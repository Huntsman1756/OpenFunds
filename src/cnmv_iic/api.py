"""cnmv_iic public API — the supported contract since v0.1.

Everything exported here is part of the stable surface: dataset
opening, entity resolution, holdings, NAV/AUM/investor series,
issuer exposure, lifecycle adjudication and derived lineage.

Internal DuckDB views and module-private helpers are NOT part of the
contract — import only from this module (or the CLI, which wraps it).

All functions are read-only, offline, and deterministic over a local
dataset directory produced by `cnmv-iic update/backfill` +
`cnmv-iic lifecycle-export`.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cnmv_iic import __version__
from cnmv_iic.query import (
    class_observation_summary,
    daily_series,
    dataset_info,
    fund_info,
    funds_by_institution,
    funds_exposed_to,
    funds_holding,
    holdings,
    identity_events,
    lei_evidence,
    lifecycle_fund,
    official_returns,
    patrimony_allocation,
    patrimony_reconciliation,
    portfolio_diff,
    portfolio_history,
    position_history,
    predecessors_of,
    quarterly_fees,
    quarterly_metrics,
    resolution_conflicts,
    resolution_coverage,
    security_evidence,
    security_resolution,
    share_class_info,
)
from cnmv_iic.versions import contract as versions_contract

__all__ = ["Dataset", "open_dataset", "versions_contract",
           "__version__"]


def _pack(names: tuple[str, ...], result: tuple) -> dict:
    return dict(zip(names, result, strict=True))


class Dataset:
    """Read-only handle over a local cnmv-iic dataset directory.

    Wraps the supported query surface; never exposes raw DuckDB
    internals. All methods return plain JSON-serializable dicts."""
    def __init__(self, root: Path | str):
        self.root = Path(root)

    # -- dataset ----------------------------------------------------
    def info(self) -> dict:
        """Periods, row counts, quality states, lifecycle layer,
        fingerprints, compatibility contract."""
        return dataset_info(self.root)

    def versions(self) -> dict:
        """Compatibility contract: schema/model/engine/parser."""
        return versions_contract()

    # -- identity ---------------------------------------------------
    def fund(self, key: str, as_of: str | None = None) -> dict:
        """Registry record for a fund identifier (FI:<regnum>, regnum,
        or ISIN)."""
        return _pack(("period", "resolution", "record"),
                     fund_info(self.root, key, as_of))

    def share_class(self, key: str, as_of: str | None = None) -> dict:
        """Registry record for a share-class identifier."""
        return _pack(("period", "resolution", "record"),
                     share_class_info(self.root, key, as_of))

    def class_summary(self, key: str, as_of: str | None = None) -> dict:
        return _pack(("share_class", "summary"),
                     class_observation_summary(self.root, key, as_of))

    def funds_of_institution(
            self, role: str, register_number: str,
            as_of: str | None = None) -> dict:
        """Funds managed/deposited by an institution.
        ``role``: 'gestora' | 'depositario'."""
        return _pack(("period", "institution", "funds"),
                     funds_by_institution(
                         self.root, role, register_number, as_of))

    def fund_events(self, from_period: str, to_period: str,
                    fund: str | None = None) -> dict:
        """Mechanical registry diffs — WHAT changed, never WHY."""
        return {"events": identity_events(
            self.root, from_period, to_period, fund)}

    # -- holdings ---------------------------------------------------
    def holdings(self, identifier: str, as_of: str | None = None,
                 exact: bool = False) -> dict:
        """Reported portfolio positions for an ISIN/fund/compartment."""
        return _pack(("period", "resolution", "positions"),
                     holdings(self.root, identifier, as_of, exact=exact))

    def funds_holding(self, isin: str, as_of: str | None = None,
                      exact: bool = False) -> dict:
        """Funds reporting a position in an instrument — REPORTED
        PORTFOLIO POSITIONS, never beneficial ownership."""
        return _pack(("period", "resolution", "funds"),
                     funds_holding(self.root, isin, as_of, exact=exact))

    def portfolio_diff(self, identifier: str,
                       from_period: str | None = None,
                       to_period: str | None = None,
                       previous: bool = False) -> dict:
        return _pack(("meta", "diffs"),
                     portfolio_diff(self.root, identifier, from_period,
                                    to_period, previous=previous))

    def position_history(self, identifier: str, isin: str) -> dict:
        return _pack(("meta", "history"),
                     position_history(self.root, identifier, isin))

    def portfolio_history(self, identifier: str) -> dict:
        return _pack(("meta", "history"),
                     portfolio_history(self.root, identifier))

    # -- observations -----------------------------------------------
    def nav(self, key: str, frm: str | None = None,
            to: str | None = None) -> dict:
        """Daily NAV series for a share class."""
        return _pack(("meta", "series"),
                     daily_series(self.root, key, "nav", frm, to))

    def aum(self, key: str, frm: str | None = None,
            to: str | None = None) -> dict:
        return _pack(("meta", "series"),
                     daily_series(self.root, key, "aum", frm, to))

    def investors(self, key: str, frm: str | None = None,
                  to: str | None = None) -> dict:
        return _pack(("meta", "series"),
                     daily_series(self.root, key, "investors", frm, to))

    def metrics(self, key: str, period: str) -> dict:
        """Quarterly metrics block for one share class (YYYY-MM)."""
        return quarterly_metrics(self.root, key, period)

    def fees(self, key: str, period: str) -> dict:
        return quarterly_fees(self.root, key, period)

    def official_returns(self, key: str,
                         from_period: str | None = None,
                         to_period: str | None = None) -> dict:
        """CNMV-computed returns — verbatim, never recomputed."""
        return _pack(("meta", "series"),
                     official_returns(self.root, key, from_period,
                                      to_period))

    def allocation(self, identifier: str, period: str) -> dict:
        return _pack(("meta", "rows"),
                     patrimony_allocation(self.root, identifier, period))

    def reconcile(self, period: str, tolerance: float = 0.01) -> dict:
        """Cross-family patrimony comparison — derived, equality
        never required."""
        return patrimony_reconciliation(
            self.root, period,
            tolerance_rel=Decimal(str(tolerance)))

    # -- issuer exposure (G7/G8) ------------------------------------
    def issuer(self, isin: str, version: str | None = None,
               bundle: str | None = None) -> dict:
        """Issuer-resolution verdict for one ISIN; conflicts carry the
        full context, never a picked winner."""
        return security_resolution(self.root, isin, version=version,
                                   bundle=bundle)

    def issuer_evidence(self, isin: str) -> dict:
        return security_evidence(self.root, isin)

    def lei_evidence(self, lei: str) -> dict:
        return lei_evidence(self.root, lei)

    def issuer_coverage(self, version: str | None = None,
                        bundle: str | None = None) -> dict:
        return resolution_coverage(self.root, version=version,
                                   bundle=bundle)

    def issuer_conflicts(self, version: str | None = None,
                         bundle: str | None = None) -> dict:
        """Every CONFLICT row — the disagreement surface, never
        adjudicated away."""
        return resolution_conflicts(self.root, version=version,
                                    bundle=bundle)

    def funds_exposed_to(self, lei: str, period: str,
                         include_positions: bool = False) -> dict:
        """Funds reporting exposure to an issuer (LEI) — reported
        positions, never beneficial ownership."""
        return funds_exposed_to(self.root, lei, period,
                                include_positions=include_positions)

    # -- lifecycle (G9) -----------------------------------------------
    def lifecycle(self, entity_key: str) -> dict:
        """What happened to a fund: adjudication + derived ABSORBED_BY
        edges in both directions, full evidence provenance."""
        return lifecycle_fund(self.root, entity_key)

    def predecessors_of(self, entity_key: str) -> dict:
        """Funds adjudicated as absorbed by this fund."""
        return predecessors_of(self.root, entity_key)


def open_dataset(path: Path | str | None = None) -> Dataset:
    """Open a local cnmv-iic dataset directory (default: the standard
    data dir, same as the CLI's --data-dir resolution)."""
    if path is None:
        from cnmv_iic.cli import _data_dir
        path = _data_dir() / "dataset"
    return Dataset(path)
