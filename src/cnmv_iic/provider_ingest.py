"""G7 provider evidence ingestion — pinned artifact -> resolution ledger.

Distinct from ``ingest.update_period`` (CNMV monthly disclosures): this
path ingests *provider* artifacts (GLEIF, later FIRDS/OpenFIGI) and writes
evidence tables partitioned by (provider, snapshot). The corpus ISIN
universe is read from the stored ``positions`` table — never invented.

Gates (docs/g7/contract.md):
- Only ``isin_state='valid'`` enters the join; masked/invalid/absent ISINs
  never become observations.
- Exact ISIN join only — zero fuzzy/fulltext.
- ``no_match`` is a first-class result, not an error.
- ``holding_periods`` and ``provider_snapshot_date`` stay separate.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from cnmv_iic.adapters import gleif_isin_lei
from cnmv_iic.artifacts.store import ArtifactStore, SourceArtifact
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.storage import write_provider_resolution

GLEIF_ISIN_LEI_PAGE = (
    "https://www.gleif.org/en/lei-data/lei-mapping/"
    "download-isin-to-lei-relationship-files"
)


@dataclass(frozen=True)
class ProviderIngestResult:
    provider: str
    snapshot_date: str
    artifact: SourceArtifact
    artifact_new: bool
    exported: bool                    # False = same evidence already stored
    observations: int
    matched: int
    multiple_candidates: int
    no_match: int
    candidates: int
    universe_isins: int
    resolution_fingerprint: str | None


def _corpus_isin_universe(dataset_root: Path) -> dict[str, tuple[str, ...]]:
    """Distinct valid ISINs -> sorted corpus periods carrying them."""
    glob = str(dataset_root / "positions" / "period=*" / "*.parquet")
    if not (dataset_root / "positions").exists():
        raise NotFoundError(
            f"no FONDCART positions under {dataset_root} — "
            f"run `cnmv-iic update` for a cadence period first")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT isin_raw, period FROM "
            "read_parquet(?, hive_partitioning=true) "
            "WHERE isin_state = 'valid' "
            "GROUP BY isin_raw, period ORDER BY isin_raw, period",
            [glob]).fetchall()
    finally:
        con.close()
    universe: dict[str, list[str]] = {}
    for isin, period in rows:
        universe.setdefault(isin, []).append(period)
    return {k: tuple(v) for k, v in universe.items()}


def ingest_gleif_isin_lei(
    store: ArtifactStore,
    dataset_root: Path | str,
    zip_path: Path | str,
    *,
    retrieved_at: datetime | None = None,
) -> ProviderIngestResult:
    """Ingest one pinned GLEIF/ANNA isin-lei daily full-snapshot ZIP.

    Idempotent per artifact bytes: re-ingesting the same ZIP produces no
    new artifact and no re-export. A *new* snapshot date creates a new
    (provider, snapshot) partition — evidence is append-only.
    """
    dataset_root = Path(dataset_root)
    zip_path = Path(zip_path)
    data = zip_path.read_bytes()

    # Snapshot date comes from the embedded member name, not user input —
    # the artifact is self-describing.
    zf = zipfile.ZipFile(zip_path)
    member_name = gleif_isin_lei.csv_member(zf)
    snapshot_date = gleif_isin_lei.member_snapshot_date(member_name)

    artifact, is_new = store.put(
        period=snapshot_date,
        source_page=GLEIF_ISIN_LEI_PAGE,
        source_url=str(zip_path),
        content_type="application/zip",
        data=data,
        retrieved_at=retrieved_at,
        provider="gleif",
        source_family="isin-lei",
        source_id_prefix="gleif-isin-lei",
    )

    manifest_name = (
        dataset_root / "manifests"
        / f"resolution_{gleif_isin_lei.PROVIDER}_{snapshot_date}.json"
    )
    if not is_new and manifest_name.exists():
        m = json.loads(manifest_name.read_text(encoding="utf-8"))
        return ProviderIngestResult(
            provider=gleif_isin_lei.PROVIDER,
            snapshot_date=snapshot_date,
            artifact=artifact,
            artifact_new=False,
            exported=False,
            observations=m["observations"],
            matched=m["matched"],
            multiple_candidates=m["multiple_candidates"],
            no_match=m["no_match"],
            candidates=m["candidates"],
            universe_isins=m["universe_isins"],
            resolution_fingerprint=m["resolution_fingerprint"],
        )

    zf = zipfile.ZipFile(store.raw_path(artifact))
    member_sha = next(
        (m.sha256 for m in artifact.members if m.name == member_name), None)
    if member_sha is None:
        raise ParseError(f"member {member_name} not in artifact manifest")

    mapping = gleif_isin_lei.load_mapping(zf, member_name)
    universe = _corpus_isin_universe(dataset_root)
    observations, candidates = gleif_isin_lei.build_observations(
        universe, mapping,
        snapshot_date=snapshot_date,
        artifact_id=artifact.source_id,
        source_sha256=artifact.sha256,
        member_name=member_name,
        member_sha256=member_sha,
        retrieved_at=artifact.retrieved_at,
    )
    manifest = write_provider_resolution(
        dataset_root,
        provider=gleif_isin_lei.PROVIDER,
        snapshot_date=snapshot_date,
        observations=observations,
        candidates=candidates,
        artifact_id=artifact.source_id,
    )
    return ProviderIngestResult(
        provider=gleif_isin_lei.PROVIDER,
        snapshot_date=snapshot_date,
        artifact=artifact,
        artifact_new=is_new,
        exported=True,
        observations=manifest["observations"],
        matched=manifest["matched"],
        multiple_candidates=manifest["multiple_candidates"],
        no_match=manifest["no_match"],
        candidates=manifest["candidates"],
        universe_isins=manifest["universe_isins"],
        resolution_fingerprint=manifest["resolution_fingerprint"],
    )


GLEIF_GOLDEN_PAGE = (
    "https://www.gleif.org/en/lei-data/gleif-concatenated-file/"
    "download-the-concatenated-file"
)


@dataclass(frozen=True)
class GoldenIngestResult:
    snapshot_date: str
    artifact_ids: dict[str, str]      # dataset -> source_id
    artifacts_new: int                # how many of the 3 were new
    exported: bool
    wanted_lei_count: int
    closure_lei_count: int
    legal_entities: int
    entities_resolved_role: int
    entities_closure_role: int
    relationships: int
    relationship_types: tuple[str, ...]
    relationship_exceptions: int
    evidence_fingerprint: str | None


def _wanted_leis(dataset_root: Path) -> set[str]:
    """Distinct candidate LEIs from G7-A resolution evidence.

    Only LEIs reachable from loaded ``resolution_candidates`` enter the
    GLEIF extraction — cnmv-iic is not a GLEIF replica.
    """
    cdir = (dataset_root / "resolution_candidates"
            / f"provider={gleif_isin_lei.PROVIDER}")
    glob = str(cdir / "snapshot=*" / "*.parquet")
    if not cdir.exists():
        raise NotFoundError(
            "no GLEIF resolution candidates — run "
            "`cnmv-iic ingest-provider gleif-isin-lei <zip>` first")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT DISTINCT candidate_lei FROM "
            "read_parquet(?, hive_partitioning=true)",
            [glob]).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def ingest_gleif_golden(
    store: ArtifactStore,
    dataset_root: Path | str,
    lei_zip: Path | str,
    rr_zip: Path | str,
    repex_zip: Path | str,
    *,
    retrieved_at: datetime | None = None,
) -> GoldenIngestResult:
    """Ingest the three GLEIF concatenated files for ONE snapshot date.

    Gate 1: all three members must declare the same snapshot date —
    mixed-date bundles are rejected fail-closed. Extraction is filtered:
    RR records whose start LEI is a resolved candidate; Level-1 records
    for resolved LEIs + the bounded one-hop closure over RR end nodes
    (no recursion); reporting exceptions for resolved LEIs.
    """
    from cnmv_iic.adapters import gleif_golden
    from cnmv_iic.storage import write_gleif_golden

    dataset_root = Path(dataset_root)
    inputs = {
        "lei2": Path(lei_zip), "rr": Path(rr_zip), "repex": Path(repex_zip)}
    members: dict[str, tuple[str, str]] = {}   # kind -> (member, snapshot)
    dates: set[str] = set()
    for kind, zp in inputs.items():
        with zipfile.ZipFile(zp) as zf:
            members[kind] = gleif_golden.member_info(zf, kind)
        dates.add(members[kind][1])
    if len(dates) != 1:
        raise ParseError(
            f"snapshot_date_mismatch across GLEIF artifacts: "
            f"{sorted(dates)} — the three files must be the same "
            f"publication date")
    snapshot_date = dates.pop()

    family = {"lei2": "lei-cdf", "rr": "rr-cdf", "repex": "repex"}
    artifacts: dict[str, tuple[SourceArtifact, bool]] = {}
    for kind, zp in inputs.items():
        a, is_new = store.put(
            period=snapshot_date,
            source_page=GLEIF_GOLDEN_PAGE,
            source_url=str(zp),
            content_type="application/zip",
            data=zp.read_bytes(),
            retrieved_at=retrieved_at,
            provider="gleif",
            source_family=family[kind],
            source_id_prefix=f"gleif-{family[kind]}",
        )
        artifacts[kind] = (a, is_new)

    manifest_path = (dataset_root / "manifests"
                     / f"resolution_gleif_golden_{snapshot_date}.json")
    if not any(n for _, n in artifacts.values()) and manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        return GoldenIngestResult(
            snapshot_date=snapshot_date,
            artifact_ids=m["source_artifact_ids"],
            artifacts_new=0,
            exported=False,
            wanted_lei_count=m["wanted_lei_count"],
            closure_lei_count=m["closure_lei_count"],
            legal_entities=m["legal_entities"],
            entities_resolved_role=m["entities_resolved_role"],
            entities_closure_role=m["entities_closure_role"],
            relationships=m["relationships"],
            relationship_types=tuple(m["relationship_types"]),
            relationship_exceptions=m["relationship_exceptions"],
            evidence_fingerprint=m["evidence_fingerprint"],
        )

    wanted = _wanted_leis(dataset_root)
    if not wanted:
        raise NotFoundError(
            "zero resolved candidate LEIs — nothing to close over")

    def _member_sha(kind: str) -> str:
        name = members[kind][0]
        sha = next((m.sha256 for m in artifacts[kind][0].members
                    if m.name == name), None)
        if sha is None:
            raise ParseError(f"member {name} not in artifact manifest")
        return sha

    artifact_ids = {
        gleif_golden.DATASET_LEI: artifacts["lei2"][0].source_id,
        gleif_golden.DATASET_RR: artifacts["rr"][0].source_id,
        gleif_golden.DATASET_REPEX: artifacts["repex"][0].source_id,
    }

    # RR first: learn the one-hop closure (end nodes not already wanted)
    relationships = []
    with zipfile.ZipFile(store.raw_path(artifacts["rr"][0])) as zf:
        member, _ = members["rr"]
        for ordinal, rec in gleif_golden.iter_relationships(
                zf, member, wanted):
            relationships.append(gleif_golden.build_relationship_observation(
                rec, snapshot_date=snapshot_date,
                artifact_id=artifact_ids[gleif_golden.DATASET_RR],
                source_sha256=artifacts["rr"][0].sha256,
                member_name=member, member_sha256=_member_sha("rr"),
                retrieved_at=artifacts["rr"][0].retrieved_at,
                ordinal=ordinal))
    closure = {r.end_lei for r in relationships if r.end_lei} - wanted

    exceptions = []
    with zipfile.ZipFile(store.raw_path(artifacts["repex"][0])) as zf:
        member, _ = members["repex"]
        for ordinal, rec in gleif_golden.iter_exceptions(
                zf, member, wanted):
            exceptions.append(gleif_golden.build_exception_observation(
                rec, snapshot_date=snapshot_date,
                artifact_id=artifact_ids[gleif_golden.DATASET_REPEX],
                source_sha256=artifacts["repex"][0].sha256,
                member_name=member, member_sha256=_member_sha("repex"),
                retrieved_at=artifacts["repex"][0].retrieved_at,
                ordinal=ordinal))

    entities = []
    with zipfile.ZipFile(store.raw_path(artifacts["lei2"][0])) as zf:
        member, _ = members["lei2"]
        for ordinal, rec in gleif_golden.iter_lei_records(
                zf, member, wanted | closure):
            role = ("resolved" if rec["lei"] in wanted
                    else "closure_end_node")
            entities.append(gleif_golden.build_entity_observation(
                rec, role=role, snapshot_date=snapshot_date,
                artifact_id=artifact_ids[gleif_golden.DATASET_LEI],
                source_sha256=artifacts["lei2"][0].sha256,
                member_name=member, member_sha256=_member_sha("lei2"),
                retrieved_at=artifacts["lei2"][0].retrieved_at,
                ordinal=ordinal))

    m = write_gleif_golden(
        dataset_root,
        snapshot_date=snapshot_date,
        entities=entities,
        relationships=relationships,
        exceptions=exceptions,
        artifact_ids=artifact_ids,
        wanted_lei_count=len(wanted),
        closure_lei_count=len(closure),
    )
    return GoldenIngestResult(
        snapshot_date=snapshot_date,
        artifact_ids=artifact_ids,
        artifacts_new=sum(1 for _, n in artifacts.values() if n),
        exported=True,
        wanted_lei_count=m["wanted_lei_count"],
        closure_lei_count=m["closure_lei_count"],
        legal_entities=m["legal_entities"],
        entities_resolved_role=m["entities_resolved_role"],
        entities_closure_role=m["entities_closure_role"],
        relationships=m["relationships"],
        relationship_types=tuple(m["relationship_types"]),
        relationship_exceptions=m["relationship_exceptions"],
        evidence_fingerprint=m["evidence_fingerprint"],
    )


FIRDS_PAGE = (
    "https://registers.esma.europa.eu/publication/searchRegister"
    "?core=esma_registers_firds_files"
)


@dataclass(frozen=True)
class FirdsIngestResult:
    provider: str
    snapshot_date: str
    artifact_ids: dict[str, str]      # member -> source_id
    artifacts_new: int
    exported: bool
    observations: int
    matched: int
    multiple_candidates: int
    no_candidate: int
    no_match: int
    candidates: int
    evidence_records: int
    universe_isins: int
    resolution_fingerprint: str | None


def ingest_firds_fulins(
    store: ArtifactStore,
    dataset_root: Path | str,
    zip_paths: Sequence[Path | str],
    *,
    retrieved_at: datetime | None = None,
) -> FirdsIngestResult:
    """Ingest a complete pinned FULINS snapshot (all in-scope parts).

    Gates: every part declares the same snapshot date (filename AND
    RptgPrd/Dt must agree); each asset letter's part set must be
    complete (NNofMM). Absence of an ISIN = ``no_match`` — never
    inferred ``not_applicable``.
    """
    from cnmv_iic.adapters import firds_fulins

    dataset_root = Path(dataset_root)
    paths = [Path(p) for p in zip_paths]
    if not paths:
        raise ParseError("no FULINS files provided")

    infos: dict[str, firds_fulins.FirdsFileInfo] = {}
    dates: set[str] = set()
    for p in paths:
        with zipfile.ZipFile(p) as zf:
            info = firds_fulins.file_info(zf)
            rpt = firds_fulins.rptg_period_date(zf, info.member_name)
        if rpt and rpt != info.snapshot_date:
            raise ParseError(
                f"{p.name}: filename date {info.snapshot_date} disagrees"
                f" with RptgPrd/Dt {rpt}")
        infos[info.member_name] = info
        dates.add(info.snapshot_date)
    if len(dates) != 1:
        raise ParseError(
            f"snapshot_date_mismatch across FULINS parts: {sorted(dates)}")
    snapshot_date = dates.pop()

    # completeness: all parts 1..N of each asset letter present
    by_asset: dict[str, set[int]] = {}
    totals: dict[str, int] = {}
    for i in infos.values():
        by_asset.setdefault(i.asset_letter, set()).add(i.part)
        totals[i.asset_letter] = i.total_parts
    incomplete = {
        a: sorted(set(range(1, totals[a] + 1)) - parts)
        for a, parts in by_asset.items()
        if parts != set(range(1, totals[a] + 1))}
    if incomplete:
        raise ParseError(f"incomplete FULINS parts: {incomplete}")

    artifacts: dict[str, tuple[SourceArtifact, bool]] = {}
    for p in paths:
        with zipfile.ZipFile(p) as zf:
            info = firds_fulins.file_info(zf)
        a, is_new = store.put(
            period=snapshot_date,
            source_page=FIRDS_PAGE,
            source_url=str(p),
            content_type="application/zip",
            data=p.read_bytes(),
            retrieved_at=retrieved_at,
            provider="esma",
            # one dedupe key per part — a shared family would make all
            # parts collide on (period, provider, source_family)
            source_family=(
                f"firds-fulins-{info.asset_letter}{info.part:02d}"),
            source_id_prefix=(
                f"esma-fulins-{info.asset_letter}{info.part:02d}"),
        )
        artifacts[info.member_name] = (a, is_new)

    manifest_path = (dataset_root / "manifests"
                     / f"resolution_esma_firds_{snapshot_date}.json")
    if (not any(n for _, n in artifacts.values())
            and manifest_path.exists()):
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        return FirdsIngestResult(
            provider=firds_fulins.PROVIDER,
            snapshot_date=snapshot_date,
            artifact_ids=m["source_artifact_ids"],
            artifacts_new=0,
            exported=False,
            observations=m["observations"],
            matched=m["matched"],
            multiple_candidates=m["multiple_candidates"],
            no_candidate=m["no_candidate"],
            no_match=m["no_match"],
            candidates=m["candidates"],
            evidence_records=m["evidence_records"],
            universe_isins=m["universe_isins"],
            resolution_fingerprint=m["resolution_fingerprint"],
        )

    universe = _corpus_isin_universe(dataset_root)
    wanted = set(universe)
    records: dict[str, list[tuple[str, int, dict]]] = {}
    artifact_ids: dict[str, str] = {}
    source_sha256s: dict[str, str] = {}
    member_sha256s: dict[str, str] = {}
    for member, (a, _n) in sorted(artifacts.items()):
        artifact_ids[member] = a.source_id
        source_sha256s[member] = a.sha256
        member_sha256s[member] = next(
            (m.sha256 for m in a.members if m.name == member), "")
        with zipfile.ZipFile(store.raw_path(a)) as zf:
            for ordinal, rec in firds_fulins.iter_refdata(
                    zf, member, wanted):
                records.setdefault(rec["isin"], []).append(
                    (member, ordinal, rec))

    observations, candidates, evidences = (
        firds_fulins.build_observations(
            universe, records,
            snapshot_date=snapshot_date,
            artifact_ids=artifact_ids,
            source_sha256s=source_sha256s,
            member_sha256s=member_sha256s,
            retrieved_at=artifacts[sorted(artifacts)[0]][0].retrieved_at,
        ))

    manifest = write_provider_resolution(
        dataset_root,
        provider=firds_fulins.PROVIDER,
        snapshot_date=snapshot_date,
        observations=observations,
        candidates=candidates,
        artifact_id=artifact_ids[sorted(artifact_ids)[0]],
        evidences=evidences,
        manifest_extra={
            "source_artifact_ids": artifact_ids,
            "asset_letters": sorted(by_asset),
            "files": sorted(infos),
        },
    )
    return FirdsIngestResult(
        provider=firds_fulins.PROVIDER,
        snapshot_date=snapshot_date,
        artifact_ids=artifact_ids,
        artifacts_new=sum(1 for _, n in artifacts.values() if n),
        exported=True,
        observations=manifest["observations"],
        matched=manifest["matched"],
        multiple_candidates=manifest["multiple_candidates"],
        no_candidate=manifest["no_candidate"],
        no_match=manifest["no_match"],
        candidates=manifest["candidates"],
        evidence_records=manifest["evidence_records"],
        universe_isins=manifest["universe_isins"],
        resolution_fingerprint=manifest["resolution_fingerprint"],
    )


# ---------------------------------------------------------------------------
# G7-D — OpenFIGI instrument evidence. Acquisition is campaign-based raw
# evidence (openfigi_client); this step is a pure local function of the
# stored batch artifacts — re-running it is byte-deterministic.
# ---------------------------------------------------------------------------

OPENFIGI_PAGE = "https://www.openfigi.com/api/documentation"


@dataclass(frozen=True)
class OpenFigiIngestResult:
    provider: str
    campaign: str
    batches: int
    exported: bool
    observations: int
    matched_single: int
    matched_multi: int
    no_match: int
    provider_error: int
    invalid_response: int
    candidates: int
    universe_isins: int
    instrument_fingerprint: str | None


def ingest_openfigi(
    dataset_root: Path | str,
    campaign_dir: Path | str,
) -> OpenFigiIngestResult:
    """Export a stored OpenFIGI campaign into the evidence tables.

    Reads every batch artifact under ``<campaign_dir>/batches``; the
    campaign id is the directory name (retrieval date). Universe ISINs
    without a stored job become ``provider_error`` observations — an
    incomplete campaign is visible, never silently partial.
    """
    from cnmv_iic.adapters import openfigi as openfigi_adapter
    from cnmv_iic.openfigi_client import iter_campaign
    from cnmv_iic.storage import write_instrument_evidence

    dataset_root = Path(dataset_root)
    campaign_dir = Path(campaign_dir)
    campaign = campaign_dir.name
    batches = iter_campaign(campaign_dir / "batches")
    if not batches:
        raise NotFoundError(
            f"no OpenFIGI batch artifacts under {campaign_dir}/batches")

    universe = _corpus_isin_universe(dataset_root)
    observations, candidates = openfigi_adapter.build_observations(
        universe, batches, campaign=campaign)
    # completeness gate: jobs_missing = universe ISINs with NO stored
    # positional response (batch absent/failed) — an incomplete
    # campaign is machine-visible, never silently partial
    jobs_missing = sum(
        1 for o in observations
        if o.state.value == "provider_error" and not o.batch_id)
    manifest = write_instrument_evidence(
        dataset_root,
        provider=openfigi_adapter.PROVIDER,
        campaign=campaign,
        observations=observations,
        candidates=candidates,
        manifest_extra={
            "batches": len(batches),
            "batch_ids": sorted(b.batch_id for b in batches),
            "provider_dataset": openfigi_adapter.PROVIDER_DATASET,
            "jobs_missing": jobs_missing,
            "campaign_complete": jobs_missing == 0,
        },
    )
    return OpenFigiIngestResult(
        provider=openfigi_adapter.PROVIDER,
        campaign=campaign,
        batches=len(batches),
        exported=True,
        observations=manifest["observations"],
        matched_single=manifest.get("matched_single", 0),
        matched_multi=manifest.get("matched_multi", 0),
        no_match=manifest.get("no_match", 0),
        provider_error=manifest.get("provider_error", 0),
        invalid_response=manifest.get("invalid_response", 0),
        candidates=manifest["candidates"],
        universe_isins=manifest["universe_isins"],
        instrument_fingerprint=manifest["instrument_fingerprint"],
    )
