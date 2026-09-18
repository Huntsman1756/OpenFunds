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
