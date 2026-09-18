"""cnmv-iic CLI — G1 holdings slice + G2 regulatory identity."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import typer

from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.errors import CnmvIicError
from cnmv_iic.ingest import update_period
from cnmv_iic.query import (
    class_observation_summary,
    daily_series,
    dataset_info,
    fund_info,
    funds_by_institution,
    funds_holding,
    identity_events,
    patrimony_reconciliation,
    share_class_info,
)
from cnmv_iic.query import holdings as query_holdings

app = typer.Typer(
    name="cnmv-iic",
    help="Provenance-preserving CNMV IIC disclosure pipeline.",
    no_args_is_help=True,
)

DATA_DIR_ENV = "CNMV_IIC_DATA_DIR"


def _data_dir() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV, Path.home() / ".cnmv-iic"))


def _emit(obj: Any, as_json: bool) -> None:
    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return str(o)
        if is_dataclass(o) and not isinstance(o, type):
            return asdict(o)
        return str(o)

    if as_json:
        typer.echo(json.dumps(obj, default=default, indent=1, sort_keys=True))
    elif isinstance(obj, str):
        typer.echo(obj)
    else:
        typer.echo(json.dumps(obj, default=default, indent=1, sort_keys=True))


def _run(fn: Any) -> Any:
    try:
        return fn()
    except CnmvIicError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command()
def update(
    period: Annotated[str, typer.Option(help="Publication period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Download one CNMV period; export canonical positions + registry."""
    root = data_dir or _data_dir()
    result = _run(lambda: update_period(
        ArtifactStore(root / "artifacts"), root / "dataset", period))
    _emit(
        {
            "period": result.period,
            "artifact": result.artifact.source_id,
            "artifact_sha256": result.artifact.sha256,
            "artifact_new_version": result.artifact_new,
            "exported": result.exported,
            "fondcart_present": result.fondcart_present,
            "fondmens_present": result.fondmens_present,
            "fondtrim_present": result.fondtrim_present,
            "fondpatrimdisvar_present": result.fondpatrimdisvar_present,
            "dataset_fingerprint": result.dataset_fingerprint,
            "registry_fingerprint": result.registry_fingerprint,
            "daily_fingerprint": result.daily_fingerprint,
            "quarterly_fingerprint": result.quarterly_fingerprint,
            "patrimony_fingerprint": result.patrimony_fingerprint,
            "positions": result.positions,
            "quality_rows": result.quality_rows,
            "funds": result.funds,
            "share_classes": result.share_classes,
            "daily_observations": result.daily_observations,
            "quarterly_metrics": result.quarterly_metrics,
            "patrimony_records": result.patrimony_records,
        },
        json_out,
    )


@app.command()
def holdings(
    fund: Annotated[str, typer.Argument(
        help="Share-class ISIN, or CNMV key FI:<reg>:<comp> / FI:<reg> / <reg>"
    )],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    exact: Annotated[bool, typer.Option(
        "--exact", help="Fail unless a snapshot exists at the as-of month")] = False,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reported portfolio positions at latest period <= as-of.

    A share-class ISIN resolves through FONDREGISTRO to its compartment
    portfolio owner — several classes may share one portfolio (never
    duplicated). The response always exposes requested_as_of,
    portfolio_period, resolution_mode and stale so a fallback snapshot
    can never look contemporaneous; --exact disables fallback entirely.
    """
    root = data_dir or _data_dir()
    period, resolution, rows = _run(
        lambda: query_holdings(root / "dataset", fund, as_of, exact=exact))
    _emit(
        {"period": period, "resolution": resolution, "positions": rows},
        json_out,
    )


@app.command()
def fund(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or CNMV key FI:<reg>[:<comp>[:<clase>]]"
    )],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """FONDREGISTRO identity record for a fund."""
    root = data_dir or _data_dir()
    period, resolution, record = _run(
        lambda: fund_info(root / "dataset", identifier, as_of))
    _emit(
        {"period": period, "resolution": resolution, **record},
        json_out,
    )


@app.command(name="share-class")
def share_class(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>"
    )],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """One share class and its fund context (FONDREGISTRO)."""
    root = data_dir or _data_dir()
    period, resolution, record = _run(
        lambda: share_class_info(root / "dataset", identifier, as_of))
    _emit(
        {"period": period, "resolution": resolution, **record},
        json_out,
    )


def _daily_cmd(metric: str, identifier: str, from_date: str | None,
               to_date: str | None, data_dir: Path | None,
               json_out: bool) -> None:
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: daily_series(
        root / "dataset", identifier, metric, from_date, to_date))
    _emit({"resolution": meta, "observations": rows}, json_out)


@app.command()
def nav(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    from_date: Annotated[str | None, typer.Option(
        "--from", help="ISO date YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option(
        "--to", help="ISO date YYYY-MM-DD")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Daily valor liquidativo (NAV, EUR) for one share class.

    OBSERVED values only — sentinel/missing cells keep NULL + raw + state.
    """
    _daily_cmd("nav", identifier, from_date, to_date, data_dir, json_out)


@app.command()
def aum(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    from_date: Annotated[str | None, typer.Option(
        "--from", help="ISO date YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option(
        "--to", help="ISO date YYYY-MM-DD")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Daily patrimonio (AUM, EUR) for one share class."""
    _daily_cmd("aum", identifier, from_date, to_date, data_dir, json_out)


@app.command()
def investors(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    from_date: Annotated[str | None, typer.Option(
        "--from", help="ISO date YYYY-MM-DD")] = None,
    to_date: Annotated[str | None, typer.Option(
        "--to", help="ISO date YYYY-MM-DD")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Daily participes (investor count) for one share class."""
    _daily_cmd("investors", identifier, from_date, to_date, data_dir, json_out)


@app.command(name="class")
def class_card(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Share-class identity + FONDMENS observation coverage."""
    root = data_dir or _data_dir()
    info, summary = _run(lambda: class_observation_summary(
        root / "dataset", identifier, as_of))
    _emit({"resolution": info, "coverage": summary}, json_out)


@app.command()
def manager(
    numero_registro: Annotated[str, typer.Argument(
        help="CNMV gestora registration number (e.g. 190)"
    )],
    funds: Annotated[bool, typer.Option(
        "--funds", help="List managed funds")] = False,
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Institution record + (with --funds) the funds it manages."""
    root = data_dir or _data_dir()
    period, inst, rows = _run(lambda: funds_by_institution(
        root / "dataset", "gestora", numero_registro, as_of))
    out: dict = {"period": period, "institution": inst,
                 "fund_count": len(rows)}
    if funds:
        out["funds"] = rows
    _emit(out, json_out)


@app.command()
def depositary(
    numero_registro: Annotated[str, typer.Argument(
        help="CNMV depositario registration number (e.g. 211)"
    )],
    funds: Annotated[bool, typer.Option(
        "--funds", help="List deposited funds")] = False,
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Institution record + (with --funds) the funds it deposits."""
    root = data_dir or _data_dir()
    period, inst, rows = _run(lambda: funds_by_institution(
        root / "dataset", "depositario", numero_registro, as_of))
    out: dict = {"period": period, "institution": inst,
                 "fund_count": len(rows)}
    if funds:
        out["funds"] = rows
    _emit(out, json_out)


@app.command(name="fund-events")
def fund_events(
    from_period: Annotated[str, typer.Option(
        "--from", help="Earlier observed period YYYY-MM")],
    to_period: Annotated[str, typer.Option(
        "--to", help="Later observed period YYYY-MM")],
    fund: Annotated[str | None, typer.Option(
        help="Restrict to one fund (ISIN or CNMV key)")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Mechanical identity diff between two registry snapshots.

    Reports WHAT changed (name/manager/depositary/classes/ISINs/
    compartments) — never WHY. Fund additions/removals as a whole are
    out of scope for this gate.
    """
    root = data_dir or _data_dir()
    events = _run(lambda: identity_events(
        root / "dataset", from_period, to_period, fund))
    _emit(
        {"from_period": from_period, "to_period": to_period,
         "events": events},
        json_out,
    )


@app.command(name="funds-holding")
def funds_holding_cmd(
    isin: Annotated[str, typer.Argument(help="Instrument ISIN")],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    exact: Annotated[bool, typer.Option(
        "--exact", help="Fail unless a snapshot exists at the as-of month")] = False,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Funds REPORTING A PORTFOLIO POSITION in `isin` (not beneficial owners)."""
    root = data_dir or _data_dir()
    period, meta, rows = _run(
        lambda: funds_holding(root / "dataset", isin, as_of, exact=exact))
    _emit(
        {
            "period": period,
            "isin": isin,
            **meta,
            "semantics": "reported portfolio positions (not beneficial ownership)",
            "funds": rows,
        },
        json_out,
    )


@app.command(name="dataset-info")
def dataset_info_cmd(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Periods, row counts, quality states, fingerprints."""
    root = data_dir or _data_dir()
    _emit(_run(lambda: dataset_info(root / "dataset")), json_out)


@app.command()
def reconcile(
    period: Annotated[str, typer.Argument(
        help="period YYYY-MM with FONDTRIM+FONDPATRIMDISVAR+FONDMENS"
    )],
    tolerance: Annotated[float, typer.Option(
        help="relative tolerance for 'match' (default 1%)"
    )] = 0.01,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Cross-family patrimony comparison — derived, equality not required."""
    root = data_dir or _data_dir()
    _emit(
        _run(lambda: patrimony_reconciliation(
            root / "dataset", period,
            tolerance_rel=Decimal(str(tolerance)))),
        json_out,
    )


@app.command()
def source(
    artifact_id: Annotated[str, typer.Argument(
        help="cnmv-iic-zip/<period>/<sha256> or bare sha256 prefix"
    )],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Provenance record for a source artifact."""
    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    match = None
    for a in store.load():
        if a.source_id == artifact_id or a.sha256.startswith(artifact_id):
            match = a
            break
    if match is None:
        typer.echo(f"error: artifact {artifact_id!r} not found", err=True)
        raise typer.Exit(1)
    _emit(
        {
            "source_id": match.source_id,
            "provider": match.provider,
            "period": match.period,
            "sha256": match.sha256,
            "size_bytes": match.size_bytes,
            "retrieved_at": match.retrieved_at,
            "source_page": match.source_page,
            "supersedes": match.supersedes,
            "members": [
                {"name": m.name, "size": m.size, "sha256": m.sha256}
                for m in match.members
            ],
            "xsd_sha256": match.xsd_sha256,
            "integrity_verified": store.verify_integrity(match),
        },
        json_out,
    )


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
