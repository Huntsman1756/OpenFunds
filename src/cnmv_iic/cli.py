"""cnmv-iic CLI — G1 vertical slice."""

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
from cnmv_iic.query import dataset_info, funds_holding
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


@app.command()
def update(
    period: Annotated[str, typer.Option(help="Publication period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Download one CNMV period and export canonical FONDCART positions."""
    root = data_dir or _data_dir()
    try:
        result = update_period(
            ArtifactStore(root / "artifacts"), root / "dataset", period
        )
    except CnmvIicError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(
        {
            "period": result.period,
            "artifact": result.artifact.source_id,
            "artifact_sha256": result.artifact.sha256,
            "artifact_new_version": result.artifact_new,
            "exported": result.exported,
            "dataset_fingerprint": result.dataset_fingerprint,
            "positions": result.positions,
            "quality_rows": result.quality_rows,
        },
        json_out,
    )


@app.command()
def holdings(
    fund: Annotated[str, typer.Argument(
        help="CNMV key FI:<numero_registro>:<compartimento> or numero_registro"
    )],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reported portfolio positions for one fund at latest period <= as-of."""
    root = data_dir or _data_dir()
    try:
        period, rows = query_holdings(root / "dataset", fund, as_of)
    except CnmvIicError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit({"period": period, "fund": fund, "positions": rows}, json_out)


@app.command(name="funds-holding")
def funds_holding_cmd(
    isin: Annotated[str, typer.Argument(help="Instrument ISIN")],
    as_of: Annotated[str | None, typer.Option(help="YYYY-MM-DD or YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Funds REPORTING A PORTFOLIO POSITION in `isin` (not beneficial owners)."""
    root = data_dir or _data_dir()
    try:
        period, rows = funds_holding(root / "dataset", isin, as_of)
    except CnmvIicError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc
    _emit(
        {
            "period": period,
            "isin": isin,
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
    """Periods, row counts, quality states, dataset fingerprints."""
    root = data_dir or _data_dir()
    try:
        _emit(dataset_info(root / "dataset"), json_out)
    except CnmvIicError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc


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
