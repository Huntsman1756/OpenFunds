"""DuckDB read layer over the Parquet dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from cnmv_iic.errors import NotFoundError

_ISIN_LIKE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class DatasetHandle:
    root: Path

    def positions_glob(self) -> str:
        return str(self.root / "positions" / "period=*" / "*.parquet")

    def quality_glob(self) -> str:
        return str(self.root / "quality" / "period=*" / "*.parquet")


def _con(root: Path | str) -> duckdb.DuckDBPyConnection:
    root = Path(root)
    con = duckdb.connect(database=":memory:")
    pos = root / "positions"
    if not pos.exists():
        raise NotFoundError(f"no dataset under {root} — run `cnmv-iic update` first")
    # Interpolated values below are local glob paths built from --data-dir
    # and fixed column names — never user input; all values are bound params.
    con.execute(
        "CREATE VIEW positions AS "
        f"SELECT * FROM read_parquet('{DatasetHandle(root).positions_glob()}', "
        "hive_partitioning=true)"
    )
    if (root / "quality").exists():
        con.execute(
            "CREATE VIEW quality AS "
            f"SELECT * FROM read_parquet('{DatasetHandle(root).quality_glob()}', "
            "hive_partitioning=true)"
        )
    return con


def latest_period_on_or_before(root: Path | str, as_of: str | None) -> str:
    """as_of 'YYYY-MM-DD' or 'YYYY-MM'; None -> latest period in dataset."""
    con = _con(root)
    if as_of is None:
        row = con.execute("SELECT max(period) FROM positions").fetchone()
    else:
        cutoff = as_of[:7]
        row = con.execute(
            "SELECT max(period) FROM positions WHERE period <= ?", [cutoff]
        ).fetchone()
    if row is None or row[0] is None:
        raise NotFoundError(f"no positions for as-of {as_of}")
    return str(row[0])


def holdings(
    root: Path | str, fund_key: str, as_of: str | None
) -> tuple[str, list[dict]]:
    """Reported positions for one fund at the latest period <= as-of.

    fund_key: 'FI:<numero_registro>:<compartimento>' or '<numero_registro>'
    (defaults to FI compartimento *). A share-class ISIN argument raises a
    descriptive error — ISIN->CNMV-key resolution needs FONDREGISTRO, which
    is not in G1.
    """
    if _ISIN_LIKE.fullmatch(fund_key):
        raise NotFoundError(
            "share-class ISIN lookup requires FONDREGISTRO (post-G1); "
            "use the CNMV key FI:<numero_registro>:<compartimento>"
        )
    period = latest_period_on_or_before(root, as_of)
    con = _con(root)
    if ":" in fund_key:
        where, params = "fund_key = ?", [fund_key]
    else:
        where, params = "numero_registro = ?", [fund_key]
    # `where` is a fixed column name chosen above, never user input.
    sql = (
        "SELECT position_seq, kind, clase_if, descripcion_if,"
        " descripcion_valor, divisa, reported_market_value,"
        " derived_weight, isin_raw, isin_state,"
        " fund_key, xml_locator, source_artifact_id"
        f" FROM positions WHERE period = ? AND {where}"
        " ORDER BY numero_compartimento, position_seq"
    )
    rows = con.execute(sql, [period, *params]).fetchall()
    cols = [d[0] for d in con.description]
    return period, [dict(zip(cols, r, strict=True)) for r in rows]


def funds_holding(
    root: Path | str, isin: str, as_of: str | None
) -> tuple[str, list[dict]]:
    """Funds reporting a position in `isin` — REPORTED PORTFOLIO POSITIONS.

    This is not beneficial ownership: it enumerates funds whose disclosed
    portfolio includes the instrument at the latest period <= as-of.
    """
    period = latest_period_on_or_before(root, as_of)
    con = _con(root)
    rows = con.execute(
        """SELECT fund_key, entity_type, numero_registro,
                  numero_compartimento, clase_if, descripcion_if,
                  reported_market_value, derived_weight
           FROM positions
           WHERE period = ? AND isin_raw = ?
           ORDER BY reported_market_value DESC NULLS LAST""",
        [period, isin],
    ).fetchall()
    cols = [d[0] for d in con.description]
    return period, [dict(zip(cols, r, strict=True)) for r in rows]


def dataset_info(root: Path | str) -> dict:
    root = Path(root)
    con = _con(root)
    periods = [
        r[0] for r in con.execute(
            "SELECT DISTINCT period FROM positions ORDER BY 1"
        ).fetchall()
    ]
    per = con.execute(
        """SELECT period, count(*) AS positions,
                  count(DISTINCT fund_key) AS funds
           FROM positions GROUP BY period ORDER BY period"""
    ).fetchall()
    states: dict[str, int] = {}
    if (root / "quality").exists():
        states = {
            r[0]: r[1] for r in con.execute(
                "SELECT state, count(*) FROM quality GROUP BY state"
            ).fetchall()
        }
    manifests = {}
    mdir = root / "manifests"
    if mdir.exists():
        import json

        for f in sorted(mdir.glob("*.json")):
            manifests[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    return {
        "periods": periods,
        "per_period": [
            {"period": p, "positions": n, "funds": f} for p, n, f in per
        ],
        "quality_states": states,
        "manifests": manifests,
    }
