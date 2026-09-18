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
    for table in ("positions", "quality", "funds", "compartments",
                  "share_classes", "daily"):
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


def _positions_period(
    con: duckdb.DuckDBPyConnection, as_of: str | None, *, exact: bool = False
) -> str:
    row = con.execute(
        "SELECT count(*) FROM information_schema.tables"
        " WHERE table_name = 'positions'").fetchone()
    if not row or not row[0]:
        raise NotFoundError(
            "no FONDCART positions in dataset — "
            "run `cnmv-iic update` for a cadence period")
    cutoff = as_of[:7] if as_of else None
    if exact and cutoff is not None:
        hit = con.execute(
            "SELECT count(*) FROM positions WHERE period = ?",
            [cutoff]).fetchone()
        if not hit or not hit[0]:
            raise NotFoundError(
                f"no positions snapshot exactly at {cutoff} "
                f"(--exact: no fallback to an earlier period)")
        return cutoff
    period = _latest_period(con, "positions", cutoff)
    if period is None:
        raise NotFoundError(f"no positions for as-of {as_of}")
    return period


def _period_meta(period: str, as_of: str | None, exact: bool) -> dict:
    """Truthfulness metadata: never let a stale snapshot look contemporaneous."""
    return {
        "requested_as_of": as_of,
        "portfolio_period": period,
        "resolution_mode": ("exact" if exact
                            else "latest_available_before_or_on"),
        "stale": bool(as_of and period < as_of[:7]),
    }


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
    root: Path | str, identifier: str, as_of: str | None, *,
    exact: bool = False,
) -> tuple[str, dict, list[dict]]:
    """Reported positions for a fund/compartment/share-class.

    Default temporal semantics: latest positions period <= as-of, exposed
    honestly via `requested_as_of` / `portfolio_period` / `resolution_mode` /
    `stale` — a fallback snapshot can never masquerade as contemporaneous.
    `exact=True` fails when no snapshot exists at the as-of month itself.

    When registry data exists, the identifier is resolved fail-closed through
    FONDREGISTRO (ISIN -> share class -> compartment portfolio owner). Without
    registry data the identifier is treated as a positions key directly.
    """
    con = _con(root)
    period = _positions_period(con, as_of, exact=exact)
    meta = _period_meta(period, as_of, exact)

    reg_period = _registry_period(con, period)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period),
        )
        if resolution.kind in (ResolutionKind.AMBIGUOUS,
                               ResolutionKind.INVALID_IDENTIFIER):
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
            return period, info | meta, rows
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
        return period, _resolution_info(resolution) | meta, _rows(con)

    # Fallback: no registry ingested — treat identifier as a positions key.
    if _ISIN_LIKE.fullmatch(identifier) or (
            len(identifier) == 12 and identifier[:2].isalpha()):
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
    return period, info | meta, rows


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
    root: Path | str, isin: str, as_of: str | None, *,
    exact: bool = False,
) -> tuple[str, dict, list[dict]]:
    """Funds reporting a position in `isin` — REPORTED PORTFOLIO POSITIONS.

    This is not beneficial ownership: it enumerates funds whose disclosed
    portfolio includes the instrument at the latest period <= as-of
    (or the exact as-of month with `exact=True`). Fund names come from
    FONDREGISTRO at the same period when available.
    """
    con = _con(root)
    period = _positions_period(con, as_of, exact=exact)
    meta = _period_meta(period, as_of, exact)
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
    return period, meta, _rows(con)


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


def _daily_share_class_key(
    con: duckdb.DuckDBPyConnection, identifier: str, as_of: str | None
) -> tuple[str, dict]:
    """Resolve an identifier to ONE share-class key for daily observations.

    Grain contract: NAV/AUM/investors are per-share-class — a fund or
    compartment identifier can never resolve to a class-level series.
    Resolution uses the registry at the latest period <= as-of when it
    exists; without registry data only the full FI:r:c:k key is accepted.
    """
    if "daily" not in {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}:
        raise NotFoundError(
            "no FONDMENS data in dataset — run `cnmv-iic update` first")
    reg_period = _registry_period(con, as_of)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period),
        )
        if resolution.kind != ResolutionKind.EXACT_SHARE_CLASS:
            raise NotFoundError(
                f"{identifier!r} does not resolve to a single share class:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        key = resolution.share_class_key
        if key is None:
            raise NotFoundError(
                f"cannot resolve {identifier!r}: share class key absent")
        return key, _resolution_info(resolution)
    if identifier.count(":") == 3:
        return identifier, {
            "requested_identifier": identifier,
            "resolved_as": ResolutionKind.EXACT_SHARE_CLASS.value,
            "share_class_key": identifier,
            "share_class_isin": None,
            "note": "resolved without registry data",
        }
    raise NotFoundError(
        f"cannot resolve {identifier!r}: daily observations require a "
        f"share-class ISIN or full key FI:<reg>:<comp>:<clase>")


def daily_series(
    root: Path | str, identifier: str, metric: str,
    from_date: str | None, to_date: str | None,
) -> tuple[dict, list[dict]]:
    """Daily observed values for one share class and one metric.

    OBSERVED values only in the value column — sentinel/missing/invalid
    cells keep NULL + verbatim raw + explicit state. No forward-fill,
    no interpolation, no derived returns.
    """
    if metric not in ("nav", "aum", "investors"):
        raise NotFoundError(f"unknown daily metric {metric!r}")
    con = _con(root)
    key, info = _daily_share_class_key(con, identifier, to_date)
    clauses, params = ["share_class_key = ?"], [key]
    if from_date:
        clauses.append("observation_date >= ?")
        params.append(from_date)
    if to_date:
        clauses.append("observation_date <= ?")
        params.append(to_date)
    con.execute(
        f"SELECT observation_date, day_index, period,"
        f" {metric} AS value, {metric}_raw AS raw,"
        f" {metric}_state AS state, registry_state, isin_raw,"
        f" source_artifact_id, xml_locator"
        f" FROM daily WHERE {' AND '.join(clauses)}"
        f" ORDER BY observation_date",
        params,
    )
    rows = _rows(con)
    meta = info | {
        "metric": metric,
        "from_date": from_date,
        "to_date": to_date,
        "observations": len(rows),
        "observed": sum(1 for r in rows if r["state"] == "observed"),
        "semantics": "EUR values; NULL = no observation (see state/raw)",
    }
    return meta, rows


def class_observation_summary(
    root: Path | str, identifier: str, as_of: str | None
) -> tuple[dict, dict]:
    """Coverage summary of one share class's daily observations."""
    con = _con(root)
    key, info = _daily_share_class_key(con, identifier, as_of)
    con.execute(
        "SELECT min(observation_date) AS first_observed,"
        " max(observation_date) AS last_observed,"
        " count(DISTINCT period) AS periods,"
        " count(*) AS rows,"
        " sum(CASE WHEN nav_state='observed' THEN 1 ELSE 0 END)"
        " AS nav_observed,"
        " sum(CASE WHEN nav_state='source_zero_sentinel' THEN 1 ELSE 0 END)"
        " AS nav_sentinel,"
        " sum(CASE WHEN aum_state='observed' THEN 1 ELSE 0 END)"
        " AS aum_observed,"
        " sum(CASE WHEN investors_state='observed' THEN 1 ELSE 0 END)"
        " AS investors_observed,"
        " sum(CASE WHEN nav_state='missing' THEN 1 ELSE 0 END) AS missing,"
        " sum(CASE WHEN registry_state='unresolved_registry_reference'"
        " THEN 1 ELSE 0 END) AS unresolved_days"
        " FROM daily WHERE share_class_key = ?",
        [key],
    )
    summary = _rows(con)[0]
    con.execute(
        "SELECT DISTINCT period FROM daily WHERE share_class_key = ?"
        " ORDER BY 1", [key])
    summary["observed_periods"] = [r["period"] for r in _rows(con)]
    return info, summary


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
    if "daily" in tables:
        out["daily_periods"] = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM daily ORDER BY 1").fetchall()]
        out["daily_per_period"] = _rows(con.execute(
            "SELECT period, count(*) AS observations,"
            " count(DISTINCT share_class_key) AS share_classes"
            " FROM daily GROUP BY period ORDER BY period"))
        out["daily_states"] = {
            r[0]: r[1] for r in con.execute(
                "SELECT state, count(*) FROM ("
                " SELECT nav_state AS state FROM daily UNION ALL"
                " SELECT aum_state FROM daily UNION ALL"
                " SELECT investors_state FROM daily)"
                " GROUP BY state").fetchall()}
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
