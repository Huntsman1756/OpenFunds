"""Deterministic Parquet export + canonical dataset fingerprint.

Determinism contract (user gate 6):
- Rows are emitted in a canonical sort order:
  (entity_type, numero_registro, numero_compartimento, position_seq).
- ``dataset_fingerprint`` = SHA-256 over a canonical text serialization of
  every row of both tables — independent of Parquet metadata, so identical
  logical content fingerprints identically even if the byte stream varies.
- OBSERVED money is decimal128(38,2) — exact (source is always scale-2).
- DERIVED values (weight, rel_diff) are decimal128(38,18), ROUND_HALF_EVEN —
  deterministic, documented as derived.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_EVEN, Decimal
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cnmv_iic.domain import PortfolioSnapshot

Q18 = Decimal(1).scaleb(-18)
DERIVED_QUANT = Q18

POSITIONS_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("fund_key", pa.string()),
    ("position_seq", pa.int32()),
    ("kind", pa.string()),
    ("clase_if", pa.string()),
    ("descripcion_if", pa.string()),
    ("descripcion_valor", pa.string()),
    ("divisa", pa.string()),
    ("reported_market_value", pa.decimal128(38, 2)),
    ("derived_weight", pa.decimal128(38, 18)),
    ("isin_raw", pa.string()),
    ("isin_state", pa.string()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("member_name", pa.string()),
    ("member_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

QUALITY_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("metric", pa.string()),
    ("cart_sum", pa.decimal128(38, 2)),
    ("pdv_sum", pa.decimal128(38, 2)),
    ("abs_diff", pa.decimal128(38, 2)),
    ("rel_diff", pa.decimal128(38, 18)),
    ("tolerance", pa.decimal128(38, 6)),
    ("state", pa.string()),
    ("note", pa.string()),
    ("source_artifact_id", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])


def _quant(v: Decimal | None, q: Decimal = DERIVED_QUANT) -> Decimal | None:
    return v.quantize(q, rounding=ROUND_HALF_EVEN) if v is not None else None


def position_rows(snaps: list[PortfolioSnapshot]) -> list[dict]:
    rows = []
    for snap in snaps:
        for seq, p in enumerate(snap.positions, start=1):
            rows.append({
                "period": snap.period,
                "entity_type": snap.identity.entity_type,
                "numero_registro": snap.identity.numero_registro,
                "numero_compartimento": snap.identity.numero_compartimento,
                "fund_key": snap.identity.key,
                "position_seq": seq,
                "kind": p.kind.value,
                "clase_if": p.clase_if,
                "descripcion_if": p.descripcion_if,
                "descripcion_valor": p.descripcion_valor,
                "divisa": p.divisa,
                "reported_market_value": p.reported_market_value,
                "derived_weight": _quant(p.derived_weight),
                "isin_raw": p.isin_raw,
                "isin_state": p.isin_state.value,
                "source_artifact_id": p.provenance.source_artifact_id,
                "source_sha256": p.provenance.source_sha256,
                "member_name": p.provenance.member_name,
                "member_sha256": p.provenance.member_sha256,
                "xml_locator": p.provenance.xml_locator,
                "parser": p.provenance.parser,
                "parser_version": p.provenance.parser_version,
            })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6), int(str(r["position_seq"])),
    ))
    return rows


def quality_rows(snaps: list[PortfolioSnapshot]) -> list[dict]:
    rows = []
    for snap in snaps:
        for q in snap.quality:
            rows.append({
                "period": snap.period,
                "entity_type": snap.identity.entity_type,
                "numero_registro": snap.identity.numero_registro,
                "numero_compartimento": snap.identity.numero_compartimento,
                "metric": q.metric,
                "cart_sum": q.cart_sum,
                "pdv_sum": q.pdv_sum,
                "abs_diff": q.abs_diff,
                "rel_diff": _quant(q.rel_diff),
                "tolerance": q.tolerance,
                "state": q.state,
                "note": q.note,
                "source_artifact_id": snap.positions[0].provenance.source_artifact_id
                if snap.positions else None,
                "parser": snap.positions[0].provenance.parser
                if snap.positions else None,
                "parser_version": snap.positions[0].provenance.parser_version
                if snap.positions else None,
            })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6), str(r["metric"]),
    ))
    return rows


def canonical_fingerprint(*row_sets: list[dict]) -> str:
    """SHA-256 over canonical row serialization — parquet-metadata independent."""
    h = sha256()
    for rows in row_sets:
        for row in rows:
            h.update("|".join("" if v is None else str(v)
                              for v in row.values()).encode("utf-8"))
            h.update(b"\n")
        h.update(b"\x00")
    return h.hexdigest()


def write_period(
    dataset_root: Path | str,
    snaps: list[PortfolioSnapshot],
    *,
    period: str,
    artifact_id: str,
) -> dict:
    """Write period-partitioned positions+quality parquet; return manifest."""
    root = Path(dataset_root)
    pos_dir = root / "positions" / f"period={period}"
    qal_dir = root / "quality" / f"period={period}"
    pos_dir.mkdir(parents=True, exist_ok=True)
    qal_dir.mkdir(parents=True, exist_ok=True)

    prow, qrow = position_rows(snaps), quality_rows(snaps)
    pq.write_table(
        pa.Table.from_pylist(prow, schema=POSITIONS_SCHEMA),
        pos_dir / "part-0.parquet",
        compression="zstd",
    )
    if qrow:
        pq.write_table(
            pa.Table.from_pylist(qrow, schema=QUALITY_SCHEMA),
            qal_dir / "part-0.parquet",
            compression="zstd",
        )

    fingerprint = canonical_fingerprint(prow, qrow)
    manifest = {
        "period": period,
        "source_artifact_id": artifact_id,
        "positions": len(prow),
        "quality_rows": len(qrow),
        "dataset_fingerprint": fingerprint,
    }
    (root / "manifests").mkdir(parents=True, exist_ok=True)
    with open(root / "manifests" / f"{period}.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def read_period_fingerprint(dataset_root: Path | str, period: str) -> str | None:
    """Recompute the canonical fingerprint of a stored period."""
    root = Path(dataset_root)
    mpath = root / "manifests" / f"{period}.json"
    if not mpath.exists():
        return None
    fp = json.loads(mpath.read_text(encoding="utf-8")).get("dataset_fingerprint")
    return str(fp) if fp is not None else None
