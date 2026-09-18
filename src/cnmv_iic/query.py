"""DuckDB read layer over the Parquet dataset."""

from __future__ import annotations

import hashlib
import json
import re
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
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
    classify_isin,
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
                  "share_classes", "daily", "quarterly", "patrimony",
                  "derivatives", "derivative_coverage"):
        if (root / table).exists():
            glob = str(root / table / "period=*" / "*.parquet")
            con.execute(
                f"CREATE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
            )
    # G7 provider evidence — partitioned by (provider, snapshot), not period
    for table in ("resolution_observations", "resolution_candidates",
                  "resolution_candidate_evidence",
                  "legal_entities", "relationships",
                  "relationship_exceptions"):
        if (root / table).exists():
            glob = str(root / table / "provider=*" / "snapshot=*"
                       / "*.parquet")
            con.execute(
                f"CREATE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
            )
    # G7-D instrument evidence — partitioned by (provider, retrieval):
    # an API retrieval date, never a provider-issued snapshot
    for table in ("instrument_observations", "instrument_candidates"):
        if (root / table).exists():
            glob = str(root / table / "provider=*" / "retrieval=*"
                       / "*.parquet")
            con.execute(
                f"CREATE VIEW {table} AS "
                f"SELECT * FROM read_parquet('{glob}', hive_partitioning=true)"
            )
    # G7-E derived adjudication — partitioned by (version, bundle):
    # append-only, multiple logical resolutions may coexist
    for table in ("security_resolution", "instrument_family_resolution"):
        if (root / table).exists():
            glob = str(root / table / "version=*" / "bundle=*"
                       / "*.parquet")
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


def _observation_share_class_key(
    con: duckdb.DuckDBPyConnection, identifier: str, as_of: str | None,
    *, table: str = "daily", label: str = "FONDMENS daily",
) -> tuple[str, dict]:
    """Resolve an identifier to ONE share-class key for observations.

    Grain contract: NAV/AUM/investors/quarterly metrics are per-share-
    class — a fund or compartment identifier can never resolve to a
    class-level series. Resolution uses the registry at the latest
    period <= as-of when it exists; without registry data only the
    full FI:r:c:k key is accepted.
    """
    if table not in {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}:
        raise NotFoundError(
            f"no {label} data in dataset — run `cnmv-iic update` first")
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
        f"cannot resolve {identifier!r}: {label} observations require a "
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
    key, info = _observation_share_class_key(con, identifier, to_date)
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
    key, info = _observation_share_class_key(con, identifier, as_of)
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


def patrimony_reconciliation(
    root: Path | str, period: str, *,
    tolerance_rel: Decimal = Decimal("0.01"),
) -> dict:
    """Derived cross-family patrimony comparison for one period (G4-C).

    Compares OBSERVED patrimony across families at the same period end —
    informational only, never a hard gate and never written back:

    1. FONDTRIM class ``patrimonio`` vs FONDMENS month-end class ``aum``
       (last OBSERVED day; only comparable when TRIM ``codigo_divisa``
       is EUR — FONDMENS is documented EUR).
    2. FONDPATRIMDISVAR ``total_patrimonio`` vs the sum of FONDTRIM
       class ``patrimonio`` in the compartment (only when all class
       currencies equal ``codigo_divisa_iic``).
    3. FONDPATRIMDISVAR ``total_patrimonio`` vs the sum of FONDMENS
       month-end ``aum`` in the compartment (same currency check).

    ``state`` is ``match`` (rel diff <= tolerance), ``diff``,
    ``skipped_currency`` or ``skipped_missing``. Equality is NOT
    required — different cutoffs (e.g. TRIM '.00' vs MENS cents) are
    documented semantics, not errors.
    """
    con = _con(root)
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise NotFoundError(f"bad period {period!r} — expected YYYY-MM")
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    have_q = "quarterly" in tables
    have_p = "patrimony" in tables
    have_d = "daily" in tables
    if not have_q and not have_p:
        raise NotFoundError(
            f"no FONDTRIM/FONDPATRIMDISVAR data for {period} — "
            "run `cnmv-iic update` for a cadence period")
    # CREATE VIEW cannot take bound parameters — period is regex-validated.
    # Absent tables degrade to empty views so LEFT JOINs yield
    # skipped_missing rather than a catalog error.
    if have_d:
        con.execute(
            "CREATE VIEW mens_eom AS SELECT share_class_key,"
            " compartment_key, aum, observation_date FROM daily"
            f" WHERE period = '{period}' AND aum_state = 'observed'"
            " QUALIFY row_number() OVER ("
            "   PARTITION BY share_class_key ORDER BY day_index DESC) = 1",
        )
    else:
        con.execute(
            "CREATE VIEW mens_eom AS SELECT NULL::VARCHAR share_class_key,"
            " NULL::VARCHAR compartment_key, NULL::DECIMAL(38,2) aum,"
            " NULL::DATE observation_date WHERE false",
        )
    if not have_q:
        con.execute(
            "CREATE VIEW quarterly AS SELECT NULL::VARCHAR period,"
            " NULL::VARCHAR share_class_key,"
            " NULL::VARCHAR compartment_key, NULL::DECIMAL(38,2) patrimonio,"
            " NULL::VARCHAR codigo_divisa WHERE false",
        )

    rows: list[dict] = []

    def _emit(subject: str, metric: str,
              left: Decimal | None, left_src: str,
              right: Decimal | None, right_src: str,
              state: str, note: str | None) -> None:
        abs_diff = rel = None
        if state == "comparable":
            if left is not None and right is not None:
                abs_diff = abs(left - right)
                rel = (abs_diff / abs(right)) if right else (
                    Decimal(0) if abs_diff == 0 else None)
                state = ("match"
                         if rel is not None and rel <= tolerance_rel
                         else "diff")
            else:
                state = "skipped_missing"
        rows.append({
            "subject_key": subject, "metric": metric,
            "left_value": left, "left_source": left_src,
            "right_value": right, "right_source": right_src,
            "abs_diff": abs_diff, "rel_diff": rel,
            "state": state, "note": note,
        })

    # 1. TRIM class patrimonio vs MENS month-end class AUM
    con.execute(
        "SELECT q.share_class_key, q.patrimonio, m.aum, q.codigo_divisa"
        " FROM quarterly q"
        " LEFT JOIN mens_eom m USING (share_class_key)"
        " WHERE q.period = ? ORDER BY q.share_class_key", [period])
    for r in _rows(con):
        if r["patrimonio"] is None or r["aum"] is None:
            _emit(r["share_class_key"], "patrimonio_vs_mens_aum",
                  r["patrimonio"], "fondtrim.patrimonio", r["aum"],
                  "fondmens.aum@month_end", "skipped_missing",
                  "one side absent (missing element or no observed day)")
        elif r["codigo_divisa"] != "EUR":
            _emit(r["share_class_key"], "patrimonio_vs_mens_aum",
                  r["patrimonio"], "fondtrim.patrimonio", r["aum"],
                  "fondmens.aum@month_end", "skipped_currency",
                  f"class currency {r['codigo_divisa']} != MENS EUR")
        else:
            _emit(r["share_class_key"], "patrimonio_vs_mens_aum",
                  r["patrimonio"], "fondtrim.patrimonio", r["aum"],
                  "fondmens.aum@month_end", "comparable", None)

    # 2. PDV total_patrimonio vs sum of TRIM class patrimonios
    if have_p:
        con.execute(
            "SELECT p.compartment_key, p.total_patrimonio,"
            " p.codigo_divisa_iic, sum(q.patrimonio) AS trim_sum,"
            " count(DISTINCT q.codigo_divisa) AS n_currencies,"
            " max(q.codigo_divisa) AS one_currency"
            " FROM patrimony p"
            " LEFT JOIN quarterly q"
            " ON q.compartment_key = p.compartment_key"
            " AND q.period = p.period"
            " WHERE p.period = ?"
            " GROUP BY p.compartment_key, p.total_patrimonio,"
            " p.codigo_divisa_iic"
            " ORDER BY p.compartment_key", [period])
        for r in _rows(con):
            if r["total_patrimonio"] is None or r["trim_sum"] is None:
                _emit(r["compartment_key"], "total_vs_trim_class_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["trim_sum"], "sum(fondtrim.patrimonio)",
                      "skipped_missing", None)
            elif (r["codigo_divisa_iic"] is None
                  or r["n_currencies"] != 1
                  or r["one_currency"] != r["codigo_divisa_iic"]):
                _emit(r["compartment_key"], "total_vs_trim_class_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["trim_sum"], "sum(fondtrim.patrimonio)",
                      "skipped_currency",
                      "class currencies do not uniformly equal IIC currency")
            else:
                _emit(r["compartment_key"], "total_vs_trim_class_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["trim_sum"], "sum(fondtrim.patrimonio)",
                      "comparable", None)

        # 3. PDV total_patrimonio vs sum of MENS month-end AUM (EUR)
        con.execute(
            "SELECT p.compartment_key, p.total_patrimonio,"
            " p.codigo_divisa_iic, sum(m.aum) AS mens_sum"
            " FROM patrimony p"
            " LEFT JOIN mens_eom m"
            " ON m.compartment_key = p.compartment_key"
            " WHERE p.period = ?"
            " GROUP BY p.compartment_key, p.total_patrimonio,"
            " p.codigo_divisa_iic"
            " ORDER BY p.compartment_key", [period])
        for r in _rows(con):
            if r["total_patrimonio"] is None or r["mens_sum"] is None:
                _emit(r["compartment_key"], "total_vs_mens_aum_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["mens_sum"], "sum(fondmens.aum@month_end)",
                      "skipped_missing", None)
            elif r["codigo_divisa_iic"] != "EUR":
                _emit(r["compartment_key"], "total_vs_mens_aum_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["mens_sum"], "sum(fondmens.aum@month_end)",
                      "skipped_currency",
                      f"IIC currency {r['codigo_divisa_iic']} != MENS EUR")
            else:
                _emit(r["compartment_key"], "total_vs_mens_aum_sum",
                      r["total_patrimonio"],
                      "fondpatrimdisvar.total_patrimonio",
                      r["mens_sum"], "sum(fondmens.aum@month_end)",
                      "comparable", None)

    summary: dict[str, int] = {}
    for r in rows:
        summary[r["state"]] = summary.get(r["state"], 0) + 1
    return {
        "period": period,
        "tolerance_rel": tolerance_rel,
        "comparisons": rows,
        "summary": summary,
        "note": "derived comparison only — equality not required; "
                "cutoff/currency bases differ legitimately",
    }


# -- G5-C: FONDDERI coverage reconciliation ---------------------------------


def derivative_reconciliation(
    root: Path | str, period: str,
) -> dict:
    """Coverage-level checks for FONDDERI — no value counterpart exists.

    ``fondderi.importe`` is committed nominal in EUR (a stock), while
    ``fondpatrimdisvar.resultados_derivados`` is a signed percentage
    flow over average daily patrimonio; FONDTRIM carries class-level
    metrics only; FONDCART's ``ClaseIF`` is geographic. All three
    relations are therefore declared ``not_comparable`` — an honest
    verdict, not a gap.
    """
    con = _con(root)
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise NotFoundError(f"bad period {period!r} — expected YYYY-MM")
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "derivative_coverage" not in tables:
        raise NotFoundError(
            f"no FONDDERI data for {period} — "
            "run `cnmv-iic update` for a cadence period")

    rows: list[dict] = []
    if "patrimony" in tables:
        con.execute(
            "SELECT c.compartment_key, c.n_operations,"
            " c.registry_state, p.compartment_key IS NOT NULL AS in_pdv"
            " FROM derivative_coverage c"
            " LEFT JOIN patrimony p"
            " ON p.compartment_key = c.compartment_key"
            " AND p.period = c.period"
            " WHERE c.period = ?"
            " ORDER BY c.compartment_key", [period])
        for r in _rows(con):
            rows.append({
                "subject_key": r["compartment_key"],
                "metric": "derivative_reporting_vs_patrimony",
                "left_value": r["n_operations"],
                "left_source": "fondderi.coverage.n_operations",
                "right_value": r["in_pdv"],
                "right_source": "fondpatrimdisvar.presence",
                "state": "match" if r["in_pdv"] else "missing_in_patrimony",
                "registry_state": r["registry_state"],
                "note": "coverage check only — no value comparison",
            })

    aggregates: list[dict] = []
    if "derivatives" in tables:
        con.execute(
            "SELECT compartment_key, count(*) AS n_operations,"
            " sum(importe) AS importe_sum_eur,"
            " count(DISTINCT objetivo) AS n_objetivos"
            " FROM derivatives WHERE period = ?"
            " GROUP BY compartment_key ORDER BY compartment_key",
            [period])
        for r in _rows(con):
            aggregates.append({
                "compartment_key": r["compartment_key"],
                "n_operations": r["n_operations"],
                "importe_sum_eur": r["importe_sum_eur"],
                "note": "informational aggregate — committed nominal "
                        "in EUR; no counterpart field exists",
            })

    return {
        "period": period,
        "coverage": rows,
        "aggregates": aggregates,
        "not_comparable": [
            {
                "left": "fondderi.importe",
                "right": "fondpatrimdisvar.resultados_derivados",
                "reason": "committed nominal (EUR stock) vs signed % "
                          "flow over average daily patrimonio — "
                          "different semantics, never equated",
            },
            {
                "left": "fondderi.importe",
                "right": "fondtrim.*",
                "reason": "FONDTRIM is share-class metrics — no "
                          "derivative stock field exists",
            },
            {
                "left": "fondderi.*",
                "right": "fondcart.*",
                "reason": "ClaseIF is geographic "
                          "(INTERIOR/EXTERIOR/DUDOSAS) — cannot "
                          "corroborate derivative positions",
            },
        ],
        "note": "coverage reconciliation only — not_comparable is a "
                "correct verdict, not a gap",
    }


# -- G5-D: FONDDERI accessor -------------------------------------------------


def derivative_operations(
    root: Path | str, identifier: str, period: str,
) -> tuple[dict, list[dict]]:
    """FONDDERI operation rows per compartment — verbatim evidence.

    Resolution mirrors ``holdings``: fund/compartment keys and
    share-class ISINs resolve to portfolio-owner compartments; one
    result per compartment with its operation rows and the explicit
    ``n_operations`` coverage state (0 = reported no derivatives).
    """
    con = _con(root)
    if "derivative_coverage" not in {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}:
        raise NotFoundError(
            "no FONDDERI data in dataset — run `cnmv-iic update` first")
    reg_period = _registry_period(con, period)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period),
        )
        owners = resolution.portfolio_owners
        if not owners:
            raise NotFoundError(
                f"{identifier!r} does not resolve to any compartment:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        info = _resolution_info(resolution)
    elif identifier.count(":") == 2:
        owners, info = (identifier,), {
            "requested_identifier": identifier,
            "resolved_as": ResolutionKind.EXACT_COMPARTMENT.value,
            "note": "resolved without registry data",
        }
    else:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: derivatives require a "
            "fund/compartment key or share-class ISIN")
    con.execute(
        "SELECT compartment_key, n_operations, registry_state"
        " FROM derivative_coverage"
        " WHERE period = ? AND compartment_key IN "
        f"({','.join('?' * len(owners))}) ORDER BY compartment_key",
        [period, *owners])
    cov = {r["compartment_key"]: r for r in _rows(con)}
    rows: list[dict] = []
    if "derivatives" in {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}:
        con.execute(
            "SELECT * FROM derivatives"
            " WHERE period = ? AND compartment_key IN "
            f"({','.join('?' * len(owners))})"
            " ORDER BY compartment_key, operation_index",
            [period, *owners])
        rows = _rows(con)
    out = []
    for ck in owners:
        c = cov.get(ck)
        ops = [r for r in rows if r["compartment_key"] == ck]
        if c is None and not ops:
            continue
        out.append({
            "compartment_key": ck,
            "n_operations": c["n_operations"] if c else len(ops),
            "reporting_state": (
                "reported_no_derivatives" if (c and c["n_operations"] == 0)
                else "reported"),
            "registry_state": c["registry_state"] if c else None,
            "operations": [{
                "operation_index": r["operation_index"],
                "descripcion": r["descripcion"],
                "side": r["side"],
                "underlier_class": r["underlier_class"],
                "subyacente": r["subyacente"],
                "instrumento": r["instrumento"],
                "importe_eur": r["importe"],
                "objetivo": r["objetivo"],
                "representation": r["representation"],
                "provenance": {
                    "source_artifact_id": r["source_artifact_id"],
                    "xml_locator": r["xml_locator"],
                },
            } for r in ops],
        })
    return info | {
        "period": period,
        "compartments": len(out),
        "semantics": {
            "importe_eur": "committed nominal in EUR (documented), "
                           "signed; NOT in codigo_divisa_iic",
            "subyacente/instrumento": "officially non-normalized text — "
                                      "verbatim, never parsed",
            "reporting_state": "reported_no_derivatives is an explicit "
                               "source state, not absent data",
        },
    }, out


# -- G4-D: FONDTRIM / FONDPATRIMDISVAR accessors -----------------------------

_FEE_COLUMNS = (
    "comision_gestion", "comision_depositario",
    "comision_suscripcion_minima", "comision_suscripcion_maxima",
    "comision_reembolso_minima", "comision_reembolso_maxima",
    "comision_descuento_favor_fondo_minima",
    "comision_descuento_favor_fondo_maxima",
)

_ROLLING_COLUMNS = (
    "official_return", "ratio_total_gastos", "volatilidad_vl",
)


def _quarterly_row(
    con: duckdb.DuckDBPyConnection, identifier: str, period: str,
) -> tuple[dict, dict]:
    key, info = _observation_share_class_key(
        con, identifier, period, table="quarterly", label="FONDTRIM")
    con.execute(
        "SELECT * FROM quarterly"
        " WHERE share_class_key = ? AND period = ?", [key, period])
    rows = _rows(con)
    if not rows:
        raise NotFoundError(f"no FONDTRIM row for {key} at {period}")
    return info, rows[0]


def quarterly_metrics(
    root: Path | str, identifier: str, period: str,
) -> dict:
    """Full FONDTRIM row for one share class — verbatim observed fields.

    Fields are grouped by unit basis: monetary values are in the class
    ``codigo_divisa`` (NOT assumed EUR); fees, official returns, ratios
    and volatility are percentages. Nothing is renamed or derived —
    ``RatioTotalGastos`` is kept verbatim, never called "TER".
    """
    con = _con(root)
    info, r = _quarterly_row(con, identifier, period)
    return {
        "resolution": info,
        "period": period,
        "identity": {c: r[c] for c in (
            "share_class_key", "compartment_key", "fund_key",
            "numero_clase", "isin_raw", "isin_state", "registry_state",
            "codigo_divisa", "codigo_divisa_iic", "vocacion_inversora",
            "clase_fondo", "periodicidad_calculo_vl",
            "base_calculo_comision_gestion",
            "sistema_imputacion_comisiones")},
        "stock_in_class_currency": {c: r[c] for c in (
            "patrimonio", "valor_liquidativo", "numero_participaciones",
            "numero_participes", "beneficio_dividendo_bruto")},
        "fees_pct": {c: r[c] for c in _FEE_COLUMNS},
        "official_return_pct": {c: r[c] for c in (
            "official_return_t", "official_return_t_1",
            "official_return_t_2", "official_return_t_3")},
        "ratio_total_gastos_pct": {c: r[c] for c in (
            "ratio_total_gastos_t", "ratio_total_gastos_t_1",
            "ratio_total_gastos_t_2", "ratio_total_gastos_t_3")},
        "volatilidad_vl_pct": {c: r[c] for c in (
            "volatilidad_vl_t", "volatilidad_vl_t_1",
            "volatilidad_vl_t_2", "volatilidad_vl_t_3")},
        "provenance": {c: r[c] for c in (
            "source_artifact_id", "source_sha256", "member_name",
            "member_sha256", "xml_locator", "parser", "parser_version")},
        "semantics": {
            "stock_fields": "in codigo_divisa (class denomination), "
                            "NOT assumed EUR",
            "fee_fields": "percentages, signed verbatim "
                          "(negative fees occur)",
            "official_return": "official CNMV non-annualized return, "
                               "verbatim; NULL = insufficient history",
        },
    }


def quarterly_fees(
    root: Path | str, identifier: str, period: str,
) -> dict:
    """FONDTRIM fee block for one share class — percentages, verbatim."""
    out = quarterly_metrics(root, identifier, period)
    return {
        "resolution": out["resolution"],
        "period": period,
        "identity": {k: out["identity"][k] for k in (
            "share_class_key", "isin_raw", "codigo_divisa",
            "registry_state")},
        "fees_pct": out["fees_pct"],
        "provenance": out["provenance"],
        "semantics": "percentages over the class fee basis, verbatim; "
                     "NULL = absent in source",
    }


def official_returns(
    root: Path | str, identifier: str,
    from_period: str | None, to_period: str | None,
) -> tuple[dict, list[dict]]:
    """Official CNMV return series for one share class across periods.

    ``official_return_t`` per period only — the T-1/T-2/T-3 lookbacks
    are shown verbatim by `metrics` for a single period. Never
    recalculated, never mixed with NAV-derived returns.
    """
    con = _con(root)
    key, info = _observation_share_class_key(
        con, identifier, to_period, table="quarterly", label="FONDTRIM")
    clauses, params = ["share_class_key = ?"], [key]
    if from_period:
        clauses.append("period >= ?")
        params.append(from_period)
    if to_period:
        clauses.append("period <= ?")
        params.append(to_period)
    con.execute(
        f"SELECT period, official_return_t AS official_return_pct,"
        f" registry_state, codigo_divisa, source_artifact_id,"
        f" xml_locator FROM quarterly WHERE {' AND '.join(clauses)}"
        f" ORDER BY period",
        params,
    )
    rows = _rows(con)
    return info | {
        "from_period": from_period, "to_period": to_period,
        "periods": len(rows),
        "semantics": "official CNMV non-annualized quarterly return "
                     "(percent), verbatim; NULL = insufficient history; "
                     "never recomputed from NAV",
    }, rows


_PDV_MONETARY = (
    "dp_inversiones_financieras", "cartera_interior", "cartera_exterior",
    "intereses_cartera", "inversiones_dudosas", "liquidez", "resto",
    "total_patrimonio", "patrimonio_fin_periodo_anterior",
    "patrimonio_fin_periodo_actual",
)

_PDV_PCT = (
    "suscripciones_reembolsos_netos", "beneficios_brutos_distribuidos",
    "rendimientos_netos", "rendimientos_gestion", "intereses",
    "dividendos", "resultados_renta_fija", "resultados_renta_variable",
    "resultados_depositos", "resultados_derivados", "resultados_iic",
    "otros_resultados", "otros_rendimientos", "gastos_repercutidos",
    "comision_gestion", "comision_depositario",
    "gastos_servicios_exteriores", "otros_gastos_gestion",
    "otros_gastos_repercutidos", "ingresos", "comisiones_descuento",
    "comisiones_retrocedidas", "otros_ingresos",
)


def patrimony_allocation(
    root: Path | str, identifier: str, period: str,
) -> tuple[dict, list[dict]]:
    """FONDPATRIMDISVAR stock + flow rows per compartment.

    The two field families are kept rigidly apart: ``monetary_*`` is in
    the IIC ``codigo_divisa_iic``; ``pct_*`` are signed percentages over
    average daily patrimonio (documented CNMV semantics, not monetary).
    """
    con = _con(root)
    if "patrimony" not in {r[0] for r in con.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}:
        raise NotFoundError(
            "no FONDPATRIMDISVAR data in dataset — "
            "run `cnmv-iic update` first")
    reg_period = _registry_period(con, period)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period),
        )
        owners = resolution.portfolio_owners
        if not owners:
            raise NotFoundError(
                f"{identifier!r} does not resolve to any compartment:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        info = _resolution_info(resolution)
    elif identifier.count(":") == 2:
        owners, info = (identifier,), {
            "requested_identifier": identifier,
            "resolved_as": ResolutionKind.EXACT_COMPARTMENT.value,
            "note": "resolved without registry data",
        }
    else:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: patrimony requires a "
            "fund/compartment key or share-class ISIN")
    con.execute(
        "SELECT * FROM patrimony"
        " WHERE period = ? AND compartment_key IN "
        f"({','.join('?' * len(owners))}) ORDER BY compartment_key",
        [period, *owners])
    rows = _rows(con)
    out = []
    for r in rows:
        out.append({
            "compartment_key": r["compartment_key"],
            "codigo_divisa_iic": r["codigo_divisa_iic"],
            "registry_state": r["registry_state"],
            "indice_rotacion_cartera": {
                "actual": r["indice_rotacion_cartera_actual"],
                "anterior": r["indice_rotacion_cartera_anterior"],
            },
            "monetary_in_iic_currency": {c: r[c] for c in _PDV_MONETARY},
            "pct_of_avg_daily_patrimonio": {c: r[c] for c in _PDV_PCT},
            "provenance": {c: r[c] for c in (
                "source_artifact_id", "source_sha256", "member_name",
                "member_sha256", "xml_locator")},
        })
    return info | {
        "period": period,
        "compartments": len(out),
        "semantics": {
            "monetary_in_iic_currency":
                "stock fields in codigo_divisa_iic (IIC denomination)",
            "pct_of_avg_daily_patrimonio":
                "signed % over average daily patrimonio — "
                "NOT monetary; flow/result decomposition",
        },
    }, out


# -- G6: historical portfolio change semantics -------------------------------
#
# docs/g6/contract.md — measured identity contract:
# - ISIN is NOT a row key: 0.6-1.8% of valid rows share an ISIN inside
#   the same portfolio (repos, lots, same ISIN two roles) — those
#   groups are ambiguous and never silently paired or summed.
# - Descriptors churn 18-30% between snapshots — never a match input,
#   only a change output (source_metadata_changed).
# - Non-valid ISINs (absent/masked/invalid) match only on unique
#   byte-identical verbatim signatures — identifier_authority=none.
# - No transaction verbs: snapshot differences prove state change only.


def _valid_period(period: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        raise NotFoundError(f"bad period {period!r} — expected YYYY-MM")
    return period


def _month_end(period: str) -> date:
    y, m = int(period[:4]), int(period[5:7])
    return date(y, m, monthrange(y, m)[1])


_POS_COLS = (
    "position_seq, kind, clase_if, descripcion_if, descripcion_valor,"
    " divisa, reported_market_value, derived_weight, isin_raw,"
    " isin_state, source_artifact_id, xml_locator"
)


def _owner_positions(
    con: duckdb.DuckDBPyConnection, owner_key: str,
    period: str,
) -> list[dict]:
    # positions.fund_key IS the compartment key (FundIdentity includes
    # numero_compartimento — see domain.FundIdentity.key)
    con.execute(
        f"SELECT {_POS_COLS} FROM positions"           # noqa: S608
        " WHERE period = ? AND fund_key = ?"
        " ORDER BY position_seq",
        [period, owner_key])
    return _rows(con)


def _pos_sig(r: dict) -> tuple:
    return (r["kind"], r["clase_if"], r["descripcion_if"],
            r["descripcion_valor"], r["divisa"])


def _pos_out(r: dict) -> dict:
    return {
        "position_seq": r["position_seq"],
        "kind": r["kind"],
        "clase_if": r["clase_if"],
        "descripcion_if": r["descripcion_if"],
        "descripcion_valor": r["descripcion_valor"],
        "divisa": r["divisa"],
        "reported_market_value": r["reported_market_value"],
        "derived_weight": r["derived_weight"],
        "isin_raw": r["isin_raw"],
        "isin_state": r["isin_state"],
        "provenance": {
            "source_artifact_id": r["source_artifact_id"],
            "xml_locator": r["xml_locator"],
        },
    }


_META_FACETS = ("kind", "clase_if", "descripcion_if",
                "descripcion_valor", "divisa", "isin_raw")


def _match_positions(
    old: list[dict], new: list[dict],
) -> dict:
    """Two phases kept rigidly apart: identity matching first, change
    classification second. Returns matched pairs, added/removed rows
    and unresolved groups — never fabricates pairings."""
    old_valid = [r for r in old if r["isin_state"] == "valid"]
    new_valid = [r for r in new if r["isin_state"] == "valid"]
    oc, nc = (Counter(r["isin_raw"] for r in x)
              for x in (old_valid, new_valid))

    pairs: list[tuple[dict, dict, str]] = []
    added: list[tuple[dict, str]] = []
    removed: list[tuple[dict, str]] = []
    unresolved: list[dict] = []

    for isin in sorted(set(oc) | set(nc)):
        o = [r for r in old_valid if r["isin_raw"] == isin]
        n = [r for r in new_valid if r["isin_raw"] == isin]
        if o and n:
            if len(o) == 1 and len(n) == 1:
                pairs.append((o[0], n[0], "exact_valid_isin"))
            else:
                # ambiguous identifier group — reported, never paired
                unresolved.append({
                    "match_state": "unresolved",
                    "match_basis": "ambiguous_identifier",
                    "identifier": isin,
                    "rows_before": len(o),
                    "rows_after": len(n),
                    "before_rows": [_pos_out(r) for r in o],
                    "after_rows": [_pos_out(r) for r in n],
                    "note": "ISIN duplicated within snapshot — no "
                            "authoritative row pairing; never summed "
                            "(a repo leg + the bond itself share ISINs "
                            "in the source)",
                })
        elif n:
            added += [(r, "authoritative_identifier") for r in n]
        else:
            removed += [(r, "authoritative_identifier") for r in o]

    # non-valid rows: only a unique byte-identical verbatim signature
    # may match — identifier_authority=none either way.
    old_nv = [r for r in old if r["isin_state"] != "valid"]
    new_nv = [r for r in new if r["isin_state"] != "valid"]
    so = Counter(_pos_sig(r) for r in old_nv)
    sn = Counter(_pos_sig(r) for r in new_nv)
    used_o: set[int] = set()
    used_n: set[int] = set()
    for sig in sorted(set(so) & set(sn), key=repr):
        if so[sig] == 1 and sn[sig] == 1:
            ro = next(r for r in old_nv if _pos_sig(r) == sig)
            rn = next(r for r in new_nv if _pos_sig(r) == sig)
            pairs.append((ro, rn, "verbatim_signature"))
            used_o.add(id(ro))
            used_n.add(id(rn))
    for r in old_nv:
        if id(r) not in used_o:
            removed.append((r, "none"))
    for r in new_nv:
        if id(r) not in used_n:
            added.append((r, "none"))

    return {"pairs": pairs, "added": added,
            "removed": removed, "unresolved": unresolved}


def _classify_change(a: dict, b: dict) -> tuple[str, list[str]]:
    vm = a["reported_market_value"] != b["reported_market_value"]
    w = a["derived_weight"] != b["derived_weight"]
    meta = [f for f in _META_FACETS if a[f] != b[f]]
    if vm and w:
        state = "market_value_and_weight_changed"
    elif vm:
        state = "market_value_changed"
    elif w:
        state = "weight_changed"
    elif meta:
        state = "source_metadata_changed"
    else:
        state = "unchanged_position"
    return state, meta


def _diff_payload(
    old: list[dict], new: list[dict],
) -> dict:
    m = _match_positions(old, new)
    changes = []
    for a, b, basis in m["pairs"]:
        state, meta = _classify_change(a, b)
        changes.append({
            "match_state": ("exact_identifier" if basis
                            == "exact_valid_isin"
                            else "exact_source_signature"),
            "match_basis": basis,
            "identifier_authority": (
                "authoritative_identifier" if basis
                == "exact_valid_isin" else "none"),
            "identifier": a["isin_raw"] if basis == "exact_valid_isin"
                          else None,
            "change": state,
            "metadata_changed": meta,
            "market_value": {
                "before": a["reported_market_value"],
                "after": b["reported_market_value"],
                "delta": (b["reported_market_value"]
                          - a["reported_market_value"]),
                "state": "observed_delta",
            },
            "weight": {
                "before": a["derived_weight"],
                "after": b["derived_weight"],
                "delta": (b["derived_weight"] - a["derived_weight"]),
                "state": "derived_from_derived",
            },
            "before": _pos_out(a),
            "after": _pos_out(b),
        })
    for r, auth in m["added"]:
        changes.append({
            "match_state": None, "match_basis": None,
            "identifier_authority": auth,
            "identifier": r["isin_raw"] if auth != "none" else None,
            "change": "added_position", "metadata_changed": [],
            "market_value": {"before": None,
                             "after": r["reported_market_value"],
                             "delta": None, "state": "observed_delta"},
            "weight": {"before": None, "after": r["derived_weight"],
                       "delta": None, "state": "derived_from_derived"},
            "before": None, "after": _pos_out(r),
        })
    for r, auth in m["removed"]:
        changes.append({
            "match_state": None, "match_basis": None,
            "identifier_authority": auth,
            "identifier": r["isin_raw"] if auth != "none" else None,
            "change": "removed_position", "metadata_changed": [],
            "market_value": {"before": r["reported_market_value"],
                             "after": None,
                             "delta": None, "state": "observed_delta"},
            "weight": {"before": r["derived_weight"], "after": None,
                       "delta": None, "state": "derived_from_derived"},
            "before": _pos_out(r), "after": None,
        })
    return {"changes": changes, "unresolved": m["unresolved"]}


def _diff_summary(payload: dict, n_old: int, n_new: int) -> dict:
    changes = payload["changes"]
    by_change = Counter(c["change"] for c in changes)
    matched = sum(1 for c in changes
                  if c["match_state"] is not None)
    added = by_change.get("added_position", 0)
    removed = by_change.get("removed_position", 0)
    un_old = sum(u["rows_before"] for u in payload["unresolved"])
    un_new = sum(u["rows_after"] for u in payload["unresolved"])
    return {
        "counts": {k: by_change.get(k, 0) for k in (
            "unchanged_position", "market_value_changed",
            "weight_changed", "market_value_and_weight_changed",
            "source_metadata_changed", "added_position",
            "removed_position")} | {"unresolved_groups":
                                    len(payload["unresolved"])},
        # conservation: every row accounted for, never forced
        "conservation": {
            "old": {"matched": matched, "removed": removed,
                    "unresolved_rows": un_old,
                    "total": n_old,
                    "holds": matched + removed + un_old == n_old},
            "new": {"matched": matched, "added": added,
                    "unresolved_rows": un_new,
                    "total": n_new,
                    "holds": matched + added + un_new == n_new},
        },
    }


def _diff_fingerprint(owner_payloads: dict) -> str:
    canon = json.dumps(
        owner_payloads, sort_keys=True, default=str,
        ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


def _expected_previous_published(to_period: str) -> str | None:
    """Expected previous FONDCART publication month under the
    MEASURED post-2023 June+December cadence (docs/g0, verified:
    2023-06, 2025-06, 2025-12 present; 2024-03, 2025-03 absent).

    Returns None outside the measured window — pre-2023 cadence is
    not asserted here, so no missing snapshot is claimed.
    """
    y, m = int(to_period[:4]), int(to_period[5:7])
    if m == 12:
        expected = f"{y}-06"
    elif m == 6:
        expected = f"{y - 1}-12"
    else:
        return None
    return expected if expected >= "2023-06" else None


def _fondcart_periods(
    con: duckdb.DuckDBPyConnection, owner: str | None = None,
) -> list[str]:
    if owner is None:
        con.execute(
            "SELECT DISTINCT period FROM positions ORDER BY 1")
    else:
        con.execute(
            "SELECT DISTINCT period FROM positions"
            " WHERE fund_key = ? ORDER BY 1", [owner])
    return [r[0] for r in con.fetchall()]


def portfolio_diff(
    root: Path | str, identifier: str,
    from_period: str | None = None,
    to_period: str | None = None,
    *,
    previous: bool = False,
) -> tuple[dict, list[dict]]:
    """Compare two published FONDCART snapshots of each resolved
    portfolio owner — a change ledger, never inferred transactions.

    Periods are published snapshots, not assumed quarters:
    ``previous=True`` selects the owner's latest available snapshot
    strictly before ``to_period`` (``adjacent_available_snapshots``);
    explicit ``from_period``+``to_period`` = ``explicit_periods``.

    ``--previous`` never silently skips a measured published
    snapshot: under the verified post-2023 June+December cadence it
    fails with ``previous_published_snapshot_not_loaded=<period>``
    when that snapshot is absent from the dataset.

    Returns ``(meta, per_owner_rows)``.
    """
    if to_period is None:
        raise NotFoundError(
            "portfolio-diff requires to_period (or --as-of)")
    _valid_period(to_period)
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "positions" not in tables:
        raise NotFoundError(
            "no FONDCART data in dataset — run `cnmv-iic update` first")
    cart_periods = set(_fondcart_periods(con))
    if to_period not in cart_periods:
        raise NotFoundError(
            f"no FONDCART data for {to_period} — "
            "period is not a published snapshot")

    reg_period = _registry_period(con, to_period)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period))
        owners = resolution.portfolio_owners
        if not owners:
            raise NotFoundError(
                f"{identifier!r} does not resolve to any compartment:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        info = _resolution_info(resolution)
    elif identifier.count(":") == 2:
        owners = (identifier,)
        info = {"requested_identifier": identifier,
                "resolved_as": ResolutionKind.EXACT_COMPARTMENT.value,
                "note": "resolved without registry data"}
    else:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: portfolio-diff requires "
            "a fund/compartment key or share-class ISIN")

    out = []
    for ck in owners:
        available = _fondcart_periods(con, ck)
        if previous:
            # never silently skip a measured published snapshot:
            # if the expected previous publication isn't loaded, fail
            # naming it — don't jump years backward in silence.
            expected = _expected_previous_published(to_period)
            if expected is not None and expected not in cart_periods:
                raise NotFoundError(
                    f"previous_published_snapshot_not_loaded="
                    f"{expected} — run `cnmv-iic update --period "
                    f"{expected}` first")
            earlier = [p for p in available if p < to_period]
            if earlier:
                fp = earlier[-1]
                cadence = "adjacent_available_snapshots"
                owner_absent_from = False
            else:
                cart_earlier = sorted(p for p in cart_periods
                                      if p < to_period)
                if not cart_earlier:
                    raise NotFoundError(
                        f"no earlier FONDCART snapshot before "
                        f"{to_period} for {ck}")
                fp = cart_earlier[-1]
                cadence = "adjacent_available_snapshots"
                owner_absent_from = True
        else:
            if from_period is None:
                raise NotFoundError(
                    "explicit from_period required unless --previous")
            fp = _valid_period(from_period)
            cadence = "explicit_periods"
            owner_absent_from = fp not in available
            if fp not in cart_periods:
                raise NotFoundError(
                    f"no FONDCART data for {fp} — "
                    "period is not a published snapshot")

        old = _owner_positions(con, ck, fp)
        new = _owner_positions(con, ck, to_period)
        owner_absent_to = to_period not in available
        if not old and not new and owner_absent_from and owner_absent_to:
            continue

        payload = _diff_payload(old, new)
        artifact_from = old[0]["source_artifact_id"] if old else None
        artifact_to = new[0]["source_artifact_id"] if new else None

        # official PDV context for the later period — parallel
        # disclosure, never a causal attribution
        patrimony_ctx = None
        if "patrimony" in tables:
            con.execute(
                "SELECT suscripciones_reembolsos_netos,"
                " rendimientos_netos, comision_gestion,"
                " total_patrimonio, codigo_divisa_iic"
                " FROM patrimony WHERE period = ?"
                " AND compartment_key = ?", [to_period, ck])
            rows = _rows(con)
            if rows:
                r = rows[0]
                patrimony_ctx = {
                    "period": to_period,
                    "suscripciones_reembolsos_netos_pct":
                        r["suscripciones_reembolsos_netos"],
                    "rendimientos_netos_pct": r["rendimientos_netos"],
                    "comision_gestion_pct": r["comision_gestion"],
                    "total_patrimonio": r["total_patrimonio"],
                    "codigo_divisa_iic": r["codigo_divisa_iic"],
                    "note": "official aggregate context — no causal "
                            "attribution between flows and individual "
                            "position changes",
                }

        out.append({
            "portfolio_owner": ck,
            "from_period": fp,
            "to_period": to_period,
            "publication_cadence": cadence,
            "elapsed_days": (_month_end(to_period)
                             - _month_end(fp)).days,
            "from_artifact": artifact_from,
            "to_artifact": artifact_to,
            "snapshot_presence": {
                "from": ("owner_absent" if owner_absent_from
                         else "reported"),
                "to": ("owner_absent" if owner_absent_to
                       else "reported"),
            },
            "positions": {"old": len(old), "new": len(new)},
            "summary": _diff_summary(payload, len(old), len(new)),
            "changes": payload["changes"],
            "unresolved": payload["unresolved"],
            "derivatives": {
                "individual_position_diff": "unavailable",
                "reason": "no_authoritative_cross_snapshot_identity — "
                          "FONDDERI instruments are officially "
                          "non-normalized text (G5)",
            },
            "official_patrimony_variation": patrimony_ctx,
        })

    if not out:
        raise NotFoundError(
            f"{identifier!r}: no FONDCART snapshots found for any "
            "resolved compartment")
    return info | {
        "from_period": out[0]["from_period"],
        "to_period": to_period,
        "publication_cadence": out[0]["publication_cadence"],
        "diff_fingerprint": _diff_fingerprint(
            {o["portfolio_owner"]: o["changes"] for o in out}),
        "compartments": len(out),
        "semantics": {
            "added": "absent from the earlier disclosed snapshot and "
                     "present in the later one — does NOT imply a "
                     "purchase",
            "removed": "present earlier, absent later — does NOT "
                       "imply a sale",
            "changed": "reported field values differ — price, FX, "
                       "flows, corporate actions, reclassification "
                       "and reporting changes are all possible causes",
            "weight": "derived_weight is DERIVED (reported VM / "
                      "portfolio total); weight deltas are "
                      "derived_from_derived",
            "unresolved": "ambiguous identifier groups reported "
                          "unpaired — never summed or heuristic-matched",
        },
    }, out


def position_history(
    root: Path | str, identifier: str, isin: str,
) -> tuple[dict, list[dict]]:
    """Reported market-value history of one identifier inside a
    portfolio owner — REPORTED VALUES, not transactions.

    A duplicated ISIN inside a snapshot yields all its rows (the
    identifier is ambiguous — never collapsed).
    """
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "positions" not in tables:
        raise NotFoundError(
            "no FONDCART data in dataset — run `cnmv-iic update` first")
    reg_period = _registry_period(con, None)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period))
        owners = resolution.portfolio_owners
        if not owners:
            raise NotFoundError(
                f"{identifier!r} does not resolve to any compartment:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        info = _resolution_info(resolution)
    elif identifier.count(":") == 2:
        owners = (identifier,)
        info = {"requested_identifier": identifier,
                "resolved_as": ResolutionKind.EXACT_COMPARTMENT.value,
                "note": "resolved without registry data"}
    else:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: position-history "
            "requires a fund/compartment key or share-class ISIN")

    out = []
    for ck in owners:
        con.execute(
            f"SELECT period, {_POS_COLS} FROM positions"   # noqa: S608
            " WHERE fund_key = ? AND isin_raw = ?"
            " ORDER BY period, position_seq", [ck, isin])
        obs = _rows(con)
        if obs:
            out.append({
                "portfolio_owner": ck,
                "identifier": isin,
                "observations": [{
                    "period": r["period"],
                    "position_seq": r["position_seq"],
                    "reported_market_value": r["reported_market_value"],
                    "derived_weight": r["derived_weight"],
                    "weight_state": "derived",
                    "descripcion_valor": r["descripcion_valor"],
                    "descripcion_if": r["descripcion_if"],
                    "divisa": r["divisa"],
                    "isin_state": r["isin_state"],
                    "provenance": {
                        "source_artifact_id": r["source_artifact_id"],
                        "xml_locator": r["xml_locator"],
                    },
                    "note": ("duplicated identifier in snapshot — "
                             "rows not collapsed"
                             if sum(1 for x in obs
                                    if x["period"] == r["period"]) > 1
                             else None),
                } for r in obs],
            })
    if not out:
        raise NotFoundError(
            f"{identifier!r}: no reported positions for {isin!r}")
    return info | {
        "identifier": isin,
        "compartments": len(out),
        "semantics": {
            "reported_market_value": "observed reported value history "
                                     "— NOT a buy/sell history",
            "derived_weight": "DERIVED (reported VM / portfolio total)",
        },
    }, out


def portfolio_history(
    root: Path | str, identifier: str,
) -> tuple[dict, list[dict]]:
    """Per-snapshot reported position counts and totals for each
    resolved owner — observed aggregates, no semantics attached."""
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "positions" not in tables:
        raise NotFoundError(
            "no FONDCART data in dataset — run `cnmv-iic update` first")
    reg_period = _registry_period(con, None)
    if reg_period is not None:
        resolution = resolve(
            identifier,
            share_classes=_share_class_rows(con, reg_period),
            funds=_fund_owners(con, reg_period))
        owners = resolution.portfolio_owners
        if not owners:
            raise NotFoundError(
                f"{identifier!r} does not resolve to any compartment:"
                f" {resolution.kind.value}"
                + (f" — {resolution.note}" if resolution.note else ""))
        info = _resolution_info(resolution)
    elif identifier.count(":") == 2:
        owners = (identifier,)
        info = {"requested_identifier": identifier,
                "resolved_as": ResolutionKind.EXACT_COMPARTMENT.value,
                "note": "resolved without registry data"}
    else:
        raise NotFoundError(
            f"cannot resolve {identifier!r}: portfolio-history "
            "requires a fund/compartment key or share-class ISIN")

    out = []
    for ck in owners:
        con.execute(
            "SELECT period, count(*) AS n_positions,"
            " sum(reported_market_value) AS total_reported_value,"
            " sum(CASE WHEN kind = 'cash' THEN 1 ELSE 0 END) AS cash,"
            " sum(CASE WHEN kind = 'security' THEN 1 ELSE 0 END)"
            " AS securities,"
            " min(source_artifact_id) AS source_artifact_id"
            " FROM positions WHERE fund_key = ?"
            " GROUP BY period ORDER BY period", [ck])
        rows = _rows(con)
        if rows:
            out.append({"portfolio_owner": ck, "snapshots": rows})
    if not out:
        raise NotFoundError(
            f"{identifier!r}: no FONDCART snapshots for any "
            "resolved compartment")
    return info | {"compartments": len(out)}, out


def security_evidence(
    root: Path | str, isin: str,
) -> dict:
    """All provider observations + candidates for one ISIN (G7 evidence).

    Returns observations across every loaded provider snapshot — evidence,
    not adjudication. ``isin`` is upper-cased; masked/invalid input fails
    closed.
    """
    isin = isin.strip().upper()
    state = classify_isin(isin)
    if state is not IsinState.VALID:
        raise NotFoundError(
            f"identifier {isin!r} is {state.value}, not a valid ISIN — "
            f"no provider resolution attempted")
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "resolution_observations" not in tables:
        return {"isin": isin, "observations": [],
                "note": "no provider evidence loaded — run "
                        "`cnmv-iic ingest-provider` first"}
    obs = _rows(con.execute(
        "SELECT * FROM resolution_observations WHERE isin = ? "
        "ORDER BY provider_snapshot_date DESC, provider", [isin]))
    cands = []
    if obs and "resolution_candidates" in tables:
        ids = [o["observation_id"] for o in obs]
        ph = ",".join("?" * len(ids))
        cands = _rows(con.execute(
            f"SELECT * FROM resolution_candidates "
            f"WHERE observation_id IN ({ph}) "
            f"ORDER BY observation_id, candidate_index", ids))
    by_obs: dict[str, list] = {}
    for c in cands:
        by_obs.setdefault(c["observation_id"], []).append(c)
    for o in obs:
        o["candidates"] = by_obs.get(o["observation_id"], [])
    # G7-C: provider records backing candidates (FIRDS venue multiplicity)
    if obs and "resolution_candidate_evidence" in tables:
        ids = [o["observation_id"] for o in obs]
        ph = ",".join("?" * len(ids))
        evs = _rows(con.execute(
            f"SELECT * FROM resolution_candidate_evidence "
            f"WHERE observation_id IN ({ph}) "
            f"ORDER BY observation_id, evidence_index", ids))
        ev_by_obs: dict[str, list] = {}
        for e in evs:
            ev_by_obs.setdefault(e["observation_id"], []).append(e)
        for o in obs:
            o["candidate_evidence"] = ev_by_obs.get(o["observation_id"], [])
    return {"isin": isin, "observations": obs}


_LEI_RE = re.compile(r"^[0-9A-Z]{18}[0-9]{2}$")


def lei_evidence(root: Path | str, lei: str) -> dict:
    """G7-B evidence for one LEI: Level-1 entity, relationships,
    reporting exceptions — verbatim, no adjudication.

    ``relationships_as_start`` are the entity's own reported relations
    (upward); ``relationships_as_end`` are stored relations pointing at
    it. Absence of rows is not asserted as absence of the relationship —
    check ``exceptions`` for declared reporting exceptions first.
    """
    lei = lei.strip().upper()
    if not _LEI_RE.match(lei):
        raise NotFoundError(
            f"{lei!r} is not a well-formed LEI (20 chars, "
            f"ISO-17442) — no evidence lookup attempted")
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    out: dict = {"lei": lei}
    if "legal_entities" not in tables:
        out["note"] = ("no GLEIF golden evidence loaded — run "
                       "`cnmv-iic ingest-provider gleif-golden` first")
        return out
    out["entities"] = _rows(con.execute(
        "SELECT * FROM legal_entities WHERE lei = ? "
        "ORDER BY provider_snapshot_date DESC, evidence_role", [lei]))
    out["relationships_as_start"] = _rows(con.execute(
        "SELECT * FROM relationships WHERE start_lei = ? "
        "ORDER BY provider_snapshot_date DESC, relationship_type", [lei]))
    out["relationships_as_end"] = _rows(con.execute(
        "SELECT * FROM relationships WHERE end_lei = ? "
        "ORDER BY provider_snapshot_date DESC, relationship_type", [lei]))
    out["exceptions"] = _rows(con.execute(
        "SELECT * FROM relationship_exceptions WHERE lei = ? "
        "ORDER BY provider_snapshot_date DESC, exception_category",
        [lei]))
    return out


def instrument_evidence(
    root: Path | str, isin: str,
) -> dict:
    """G7-D OpenFIGI instrument evidence for one ISIN — instrument
    symbology, not issuer resolution. Observations carry every provider
    result row verbatim (figi/composite/share-class kept distinct).
    """
    isin = isin.strip().upper()
    state = classify_isin(isin)
    if state is not IsinState.VALID:
        raise NotFoundError(
            f"identifier {isin!r} is {state.value}, not a valid ISIN — "
            f"no instrument evidence lookup attempted")
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "instrument_observations" not in tables:
        return {"isin": isin, "observations": [],
                "note": "no instrument evidence loaded — run "
                        "`cnmv-iic ingest-openfigi` first"}
    obs = _rows(con.execute(
        "SELECT * FROM instrument_observations WHERE isin = ? "
        "ORDER BY campaign DESC", [isin]))
    if obs and "instrument_candidates" in tables:
        ids = [o["observation_id"] for o in obs]
        ph = ",".join("?" * len(ids))
        cands = _rows(con.execute(
            f"SELECT * FROM instrument_candidates "
            f"WHERE observation_id IN ({ph}) "
            f"ORDER BY observation_id, result_index", ids))
        by_obs: dict[str, list] = {}
        for c in cands:
            by_obs.setdefault(c["observation_id"], []).append(c)
        for o in obs:
            o["results"] = by_obs.get(o["observation_id"], [])
    return {"isin": isin, "observations": obs}


def _latest_adjudication_key(
        con: duckdb.DuckDBPyConnection,
        version: str | None, bundle: str | None,
) -> tuple[str, str] | None:
    """(version, bundle) of the most recent adjudication, or None."""
    where = ""
    params: list[str] = []
    if version is not None:
        where += " AND version = ?"
        params.append(version)
    if bundle is not None:
        where += " AND bundle = ?"
        params.append(bundle)
    rows = con.execute(
        "SELECT DISTINCT version, bundle, adjudicated_at "
        "FROM security_resolution WHERE 1=1" + where
        + " ORDER BY adjudicated_at DESC LIMIT 1", params).fetchall()
    return (rows[0][0], rows[0][1]) if rows else None


def security_resolution(
    root: Path | str, isin: str, *,
    version: str | None = None, bundle: str | None = None,
) -> dict:
    """Derived adjudication for one ISIN (G7-E) — issuer verdict +
    instrument-family verdict over the pinned evidence bundle.

    This is a DERIVED view: ``resolved_lei`` exists only for
    corroborated / single-provider states; ``conflict`` always carries
    ``resolved_lei = NULL`` plus a ``conflict_context`` explaining what
    is known about the two asserted entities."""
    isin = isin.strip().upper()
    state = classify_isin(isin)
    if state is not IsinState.VALID:
        raise NotFoundError(
            f"identifier {isin!r} is {state.value}, not a valid ISIN")
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "security_resolution" not in tables:
        return {"isin": isin,
                "note": "no adjudication derived — run "
                        "`cnmv-iic adjudicate` first"}
    key = _latest_adjudication_key(con, version, bundle)
    if key is None:
        return {"isin": isin, "note": "no adjudication partitions found"}
    v, b = key
    sec = _rows(con.execute(
        "SELECT * FROM security_resolution WHERE isin = ? "
        "AND version = ? AND bundle = ?", [isin, v, b]))
    fam = _rows(con.execute(
        "SELECT * FROM instrument_family_resolution WHERE isin = ? "
        "AND version = ? AND bundle = ?", [isin, v, b]))
    for s in sec:
        if s.get("conflict_context_json"):
            s["conflict_context"] = json.loads(s["conflict_context_json"])
        # derived, documented strength tier — G8 must not infer it
        # from state names alone
        s["evidence_strength"] = _EVIDENCE_STRENGTH.get(
            s["state"], "unresolved")
    return {"isin": isin, "version": v, "bundle": b,
            "security": sec[0] if sec else None,
            "instrument_family": fam[0] if fam else None}


_EVIDENCE_STRENGTH = {
    "corroborated": "corroborated",
    "gleif_only": "single_source",
    "firds_only": "single_source",
    "conflict": "unresolved",
    "multiple_candidates": "unresolved",
    "no_authoritative_match": "unresolved",
}


def resolution_coverage(
    root: Path | str, *,
    version: str | None = None, bundle: str | None = None,
) -> dict:
    """State distribution of the latest adjudication — full corpus."""
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "security_resolution" not in tables:
        return {"note": "no adjudication derived — run "
                        "`cnmv-iic adjudicate` first"}
    key = _latest_adjudication_key(con, version, bundle)
    if key is None:
        return {"note": "no adjudication partitions found"}
    v, b = key
    sec = _rows(con.execute(
        "SELECT state, COUNT(*) AS n FROM security_resolution "
        "WHERE version = ? AND bundle = ? GROUP BY state "
        "ORDER BY n DESC", [v, b]))
    fam = _rows(con.execute(
        "SELECT state, COUNT(*) AS n FROM instrument_family_resolution "
        "WHERE version = ? AND bundle = ? GROUP BY state "
        "ORDER BY n DESC", [v, b]))
    by_period = []
    if "positions" in tables:
        by_period = _rows(con.execute(
            "SELECT p.period, s.state, COUNT(DISTINCT s.isin) AS n "
            "FROM security_resolution s JOIN positions p "
            "ON s.isin = p.isin_raw AND p.isin_state = 'valid' "
            "WHERE s.version = ? AND s.bundle = ? "
            "GROUP BY p.period, s.state ORDER BY p.period, n DESC",
            [v, b]))
    return {
        "version": v, "bundle": b,
        "security_states": sec, "family_states": fam,
        "by_period": by_period,
        "temporal_semantics":
            "current_enrichment_of_historical_security — provider "
            "evidence retrieved now says nothing about what was "
            "knowable at each holding period",
    }


def resolution_conflicts(
    root: Path | str, *,
    version: str | None = None, bundle: str | None = None,
) -> dict:
    """All CONFLICT rows of the latest adjudication with parsed context —
    the disagreement surface between the two authoritative sources."""
    con = _con(root)
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    if "security_resolution" not in tables:
        return {"note": "no adjudication derived — run "
                        "`cnmv-iic adjudicate` first"}
    key = _latest_adjudication_key(con, version, bundle)
    if key is None:
        return {"note": "no adjudication partitions found"}
    v, b = key
    rows = _rows(con.execute(
        "SELECT isin, gleif_candidate_lei, firds_candidate_lei, "
        "conflict_context_json FROM security_resolution "
        "WHERE state = 'conflict' AND version = ? AND bundle = ? "
        "ORDER BY isin", [v, b]))
    kinds: dict[str, int] = {}
    for r in rows:
        r["conflict_context"] = json.loads(r["conflict_context_json"])
        k = r["conflict_context"]["kind"]
        kinds[k] = kinds.get(k, 0) + 1
    return {"version": v, "bundle": b, "conflicts": len(rows),
            "context_kinds": dict(sorted(kinds.items())), "rows": rows}


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
    if "quarterly" in tables:
        out["quarterly_periods"] = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM quarterly ORDER BY 1").fetchall()]
        out["quarterly_per_period"] = _rows(con.execute(
            "SELECT period, count(*) AS metrics,"
            " count(DISTINCT share_class_key) AS share_classes"
            " FROM quarterly GROUP BY period ORDER BY period"))
    if "patrimony" in tables:
        out["patrimony_periods"] = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM patrimony ORDER BY 1").fetchall()]
        out["patrimony_per_period"] = _rows(con.execute(
            "SELECT period, count(*) AS records,"
            " count(DISTINCT compartment_key) AS compartments"
            " FROM patrimony GROUP BY period ORDER BY period"))
    if "derivatives" in tables:
        out["derivative_periods"] = [r[0] for r in con.execute(
            "SELECT DISTINCT period FROM derivatives ORDER BY 1").fetchall()]
        out["derivative_per_period"] = _rows(con.execute(
            "SELECT period, count(*) AS operations,"
            " count(DISTINCT compartment_key) AS compartments"
            " FROM derivatives GROUP BY period ORDER BY period"))
        out["derivative_representations"] = {
            r[0]: r[1] for r in con.execute(
                "SELECT representation, count(*) FROM derivatives"
                " GROUP BY representation").fetchall()}
    if "derivative_coverage" in tables:
        out["derivative_coverage"] = _rows(con.execute(
            "SELECT period, count(*) AS compartments,"
            " sum(CASE WHEN n_operations = 0 THEN 1 ELSE 0 END)"
            " AS zero_ops FROM derivative_coverage"
            " GROUP BY period ORDER BY period"))
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
