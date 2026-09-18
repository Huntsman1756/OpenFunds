"""G7-E — adjudication layer over provider evidence ledgers.

DERIVED data only: reads the G7-A..D partitions and the immutable raw
artifacts already in the ArtifactStore; never modifies provider
evidence, never picks a winner inside a conflict, and never lets a
name/ticker/country/CFI break a tie.

The evidence bundle has NO single provider snapshot date — GLEIF and
FIRDS artifacts are dated, OpenFIGI is a live retrieval campaign. What
pins the input is ``EvidenceBundle.fingerprint`` (sha256 over the
canonical ordered evidence ids), and a derived resolution is
identified by (adjudication_version, bundle_fingerprint).

Conflict context: for ``gleif=A, firds=B, A!=B`` pairs the loaded
``relationships`` table is incomplete BY CONSTRUCTION — G7-B extracted
RR records whose start LEI was a GLEIF candidate, so a FIRDS-only LEI
``B`` has no loaded ``B -> A`` record even when RR-CDF contains one
(e.g. ``B IS_SUBFUND_OF A``). The adjudicator therefore runs a second,
bounded pass over the SAME stored RR-CDF/LEI-CDF raw artifacts with
``wanted = LEIs appearing in conflict pairs`` — derived extraction
over existing evidence, not a new provider and not a G7-B rewrite.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import duckdb

from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.domain import (
    TEMPORAL_SEMANTICS_ADJ,
    AdjudicationState,
    EvidenceBundle,
    InstrumentFamilyResolution,
    InstrumentFamilyState,
    SecurityResolution,
)
from cnmv_iic.errors import NotFoundError, ParseError

ADJUDICATION_VERSION = "1"

GLEIF_PROVIDER = "gleif_anna_isin_lei"
FIRDS_PROVIDER = "esma_firds"
OPENFIGI_PROVIDER = "openfigi"


@dataclass(frozen=True)
class AdjudicationResult:
    version: str
    bundle_fingerprint: str
    exported: bool                    # False = existing manifest reused
    securities: int
    families: int
    security_states: dict[str, int]
    family_states: dict[str, int]
    adjudication_fingerprint: str | None


def _latest_manifest(dataset_root: Path, prefix: str) -> dict | None:
    mdir = dataset_root / "manifests"
    if not mdir.exists():
        return None
    cands = sorted(mdir.glob(f"{prefix}_*.json"))
    if not cands:
        return None
    # filenames embed the snapshot/retrieval date — sorted() gives latest
    manifest: dict = json.loads(cands[-1].read_text(encoding="utf-8"))
    return manifest


def discover_bundle(dataset_root: Path | str) -> EvidenceBundle:
    """Pin the latest evidence per provider family into a bundle.

    Evidence ids are ``<family>@<date>#<evidence-fingerprint>`` — the
    bundle fingerprint is sha256 over the sorted id list, so ANY change
    in any component evidence produces a different bundle.
    """
    root = Path(dataset_root)
    parts: dict[str, tuple[str, str]] = {}   # family -> (date, evidence_id)

    m = _latest_manifest(root, "resolution_gleif_anna_isin_lei")
    if m:
        d = m["provider_snapshot_date"]
        parts["gleif_isin"] = (
            d, f"gleif_anna_isin_lei@{d}#{m['resolution_fingerprint']}")
    m = _latest_manifest(root, "resolution_gleif_golden")
    if m:
        d = m["provider_snapshot_date"]
        parts["gleif_golden"] = (
            d, f"gleif_golden@{d}#{m['evidence_fingerprint']}")
    m = _latest_manifest(root, "resolution_esma_firds")
    if m:
        d = m["provider_snapshot_date"]
        parts["esma_firds"] = (
            d, f"esma_firds@{d}#{m['resolution_fingerprint']}")
    m = _latest_manifest(root, "instrument_openfigi")
    if m:
        d = m["campaign"]
        parts["openfigi"] = (
            d, f"openfigi@{d}#{m['instrument_fingerprint']}")

    if not parts:
        raise NotFoundError(
            f"no provider evidence manifests under {root / 'manifests'} "
            f"— nothing to adjudicate")

    # fail-closed: a manifest referencing a partition that no longer
    # exists is a broken bundle — never adjudicate it into silent
    # no_match rows
    required = {
        "gleif_isin": ("resolution_observations", GLEIF_PROVIDER,
                       "snapshot"),
        "gleif_golden": ("legal_entities", "gleif", "snapshot"),
        "esma_firds": ("resolution_observations", FIRDS_PROVIDER,
                       "snapshot"),
        "openfigi": ("instrument_observations", OPENFIGI_PROVIDER,
                     "retrieval"),
    }
    for fam, (table, provider, key) in required.items():
        date = parts.get(fam, (None, ""))[0]
        if date is None:
            continue
        if not (root / table / f"provider={provider}"
                / f"{key}={date}").exists():
            raise NotFoundError(
                f"broken evidence bundle: manifest claims "
                f"{fam}@{date} but {table}/provider={provider}/"
                f"{key}={date} is missing — restore the partition or "
                f"re-ingest, never adjudicate against absent evidence")

    ids = tuple(sorted(eid for _, eid in parts.values()))
    return EvidenceBundle(
        gleif_isin_snapshot=parts.get("gleif_isin", (None, ""))[0],
        gleif_golden_snapshot=parts.get("gleif_golden", (None, ""))[0],
        firds_snapshot=parts.get("esma_firds", (None, ""))[0],
        openfigi_retrieval=parts.get("openfigi", (None, ""))[0],
        evidence_ids=ids,
        fingerprint=sha256("\n".join(ids).encode("utf-8")).hexdigest(),
    )


def _load_observations(dataset_root: Path, provider: str,
                       snapshot: str | None) -> dict[str, dict]:
    """isin -> {observation_id, state} for one provider partition."""
    if snapshot is None:
        return {}
    pdir = (dataset_root / "resolution_observations"
            / f"provider={provider}" / f"snapshot={snapshot}")
    if not pdir.exists():
        return {}
    glob = str(pdir / "*.parquet")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT isin, observation_id, state FROM "
            "read_parquet(?, hive_partitioning=true)", [glob]).fetchall()
    finally:
        con.close()
    return {i: {"observation_id": o, "state": s} for i, o, s in rows}


def _load_candidates(dataset_root: Path, provider: str,
                     snapshot: str | None) -> dict[str, list[str]]:
    """observation_id -> ordered candidate LEIs."""
    if snapshot is None:
        return {}
    pdir = (dataset_root / "resolution_candidates"
            / f"provider={provider}" / f"snapshot={snapshot}")
    if not pdir.exists():
        return {}
    glob = str(pdir / "*.parquet")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT observation_id, candidate_lei FROM "
            "read_parquet(?, hive_partitioning=true) "
            "ORDER BY observation_id, candidate_index", [glob]).fetchall()
    finally:
        con.close()
    out: dict[str, list[str]] = {}
    for oid, lei in rows:
        out.setdefault(oid, []).append(lei)
    return out


def _load_instrument(dataset_root: Path, campaign: str | None,
                     ) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """isin -> observation; observation_id -> result rows."""
    if campaign is None:
        return {}, {}
    odir = (dataset_root / "instrument_observations"
            / f"provider={OPENFIGI_PROVIDER}" / f"retrieval={campaign}")
    cdir = (dataset_root / "instrument_candidates"
            / f"provider={OPENFIGI_PROVIDER}" / f"retrieval={campaign}")
    obs: dict[str, dict] = {}
    cands: dict[str, list[dict]] = {}
    con = duckdb.connect(database=":memory:")
    try:
        if odir.exists():
            oglob = str(odir / "*.parquet")
            obs = {
                i: {"observation_id": o, "state": s}
                for i, o, s in con.execute(
                    "SELECT isin, observation_id, state FROM "
                    "read_parquet(?, hive_partitioning=true)",
                    [oglob]).fetchall()
            }
        if cdir.exists():
            cglob = str(cdir / "*.parquet")
            for r in con.execute(
                "SELECT observation_id, figi, composite_figi, "
                "share_class_figi FROM "
                "read_parquet(?, hive_partitioning=true) "
                "ORDER BY observation_id, result_index",
                    [cglob]).fetchall():
                cands.setdefault(r[0], []).append(
                    {"figi": r[1], "composite_figi": r[2],
                     "share_class_figi": r[3]})
    finally:
        con.close()
    return obs, cands


def _load_gleif_context(dataset_root: Path, snapshot: str | None,
                        leis: set[str],
                        ) -> tuple[dict[tuple[str, str], list[dict]],
                                   dict[str, dict]]:
    """Loaded-evidence context: pair relations + entity records.

    Returns ((start,end) -> [relation rows], lei -> entity fields).
    """
    rels: dict[tuple[str, str], list[dict]] = {}
    ents: dict[str, dict] = {}
    if snapshot is None or not leis:
        return rels, ents
    rglob = str(dataset_root / "relationships" / "provider=gleif"
                / f"snapshot={snapshot}" / "*.parquet")
    eglob = str(dataset_root / "legal_entities" / "provider=gleif"
                / f"snapshot={snapshot}" / "*.parquet")
    wanted = sorted(leis)
    con = duckdb.connect(database=":memory:")
    try:
        if Path(rglob).parent.exists():
            for r in con.execute(
                "SELECT start_lei, end_lei, relationship_type, "
                "relationship_status, relationship_periods_json, "
                "provider_record_locator FROM "
                "read_parquet(?, hive_partitioning=true) WHERE "
                "start_lei IN (SELECT unnest(?)) AND "
                "end_lei IN (SELECT unnest(?))",
                [rglob, wanted, wanted]).fetchall():
                rels.setdefault((r[0], r[1]), []).append({
                    "start_lei": r[0], "end_lei": r[1],
                    "relationship_type": r[2],
                    "relationship_status": r[3],
                    "periods_json": r[4],
                    "provider_record_locator": r[5],
                    "source": "evidence_table",
                })
        if Path(eglob).parent.exists():
            for r in con.execute(
                "SELECT lei, legal_name, entity_category, "
                "legal_jurisdiction, entity_status FROM "
                "read_parquet(?, hive_partitioning=true) WHERE "
                "lei IN (SELECT unnest(?))",
                [eglob, wanted]).fetchall():
                ents[r[0]] = {
                    "lei": r[0], "legal_name": r[1],
                    "entity_category": r[2],
                    "legal_jurisdiction": r[3],
                    "entity_status": r[4],
                    "source": "evidence_table",
                }
    finally:
        con.close()
    return rels, ents


def _raw_context_pass(store: ArtifactStore, snapshot: str | None,
                      leis: set[str], known_entities: set[str],
                      ) -> tuple[dict[tuple[str, str], list[dict]],
                                 dict[str, dict]]:
    """Bounded second pass over the SAME stored RR-CDF/LEI-CDF raw
    artifacts with wanted = conflict LEIs — fills the one-hop gap left
    by the G7-B extraction (records whose START is a FIRDS-only LEI).
    """
    from cnmv_iic.adapters import gleif_golden

    rels: dict[tuple[str, str], list[dict]] = {}
    ents: dict[str, dict] = {}
    if snapshot is None or not leis:
        return rels, ents

    rr = store.latest_for_period(
        snapshot, provider="gleif", source_family="rr-cdf")
    if rr is not None and store.raw_path(rr).exists():
        with zipfile.ZipFile(store.raw_path(rr)) as zf:
            member, _ = gleif_golden.member_info(zf, "rr")
            for ordinal, rec in gleif_golden.iter_relationships(
                    zf, member, leis):
                if rec["end_lei"] not in leis:
                    continue
                rels.setdefault(
                    (rec["start_lei"], rec["end_lei"]), []).append({
                        "start_lei": rec["start_lei"],
                        "end_lei": rec["end_lei"],
                        "relationship_type": rec["relationship_type"],
                        "relationship_status": rec["status"],
                        "periods_json": json.dumps(
                            rec["periods"], sort_keys=True),
                        "provider_record_locator":
                            f"{member}#RelationshipRecord={ordinal}",
                        "source": "raw_artifact",
                    })

    missing = leis - known_entities
    if missing:
        lei = store.latest_for_period(
            snapshot, provider="gleif", source_family="lei-cdf")
        if lei is not None and store.raw_path(lei).exists():
            with zipfile.ZipFile(store.raw_path(lei)) as zf:
                member, _ = gleif_golden.member_info(zf, "lei2")
                for ordinal, rec in gleif_golden.iter_lei_records(
                        zf, member, missing):
                    ents[rec["lei"]] = {
                        "lei": rec["lei"],
                        "legal_name": rec["legal_name"],
                        "entity_category": rec["entity_category"],
                        "legal_jurisdiction": rec["legal_jurisdiction"],
                        "entity_status": rec["entity_status"],
                        "provider_record_locator":
                            f"{member}#LEIRecord={ordinal}",
                        "source": "raw_artifact",
                    }
    return rels, ents


def _conflict_context(a: str, b: str,
                      rels: dict[tuple[str, str], list[dict]],
                      ents: dict[str, dict]) -> str:
    """Context JSON for one CONFLICT pair — classification is
    INFORMATION, never adjudication."""
    pair_rels = (rels.get((a, b), []) + rels.get((b, a), []))
    relations = []
    for r in sorted(pair_rels, key=lambda r: (
            r["start_lei"], r["end_lei"], r["relationship_type"] or "")):
        relations.append({
            "start_lei": r["start_lei"],
            "end_lei": r["end_lei"],
            "direction": ("gleif_to_firds" if r["start_lei"] == a
                          else "firds_to_gleif"),
            "relationship_type": r["relationship_type"],
            "relationship_status": r["relationship_status"],
            "periods": json.loads(r["periods_json"] or "[]"),
            "provider_record_locator": r["provider_record_locator"],
            "source": r["source"],
        })
    ea, eb = ents.get(a), ents.get(b)
    if relations:
        kind = "direct_gleif_relation"
    elif ea is None and eb is None:
        kind = "unknown"
    elif (ea and eb and (
            ea["entity_category"] != eb["entity_category"]
            or ea["legal_jurisdiction"] != eb["legal_jurisdiction"])):
        kind = "entity_metadata_difference"
    else:
        kind = "no_direct_gleif_relation"
    return json.dumps({
        "kind": kind,
        "relationships": relations,
        "entity_a": ea,
        "entity_b": eb,
    }, sort_keys=True)


def adjudicate(
    dataset_root: Path | str,
    store: ArtifactStore | None = None,
    *,
    version: str = ADJUDICATION_VERSION,
    adjudicated_at: str | None = None,
) -> AdjudicationResult:
    """Derive security + instrument-family resolutions over the pinned
    evidence bundle. Idempotent per (version, bundle): an existing
    manifest means the derivation already ran — returns it unchanged.
    """
    from cnmv_iic.provider_ingest import _corpus_isin_universe
    from cnmv_iic.storage import write_adjudication

    root = Path(dataset_root)
    bundle = discover_bundle(root)
    mname = (root / "manifests"
             / f"adjudication_v{version}_{bundle.fingerprint[:16]}.json")
    if mname.exists():
        m = json.loads(mname.read_text(encoding="utf-8"))
        return AdjudicationResult(
            version=version,
            bundle_fingerprint=bundle.fingerprint,
            exported=False,
            securities=m["securities"],
            families=m["instrument_families"],
            security_states=m["security_states"],
            family_states=m["family_states"],
            adjudication_fingerprint=m["adjudication_fingerprint"],
        )

    universe = _corpus_isin_universe(root)
    gobs = _load_observations(root, GLEIF_PROVIDER, bundle.gleif_isin_snapshot)
    fobs = _load_observations(root, FIRDS_PROVIDER, bundle.firds_snapshot)
    gcand = _load_candidates(root, GLEIF_PROVIDER, bundle.gleif_isin_snapshot)
    fcand = _load_candidates(root, FIRDS_PROVIDER, bundle.firds_snapshot)
    iobs, icand = _load_instrument(root, bundle.openfigi_retrieval)

    resolutions: list[SecurityResolution] = []
    conflict_pairs: dict[str, tuple[str, str]] = {}
    for isin in sorted(universe):
        g = gobs.get(isin)
        f = fobs.get(isin)
        gleis = gcand.get(g["observation_id"], []) if g else []
        fleis = fcand.get(f["observation_id"], []) if f else []
        glei = gleis[0] if len(gleis) == 1 else None
        flei = fleis[0] if len(fleis) == 1 else None

        if len(gleis) > 1 or len(fleis) > 1:
            state = AdjudicationState.MULTIPLE_CANDIDATES
        elif glei and flei:
            state = (AdjudicationState.CORROBORATED if glei == flei
                     else AdjudicationState.CONFLICT)
            if state == AdjudicationState.CONFLICT:
                conflict_pairs[isin] = (glei, flei)
        elif glei:
            state = AdjudicationState.GLEIF_ONLY
        elif flei:
            state = AdjudicationState.FIRDS_ONLY
        else:
            state = AdjudicationState.NO_AUTHORITATIVE_MATCH

        resolutions.append(SecurityResolution(
            isin=isin,
            state=state,
            resolved_lei=glei if state in (
                AdjudicationState.CORROBORATED,
                AdjudicationState.GLEIF_ONLY) else (
                    flei if state == AdjudicationState.FIRDS_ONLY else None),
            gleif_observation_id=g["observation_id"] if g else None,
            firds_observation_id=f["observation_id"] if f else None,
            gleif_candidate_lei=glei,
            firds_candidate_lei=flei,
            conflict_context_json=None,      # stamped below for conflicts
            evidence_bundle_fingerprint=bundle.fingerprint,
            adjudication_version=version,
            temporal_semantics=TEMPORAL_SEMANTICS_ADJ,
        ))

    # conservation invariant — every universe ISIN produces exactly
    # one verdict; a violation means the derivation itself is broken
    if len(resolutions) != len(universe) or {
            r.isin for r in resolutions} != set(universe):
        raise ParseError(
            f"conservation violated: {len(resolutions)} verdicts for "
            f"{len(universe)} universe ISINs — refusing to publish a "
            f"partial adjudication")

    # conflict context — loaded evidence first, then bounded raw pass
    conflict_leis = {lei for pair in conflict_pairs.values() for lei in pair}
    rels, ents = _load_gleif_context(
        root, bundle.gleif_golden_snapshot, conflict_leis)
    if store is not None and conflict_leis:
        rrels, rents = _raw_context_pass(
            store, bundle.gleif_golden_snapshot,
            conflict_leis, set(ents))
        for k, v in rrels.items():
            rels.setdefault(k, []).extend(
                r for r in v if r not in rels.get(k, []))
        ents.update(rents)

    by_isin = {r.isin: r for r in resolutions}
    for isin, (a, b) in conflict_pairs.items():
        r = by_isin[isin]
        by_isin[isin] = SecurityResolution(
            **{**r.__dict__,
               "conflict_context_json": _conflict_context(a, b, rels, ents)})
    resolutions = [by_isin[i] for i in sorted(by_isin)]

    families: list[InstrumentFamilyResolution] = []
    for isin in sorted(universe):
        o = iobs.get(isin)
        rows = icand.get(o["observation_id"], []) if o else []
        if o is None or o["state"] not in (
                "matched_single", "matched_multi"):
            fstate = InstrumentFamilyState.NO_OPENFIGI_MATCH
            sc = None
            ncomp = nven = 0
        else:
            scs = {r["share_class_figi"] for r in rows
                   if r["share_class_figi"]}
            ncomp = len({r["composite_figi"] for r in rows
                         if r["composite_figi"]})
            nven = len({r["figi"] for r in rows if r["figi"]})
            if len(scs) == 0:
                fstate, sc = InstrumentFamilyState.NO_SHARE_CLASS_FIGI, None
            elif len(scs) == 1:
                fstate, sc = (InstrumentFamilyState.SINGLE_SHARE_CLASS_FIGI,
                              scs.pop())
            else:
                fstate, sc = (InstrumentFamilyState
                              .MULTIPLE_SHARE_CLASS_FIGI, None)
        families.append(InstrumentFamilyResolution(
            isin=isin,
            state=fstate,
            share_class_figi=sc,
            composite_figi_count=ncomp,
            venue_figi_count=nven,
            observation_id=o["observation_id"] if o else None,
            evidence_bundle_fingerprint=bundle.fingerprint,
            adjudication_version=version,
            temporal_semantics=TEMPORAL_SEMANTICS_ADJ,
        ))

    at = adjudicated_at or datetime.now(UTC).isoformat()
    manifest = write_adjudication(
        root,
        version=version,
        bundle_fingerprint=bundle.fingerprint,
        resolutions=resolutions,
        families=families,
        adjudicated_at=at,
        manifest_extra={
            "bundle": {
                "gleif_isin_snapshot": bundle.gleif_isin_snapshot,
                "gleif_golden_snapshot": bundle.gleif_golden_snapshot,
                "firds_snapshot": bundle.firds_snapshot,
                "openfigi_retrieval": bundle.openfigi_retrieval,
                "evidence_ids": list(bundle.evidence_ids),
            },
            "conflicts": len(conflict_pairs),
        },
    )
    return AdjudicationResult(
        version=version,
        bundle_fingerprint=bundle.fingerprint,
        exported=True,
        securities=manifest["securities"],
        families=manifest["instrument_families"],
        security_states=manifest["security_states"],
        family_states=manifest["family_states"],
        adjudication_fingerprint=manifest["adjudication_fingerprint"],
    )
