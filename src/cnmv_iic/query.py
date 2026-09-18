"""DuckDB read layer over the Parquet dataset."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import duckdb

from cnmv_iic.domain import (
    Compartment,
    FundRecord,
    Institution,
    IsinState,
    Provenance,
    Resolution,
    ResolutionKind,
    ShareClass,
)
from cnmv_iic.errors import NotFoundError
from cnmv_iic.identity import ShareClassRow, diff_registry, resolve

_ISIN_LIKE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


@dataclass(frozen=True)
class DatasetHandle:
    root: Path

    def glob(self, table: str) -> str:
        return str(self.root / table / "period=*" / "*.parquet")


def _con(root: Path | str) -> duckdb.DuckDBPyConnection:
    root = Path(root)
    if not root.exists():
        raise NotFoundError(f"no dataset under {root} — run `cnmv-iic update` first")
    con = duckdb.connect(database=":memory:")
    for table in ("positions", "quality", "funds", "compartments", "share_classes"):
        if (root / table).exists():
            glob = str(root / table / "period=*" / "*.parquet")
            con.execute(
                f"CREATE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
            )
    return con


def _rows(con: duckdb.DuckDBPyConnection) -> list[dict]:
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r, strict=True)) for r in con.fetchall()]


def _latest_period(con: duckdb.DuckDBPyConnection, table: str,
                   cutoff: str | None) -> str | None:
    if cutoff is None:
        row = con.execute(f"SELECT max(period) FROM {table}").fetchone()
    else:
        row = con.execute(
            f"SELECT max(period) FROM {table} WHERE period <= ?", [cutoff]
        ).fetchone()
    return row[0] if row and row[0] else None


def _positions_period(con: duckdb.DuckDBPyConnection, as_of: str | None) -> str:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables"
        " WHERE table_name = 'positions'").fetchone()
    if not row or not row[0]:
        raise NotFoundError(
            "no FONDCART positions in dataset — "
            "run `cnmv-iic update` for a cadence period")
    cutoff = as_of[:7] if as_of else None
    period = _latest_period(con, "positions", cutoff)
    if period is None:
        raise NotFoundError(f"no positions for as-of {as_of}")
    return period


def _registry_period(con: duckdb.DuckDBPyConnection, as_of: str | None) -> str | None:
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_name IN ('funds','share_classes')").fetchall()}
    if "share_classes" not in tables:
        return None
    return _latest_period(con, "share_classes", as_of[:7] if as_of else None)


def _share_class_rows(con: duckdb.DuckDBPyConnection,
                      period: str) -> list[ShareClassRow]:
    con.execute(
        "SELECT share_class_key, fund_key, compartment_key, isin_raw,"
        " isin_state, denominacion_clase, xml_locator, source_artifact_id"
        " FROM share_classes WHERE period = ?", [period])
    return [ShareClassRow(**r) for r in _rows(con)]


def _fund_owners(con: duckdb.DuckDBPyConnection, period: str) -> dict[str, tuple[str, ...]]:
    con.execute(
        "SELECT fund_key, compartment_key FROM compartments WHERE period = ?"
        " ORDER BY numero_compartimento", [period])
    owners: dict[str, list[str]] = {}
    for fk, ck in con.fetchall():
        owners.setdefault(fk, []).append(ck)
    return {k: tuple(v) for k, v in owners.items()}


def holdings(
    root: Path | str, identifier: str, as_of: str | None
) -> tuple[str, dict, list[dict]]:
    """Reported positions for a fund/compartment/share-class at the latest
    positions period <= as-of. Returns (period, resolution_info, rows).

    When registry data exists, the identifier is resolved fail-closed through
    FONDREGISTRO (ISIN -> share class -> compartment portfolio owner). Without
    registry data the identifier is treated as a positions key directly.
    """
    con = _con(root)
    period = _positions_period(con, as_of)

    reg_period = _registry_period(con, period)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period),
        )
        if resolution.kind == ResolutionKind.AMBIGUOUS:
            raise NotFoundError(
                f"cannot resolve {identifier!r}: {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        if resolution.kind == ResolutionKind.NOT_FOUND:
            # Registry may legitimately lack entities that FONDCART reports
            # (e.g. entity types outside FONDREGISTRO). Exact key match against
            # positions stays allowed — still no fuzzy lookup.
            hit = _positions_by_key(con, period, identifier)
            if hit is None:
                raise NotFoundError(
                    f"cannot resolve {identifier!r}: {resolution.kind.value}"
                    + (f" — {resolution.note}" if resolution.note else ""))
            kind, rows = hit
            info = _resolution_info(resolution)
            info["resolved_as"] = kind.value
            info["note"] = ((resolution.note or "")
                            + " — matched positions key directly").strip(" —")
            return period, info, rows
        owners = list(resolution.portfolio_owners)
        con.execute(
            "SELECT position_seq, kind, clase_if, descripcion_if,"
            " descripcion_valor, divisa, reported_market_value,"
            " derived_weight, isin_raw, isin_state,"
            " fund_key, xml_locator, source_artifact_id"
            f" FROM positions WHERE period = ?"
            f" AND fund_key IN ({','.join('?' for _ in owners)})"
            " ORDER BY fund_key, position_seq",
            [period, *owners],
        )
        return period, _resolution_info(resolution), _rows(con)

    # Fallback: no registry ingested — treat identifier as a positions key.
    if _ISIN_LIKE.fullmatch(identifier):
        raise NotFoundError(
            "share-class ISIN lookup requires FONDREGISTRO data "
            "(re-run `cnmv-iic update`)")
    hit = _positions_by_key(con, period, identifier)
    if hit is None:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: unrecognized identifier format")
    kind, rows = hit
    info = {
        "requested_identifier": identifier,
        "resolved_as": kind.value,
        "share_class_key": None,
        "share_class_isin": None,
        "portfolio_owners": None,
        "portfolio_scope": "compartment",
        "registry_artifact_id": None,
        "registry_locator": None,
        "note": "resolved without registry data",
    }
    return period, info, rows


def _positions_by_key(
    con: duckdb.DuckDBPyConnection, period: str, identifier: str
) -> tuple[ResolutionKind, list[dict]] | None:
    """Exact positions-key match (no registry involved). None if the
    identifier is not a positions-key format."""
    parts = identifier.split(":")
    if len(parts) >= 3:
        where, params = "fund_key = ?", [identifier]
        kind = ResolutionKind.EXACT_COMPARTMENT
    elif len(parts) == 2:
        where, params = "fund_key LIKE ? || ':%'", [identifier]
        kind = ResolutionKind.EXACT_FUND
    elif identifier.isdigit():
        where, params = "numero_registro = ?", [identifier]
        kind = ResolutionKind.EXACT_FUND
    else:
        return None
    con.execute(
        "SELECT position_seq, kind, clase_if, descripcion_if,"
        " descripcion_valor, divisa, reported_market_value,"
        " derived_weight, isin_raw, isin_state,"
        " fund_key, xml_locator, source_artifact_id"
        f" FROM positions WHERE period = ? AND {where}"
        " ORDER BY fund_key, position_seq",
        [period, *params],
    )
    return kind, _rows(con)


def _resolution_info(res: Resolution) -> dict:
    return {
        "requested_identifier": res.requested,
        "resolved_as": res.kind.value,
        "share_class_key": res.share_class_key,
        "share_class_isin": res.share_class_isin,
        "fund_key": res.fund_key,
        "portfolio_owners": list(res.portfolio_owners),
        "portfolio_scope": "compartment",
        "registry_artifact_id": res.registry_artifact_id,
        "registry_locator": res.registry_locator,
        "note": res.note,
    }


def funds_holding(
    root: Path | str, isin: str, as_of: str | None
) -> tuple[str, list[dict]]:
    """Funds reporting a position in `isin` — REPORTED PORTFOLIO POSITIONS.

    This is not beneficial ownership: it enumerates funds whose disclosed
    portfolio includes the instrument at the latest period <= as-of.
    Fund names come from FONDREGISTRO at the same period when available.
    """
    con = _con(root)
    period = _positions_period(con, as_of)
    if _registry_period(con, period) is not None:
        con.execute(
            "SELECT p.fund_key, f.denominacion, p.entity_type,"
            " p.numero_registro, p.numero_compartimento, p.clase_if,"
            " p.descripcion_if, p.reported_market_value, p.derived_weight"
            " FROM positions p LEFT JOIN funds f"
            "  ON f.period = p.period"
            "  AND f.entity_type = p.entity_type"
            "  AND f.numero_registro = p.numero_registro"
            " WHERE p.period = ? AND p.isin_raw = ?"
            " ORDER BY p.reported_market_value DESC NULLS LAST",
            [period, isin],
        )
    else:
        con.execute(
            "SELECT fund_key, NULL AS denominacion, entity_type,"
            " numero_registro, numero_compartimento, clase_if,"
            " descripcion_if, reported_market_value, derived_weight"
            " FROM positions WHERE period = ? AND isin_raw = ?"
            " ORDER BY reported_market_value DESC NULLS LAST",
            [period, isin],
        )
    return period, _rows(con)


def _require_registry(root: Path | str) -> duckdb.DuckDBPyConnection:
    con = _con(root)
    if _registry_period(con, None) is None:
        raise NotFoundError(
            "no FONDREGISTRO data in dataset — run `cnmv-iic update` first")
    return con


def _registry_period_strict(
    con: duckdb.DuckDBPyConnection, as_of: str | None
) -> str:
    period = _registry_period(con, as_of)
    if period is None:
        raise NotFoundError(f"no FONDREGISTRO data for as-of {as_of}")
    return period


def fund_info(
    root: Path | str, identifier: str, as_of: str | None
) -> tuple[str, dict, dict]:
    """Registry record for a fund/compartment/share-class identifier."""
    con = _require_registry(root)
    period = _registry_period_strict(con, as_of)
    resolution = resolve(
        identifier,
        share_classes=_share_class_rows(con, period),
        funds=_fund_owners(con, period),
    )
    if resolution.kind in (ResolutionKind.NOT_FOUND, ResolutionKind.AMBIGUOUS):
        raise NotFoundError(
            f"cannot resolve {identifier!r}: {resolution.kind.value}"
            + (f" — {resolution.note}" if resolution.note else ""))
    fk = resolution.fund_key
    con.execute("SELECT * FROM funds WHERE period = ? AND fund_key = ?",
                [period, fk])
    fund = _rows(con)[0]
    con.execute(
        "SELECT compartment_key, numero_compartimento, denominacion,"
        " n_classes FROM compartments"
        " WHERE period = ? AND fund_key = ? ORDER BY numero_compartimento",
        [period, fk])
    comps = _rows(con)
    con.execute(
        "SELECT share_class_key, compartment_key, numero_clase, isin_raw,"
        " isin_state, denominacion_clase, denominacion_compartimento,"
        " xml_locator, source_artifact_id"
        " FROM share_classes WHERE period = ? AND fund_key = ?"
        " ORDER BY numero_compartimento, numero_clase",
        [period, fk])
    classes = _rows(con)
    return period, _resolution_info(resolution), {
        "fund": fund, "compartments": comps, "share_classes": classes,
    }


def share_class_info(
    root: Path | str, identifier: str, as_of: str | None
) -> tuple[str, dict, dict]:
    """One share class + its fund/compartment context."""
    con = _require_registry(root)
    period = _registry_period_strict(con, as_of)
    resolution = resolve(
        identifier,
        share_classes=_share_class_rows(con, period),
        funds=_fund_owners(con, period),
    )
    if resolution.kind != ResolutionKind.EXACT_SHARE_CLASS:
        raise NotFoundError(
            f"{identifier!r} does not resolve to a single share class:"
            f" {resolution.kind.value}"
            + (f" — {resolution.note}" if resolution.note else ""))
    con.execute(
        "SELECT * FROM share_classes WHERE period = ? AND share_class_key = ?",
        [period, resolution.share_class_key])
    sc = _rows(con)[0]
    con.execute("SELECT * FROM funds WHERE period = ? AND fund_key = ?",
                [period, resolution.fund_key])
    return period, _resolution_info(resolution), {
        "share_class": sc, "fund": _rows(con)[0],
    }


def funds_by_institution(
    root: Path | str, role: str, numero_registro: str, as_of: str | None
) -> tuple[str, dict | None, list[dict]]:
    """Funds managed/deposited by an institution registry number.

    role: 'gestora' | 'depositario'. Returns (period, institution, funds).
    """
    if role not in ("gestora", "depositario"):
        raise NotFoundError(f"unknown role {role!r}")
    con = _require_registry(root)
    period = _registry_period_strict(con, as_of)
    col = f"{role}_numero_registro"
    name_col = f"{role}_denominacion"
    con.execute(
        f"SELECT fund_key, denominacion, etf, n_compartments,"
        f" n_share_classes, {name_col} AS institution_name"
        f" FROM funds WHERE period = ? AND {col} = ?"
        " ORDER BY entity_type, numero_registro",
        [period, numero_registro])
    rows = _rows(con)
    institution = ({"numero_registro": numero_registro,
                    "denominacion": rows[0]["institution_name"], "role": role}
                   if rows else None)
    return period, institution, rows


def _fund_records_at(
    con: duckdb.DuckDBPyConnection, period: str
) -> list[FundRecord]:
    """Reconstruct FundRecords from the registry parquet tables at a period."""
    con.execute("SELECT * FROM funds WHERE period = ?", [period])
    funds = _rows(con)
    con.execute(
        "SELECT fund_key, numero_compartimento, denominacion"
        " FROM compartments WHERE period = ?", [period])
    comps = _rows(con)
    con.execute(
        "SELECT fund_key, numero_compartimento, numero_clase, isin_raw,"
        " isin_state, denominacion_clase FROM share_classes WHERE period = ?",
        [period])
    classes = _rows(con)

    def _comp(fk: str, nc: str) -> Compartment:
        cls = tuple(
            ShareClass(
                numero_clase=c["numero_clase"],
                isin_raw=c["isin_raw"],
                isin_state=IsinState(c["isin_state"]),
                denominacion=c["denominacion_clase"],
            )
            for c in classes
            if c["fund_key"] == fk and c["numero_compartimento"] == nc
        )
        den = next(
            (c["denominacion"] for c in comps
             if c["fund_key"] == fk and c["numero_compartimento"] == nc),
            None,
        )
        return Compartment(numero_compartimento=nc, denominacion=den,
                           classes=cls)

    out = []
    for f in funds:
        fk = f["fund_key"]
        ncs = [c["numero_compartimento"] for c in comps
               if c["fund_key"] == fk]
        out.append(FundRecord(
            entity_type=f["entity_type"],
            numero_registro=f["numero_registro"],
            denominacion=f["denominacion"],
            etf=f["etf"],
            gestora=Institution(
                numero_registro=f["gestora_numero_registro"],
                denominacion=f["gestora_denominacion"],
                tipo=f["gestora_tipo"],
                grupo_numero=f["grupo_gestora_numero"],
                grupo_denominacion=f["grupo_gestora_denominacion"]),
            depositario=Institution(
                numero_registro=f["depositario_numero_registro"],
                denominacion=f["depositario_denominacion"],
                grupo_numero=f["grupo_depositario_numero"],
                grupo_denominacion=f["grupo_depositario_denominacion"]),
            compartments=tuple(_comp(fk, nc) for nc in ncs),
            period=period,
            provenance=Provenance(
                source_artifact_id=f["source_artifact_id"],
                source_sha256=f["source_sha256"],
                member_name="",
                member_sha256="",
                xml_locator=f["xml_locator"],
                parser=f["parser"],
                parser_version=f["parser_version"]),
        ))
    return out


def identity_events(
    root: Path | str, from_period: str, to_period: str,
    fund: str | None = None,
) -> list[dict]:
    """Mechanical identity diff between two observed registry periods."""
    from dataclasses import asdict

    con = _require_registry(root)
    events = diff_registry(
        _fund_records_at(con, from_period),
        _fund_records_at(con, to_period),
    )
    if fund is not None:
        res = resolve(fund, _share_class_rows(con, to_period),
                      _fund_owners(con, to_period))
        fk = res.fund_key or fund
        events = [e for e in events if e.fund_key == fk]
    return [asdict(e) for e in events]


def dataset_info(root: Path | str) -> dict:
    root = Path(root)
    con = _con(root)
    out: dict = {"periods": [], "per_period": [], "registry_periods": []}
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "positions" in tables:
        periods = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM positions ORDER BY 1").fetchall()]
        per = _rows(con.execute(
            "SELECT period, count(*) AS positions,"
            " count(DISTINCT fund_key) AS funds"
            " FROM positions GROUP BY period ORDER BY period"))
        out["periods"] = periods
        out["per_period"] = per
    if "funds" in tables:
        out["registry_periods"] = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM funds ORDER BY 1").fetchall()]
        out["registry_per_period"] = _rows(con.execute(
            "SELECT period, count(*) AS funds,"
            " sum(n_compartments) AS compartments,"
            " sum(n_share_classes) AS share_classes"
            " FROM funds GROUP BY period ORDER BY period"))
    if "quality" in tables:
        out["quality_states"] = {
            r[0]: r[1] for r in con.execute(
                "SELECT state, count(*) FROM quality GROUP BY state").fetchall()}
    manifests = {}
    mdir = root / "manifests"
    if mdir.exists():
        import json

        for f in sorted(mdir.glob("*.json")):
            manifests[f.stem] = json.loads(f.read_text(encoding="utf-8"))
    out["manifests"] = manifests
    return out
