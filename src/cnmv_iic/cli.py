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
from cnmv_iic.ingest import backfill_periods, update_period
from cnmv_iic.provider_ingest import (
    ingest_firds_fulins,
    ingest_gleif_golden,
    ingest_gleif_isin_lei,
    ingest_openfigi,
)
from cnmv_iic.query import (
    class_observation_summary,
    daily_series,
    dataset_info,
    derivative_operations,
    derivative_reconciliation,
    fund_info,
    funds_by_institution,
    funds_exposed_to,
    funds_holding,
    identity_events,
    lei_evidence,
    official_returns,
    patrimony_allocation,
    patrimony_reconciliation,
    portfolio_diff,
    portfolio_history,
    position_history,
    quarterly_fees,
    quarterly_metrics,
    resolution_conflicts,
    resolution_coverage,
    security_resolution,
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
            "derivatives_fingerprint": result.derivatives_fingerprint,
            "positions": result.positions,
            "quality_rows": result.quality_rows,
            "funds": result.funds,
            "share_classes": result.share_classes,
            "daily_observations": result.daily_observations,
            "quarterly_metrics": result.quarterly_metrics,
            "patrimony_records": result.patrimony_records,
            "derivative_operations": result.derivative_operations,
            "derivative_coverage_records":
                result.derivative_coverage_records,
            "fondderi_present": result.fondderi_present,
        },
        json_out,
    )


@app.command()
def backfill(
    from_period: Annotated[str, typer.Option(
        "--from", help="First publication period YYYY-MM")],
    to_period: Annotated[str, typer.Option(
        "--to", help="Last publication period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """G9-A2 — chronological resumable monthly backfill.

    Artifact present + export complete -> no network; artifact stored
    but unexported -> export from local bytes; otherwise download via
    the hardened client. Per-period failures are isolated."""
    root = data_dir or _data_dir()
    out = _run(lambda: backfill_periods(
        ArtifactStore(root / "artifacts"), root / "dataset",
        from_period, to_period))
    _emit(out, json_out)


@app.command(name="ingest-provider")
def ingest_provider(
    provider: Annotated[str, typer.Argument(
        help="Provider dataset: gleif-isin-lei")],
    zip_path: Annotated[Path, typer.Argument(
        help="Pinned provider artifact ZIP (full snapshot)")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ingest a pinned provider snapshot into the resolution evidence ledger.

    The artifact is stored immutably (SHA-256), parsed once, and joined
    exactly by ISIN against the corpus positions universe. Re-ingesting
    the same bytes is a no-op; a new snapshot date creates NEW evidence,
    never an overwrite. This produces observations, not canonical
    resolution (adjudication comes after all providers are loaded).
    """
    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    if provider == "gleif-isin-lei":
        result = _run(lambda: ingest_gleif_isin_lei(
            store, root / "dataset", zip_path))
    else:
        raise typer.BadParameter(
            f"unknown provider {provider!r} — supported: gleif-isin-lei")
    _emit(
        {
            "provider": result.provider,
            "provider_snapshot_date": result.snapshot_date,
            "artifact": result.artifact.source_id,
            "artifact_sha256": result.artifact.sha256,
            "artifact_new": result.artifact_new,
            "exported": result.exported,
            "universe_isins": result.universe_isins,
            "observations": result.observations,
            "matched": result.matched,
            "multiple_candidates": result.multiple_candidates,
            "no_match": result.no_match,
            "candidates": result.candidates,
            "resolution_fingerprint": result.resolution_fingerprint,
        },
        json_out,
    )


@app.command(name="ingest-firds-fulins")
def ingest_firds_cmd(
    zips: Annotated[list[Path], typer.Argument(
        help="All in-scope FULINS parts of ONE snapshot date")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ingest a complete pinned FULINS snapshot as resolution evidence.

    Every part must declare the same snapshot date (filename and the
    in-file RptgPrd/Dt must agree) and each asset letter's part set must
    be complete (NNofMM). Records are extracted only for corpus ISINs;
    ISIN x venue records backing the same LEI are preserved as evidence
    rows — never collapsed, never counted as multiple candidates.
    """
    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    result = _run(lambda: ingest_firds_fulins(
        store, root / "dataset", zips))
    _emit(
        {
            "provider": result.provider,
            "provider_snapshot_date": result.snapshot_date,
            "artifact_ids": result.artifact_ids,
            "artifacts_new": result.artifacts_new,
            "exported": result.exported,
            "universe_isins": result.universe_isins,
            "observations": result.observations,
            "matched": result.matched,
            "multiple_candidates": result.multiple_candidates,
            "no_candidate": result.no_candidate,
            "no_match": result.no_match,
            "candidates": result.candidates,
            "evidence_records": result.evidence_records,
            "resolution_fingerprint": result.resolution_fingerprint,
        },
        json_out,
    )


@app.command(name="ingest-gleif-golden")
def ingest_gleif_golden_cmd(
    lei_cdf: Annotated[Path, typer.Option(
        "--lei-cdf", help="Pinned LEI-CDF 3.1 concatenated ZIP")],
    rr_cdf: Annotated[Path, typer.Option(
        "--rr-cdf", help="Pinned RR-CDF 2.1 concatenated ZIP")],
    repex: Annotated[Path, typer.Option(
        "--repex", help="Pinned Reporting Exceptions 2.1 ZIP")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Ingest the three GLEIF concatenated files as entity/relationship/
    exception evidence for LEIs reachable from G7-A candidates.

    The three files must declare the SAME snapshot date — mixed bundles
    are rejected fail-closed. Extraction is filtered, not a GLEIF replica:
    relationships where the start LEI is a resolved candidate; Level-1
    records for resolved LEIs plus the bounded one-hop closure over RR
    end nodes; reporting exceptions for resolved LEIs. Relationship
    types are preserved verbatim — never renamed to "parent".
    """
    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    result = _run(lambda: ingest_gleif_golden(
        store, root / "dataset", lei_cdf, rr_cdf, repex))
    _emit(
        {
            "provider_snapshot_date": result.snapshot_date,
            "artifact_ids": result.artifact_ids,
            "artifacts_new": result.artifacts_new,
            "exported": result.exported,
            "wanted_lei_count": result.wanted_lei_count,
            "closure_lei_count": result.closure_lei_count,
            "legal_entities": result.legal_entities,
            "entities_resolved_role": result.entities_resolved_role,
            "entities_closure_role": result.entities_closure_role,
            "relationships": result.relationships,
            "relationship_types": list(result.relationship_types),
            "relationship_exceptions": result.relationship_exceptions,
            "evidence_fingerprint": result.evidence_fingerprint,
        },
        json_out,
    )


@app.command(name="fetch-openfigi")
def fetch_openfigi_cmd(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Fetch the corpus ISIN universe through OpenFIGI /v3/mapping.

    Deterministic batches (sorted ISINs, 10 jobs/request anonymous /
    100 with OPENFIGI_API_KEY) whose raw request/response bytes are
    stored as immutable artifacts under
    ``dataset/provider_raw/openfigi/<retrieval-date>/batches/``.
    Resuming skips completed batches — nothing is re-requested or
    overwritten. Respects documented rate limits and 429/5xx handling.
    """
    from datetime import UTC, datetime

    from cnmv_iic.openfigi_client import (
        _ANON_MIN_INTERVAL,
        _KEY_MIN_INTERVAL,
        BATCH_SIZE_ANON,
        BATCH_SIZE_KEY,
        RateLimiter,
        UrllibPoster,
        run_campaign,
    )
    from cnmv_iic.provider_ingest import _corpus_isin_universe

    root = data_dir or _data_dir()
    dataset = root / "dataset"
    isins = sorted(_run(lambda: _corpus_isin_universe(dataset)))
    campaign = datetime.now(UTC).date().isoformat()
    bdir = dataset / "provider_raw" / "openfigi" / campaign / "batches"
    bdir.mkdir(parents=True, exist_ok=True)
    api_key = os.environ.get("OPENFIGI_API_KEY") or None
    keyed = api_key is not None
    outcomes = _run(lambda: run_campaign(
        bdir, isins,
        poster=UrllibPoster(api_key=api_key),
        limiter=RateLimiter(
            _KEY_MIN_INTERVAL if keyed else _ANON_MIN_INTERVAL),
        batch_size=BATCH_SIZE_KEY if keyed else BATCH_SIZE_ANON,
        retrieved_at=lambda: datetime.now(UTC).isoformat(),
        on_progress=lambda d, t: typer.echo(
            f"{d}/{t} batches", err=True) if d % 100 == 0 or d == t
        else None))
    counts: dict[str, int] = {}
    for o in outcomes:
        counts[o.status] = counts.get(o.status, 0) + 1
    _emit(
        {
            "campaign": campaign,
            "batches_dir": str(bdir),
            "universe_isins": len(isins),
            "batches": len(outcomes),
            "api_key": "env-provided" if keyed else "anonymous",
            **counts,
        },
        json_out,
    )


@app.command(name="ingest-openfigi")
def ingest_openfigi_cmd(
    campaign_dir: Annotated[Path | None, typer.Option(
        help="Campaign dir (default: latest under provider_raw/"
             "openfigi)")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Export a stored OpenFIGI campaign into the evidence tables.

    Pure local function of the stored batch artifacts — re-running is
    byte-deterministic and never calls the API. Universe ISINs with no
    stored job become ``provider_error`` observations: an incomplete
    campaign is visible, never silently partial.
    """
    root = data_dir or _data_dir()
    dataset = root / "dataset"
    if campaign_dir is None:
        base = dataset / "provider_raw" / "openfigi"
        campaigns = sorted(
            p for p in base.glob("*") if p.is_dir()) if base.exists() else []
        if not campaigns:
            typer.echo(
                "error: no OpenFIGI campaign under "
                f"{base} — run `cnmv-iic fetch-openfigi` first", err=True)
            raise typer.Exit(1)
        campaign_dir = campaigns[-1]
    result = _run(lambda: ingest_openfigi(dataset, campaign_dir))
    _emit(
        {
            "provider": result.provider,
            "campaign": result.campaign,
            "batches": result.batches,
            "exported": result.exported,
            "universe_isins": result.universe_isins,
            "observations": result.observations,
            "matched_single": result.matched_single,
            "matched_multi": result.matched_multi,
            "no_match": result.no_match,
            "provider_error": result.provider_error,
            "invalid_response": result.invalid_response,
            "candidates": result.candidates,
            "instrument_fingerprint": result.instrument_fingerprint,
        },
        json_out,
    )


@app.command(name="lifecycle-acquire-weeks")
def lifecycle_acquire_weeks(
    from_month: Annotated[str, typer.Option(
        "--from", help="First month YYYY-MM (widened to weeks)")],
    to_month: Annotated[str, typer.Option(
        "--to", help="Last month YYYY-MM (widened to weeks)")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """G9-B — chronological resumable weekly-bulletin acquisition.

    Per week: ``lnkRegistro`` when present, ``lnkBoletinCompleto`` as
    the general fallback; the selection page is stored only when a
    week exposes no document link (gap evidence). Stored artifacts are
    never re-downloaded — resume is 0-network.
    """
    from cnmv_iic.lifecycle_ingest import acquire_weeks

    root = data_dir or _data_dir()
    out = _run(lambda: acquire_weeks(
        ArtifactStore(root / "artifacts"), root / "dataset",
        from_month, to_month,
        on_progress=lambda d, t: typer.echo(f"{d}/{t} weeks", err=True)))
    _emit(out, json_out)


@app.command(name="lifecycle-acquire-hr")
def lifecycle_acquire_hr(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    holdout_manifest: Annotated[Path, typer.Option(
        "--holdout-manifest",
        help="Sealed blind-holdout candidate ids (never queried)")] =
    Path("docs/g9/blind-holdout-manifest.json"),
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """G9-B — per-entity HR crawl for development candidates.

    Searches relevant-information by historical denominacion inside the
    measured -14/+4-month window, stores the search + history pages as
    immutable artifacts. Blind-holdout candidates are never queried,
    linked, or inspected."""
    from cnmv_iic.lifecycle_ingest import acquire_hr

    root = data_dir or _data_dir()
    out = _run(lambda: acquire_hr(
        ArtifactStore(root / "artifacts"), root / "dataset",
        holdout_manifest,
        on_progress=lambda d, t: typer.echo(f"{d}/{t} entities", err=True)))
    _emit(out, json_out)


@app.command(name="lifecycle-export")
def lifecycle_export(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    holdout_manifest: Annotated[Path, typer.Option(
        "--holdout-manifest",
        help="Sealed blind-holdout candidate ids (never linked)")] =
    Path("docs/g9/blind-holdout-manifest.json"),
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """G9-B — rebuild the source-assertion ledger from stored artifacts.

    Pure offline function of raw artifact bytes + parser/rule versions:
    weekly registry + HR + FONDREGISTRO marker documents -> source
    observations -> descriptive assertions -> exact-regnum candidate
    links -> parquet + fingerprints. No network, no clocks, no
    holdout-linked rows."""
    import json as _json

    from cnmv_iic.lifecycle_ingest import (
        assertion_participants,
        candidate_links,
        disappearance_candidates,
        fondregistro_markers,
        holdout_ids,
        hr_ledger,
        weekly_ledger,
    )
    from cnmv_iic.lifecycle_storage import write_lifecycle

    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    hindex_path = root / "dataset" / "lifecycle" / "hr_index.json"
    hindex = (
        _json.loads(hindex_path.read_text(encoding="utf-8"))
        if hindex_path.exists() else {})
    w_docs, w_obs, w_asserts = weekly_ledger(store)
    h_docs, h_obs, h_asserts, resolutions = hr_ledger(store, hindex)
    f_docs, f_obs, f_asserts = fondregistro_markers(
        root / "dataset", store)
    all_asserts = w_asserts + h_asserts + f_asserts
    sealed = holdout_ids(holdout_manifest)
    cands = disappearance_candidates(root / "dataset")
    links = candidate_links(cands, all_asserts, sealed)
    all_obs = w_obs + h_obs + f_obs
    parts = assertion_participants(all_asserts, all_obs)
    out = _run(lambda: write_lifecycle(
        root / "dataset",
        documents=w_docs + h_docs + f_docs,
        observations=all_obs,
        assertions=all_asserts,
        entity_resolutions=resolutions,
        candidate_links=links,
        candidates=cands,
        participants=parts))
    _emit(out, json_out)


@app.command()
def adjudicate(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    version: Annotated[str, typer.Option(
        help="Rules version — bump when adjudication rules change")] = "1",
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Derive issuer + instrument-family resolutions (G7-E).

    Reads the pinned evidence bundle (latest provider evidence per
    family) and writes a derived resolution partitioned by
    (version, bundle). Idempotent: same bundle + same version is a
    no-op; a new bundle or version creates a new logical resolution —
    never an overwrite. Conflict context is enriched by a bounded
    second pass over the SAME stored GLEIF raw artifacts."""
    from cnmv_iic.adjudication import adjudicate as _adjudicate

    root = data_dir or _data_dir()
    store = ArtifactStore(root / "artifacts")
    result = _run(lambda: _adjudicate(
        root / "dataset", store, version=version))
    _emit(
        {
            "version": result.version,
            "bundle_fingerprint": result.bundle_fingerprint,
            "exported": result.exported,
            "securities": result.securities,
            "instrument_families": result.families,
            "security_states": result.security_states,
            "family_states": result.family_states,
            "adjudication_fingerprint": result.adjudication_fingerprint,
        },
        json_out,
    )


@app.command()
def security(
    isin: Annotated[str, typer.Argument(help="ISIN (12 chars)")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Adjudicated view of one ISIN: issuer verdict, instrument family,
    and the evidence bundle that produced them."""
    root = data_dir or _data_dir()
    out = _run(lambda: security_resolution(root / "dataset", isin))
    sec = out.get("security") or {}
    if sec.get("resolved_lei"):
        ent = _run(lambda: lei_evidence(root / "dataset",
                                        sec["resolved_lei"]))
        names = [e.get("legal_name") for e in ent.get("entities", [])
                 if e.get("legal_name")]
        if names:
            sec["resolved_legal_name"] = names[0]
    _emit(out, json_out)


@app.command()
def resolution(
    isin: Annotated[str, typer.Argument(help="ISIN (12 chars)")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Issuer-resolution verdict for one ISIN — conflict rows carry the
    full context JSON, never a picked winner."""
    root = data_dir or _data_dir()
    _emit(_run(lambda: security_resolution(root / "dataset", isin)),
          json_out)


@app.command(name="resolution-coverage")
def resolution_coverage_cmd(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """State distribution of the latest adjudication (full corpus)."""
    root = data_dir or _data_dir()
    _emit(_run(lambda: resolution_coverage(root / "dataset")), json_out)


@app.command(name="resolution-conflicts")
def resolution_conflicts_cmd(
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Every CONFLICT row of the latest adjudication with parsed context
    — the GLEIF/FIRDS disagreement surface, never adjudicated away."""
    root = data_dir or _data_dir()
    _emit(_run(lambda: resolution_conflicts(root / "dataset")), json_out)


@app.command()
def lei(
    lei_value: Annotated[str, typer.Argument(help="20-char ISO-17442 LEI")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """GLEIF evidence for one LEI: entity record, relationships (both
    directions), reporting exceptions — verbatim, no adjudication."""
    root = data_dir or _data_dir()
    _emit(_run(lambda: lei_evidence(root / "dataset", lei_value)),
          json_out)


@app.command(name="funds-exposed-to")
def funds_exposed_to_cmd(
    lei_value: Annotated[str, typer.Argument(help="20-char ISO-17442 LEI")],
    period: Annotated[str, typer.Option(help="Holdings period YYYY-MM")],
    evidence: Annotated[str, typer.Option(
        help="all-resolved | corroborated | single-source")] = "all-resolved",
    positions: Annotated[bool, typer.Option(
        "--positions", help="include position-row detail")] = False,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Portfolio owners reporting positions resolved to this issuer LEI.

    known_resolved_value is a LOWER BOUND — unresolved securities can
    never be proven not to belong to the issuer, so issuer-specific
    completeness is always null; only the period-universe coverage is
    a ratio. Conflicts never enter issuer totals."""
    root = data_dir or _data_dir()
    out = _run(lambda: funds_exposed_to(
        root / "dataset", lei_value, period, evidence=evidence,
        include_positions=positions))
    _emit(out, json_out)


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
    out = _run(lambda: patrimony_reconciliation(
        root / "dataset", period,
        tolerance_rel=Decimal(str(tolerance))))
    try:
        out["derivatives"] = derivative_reconciliation(
            root / "dataset", period)
    except CnmvIicError:
        pass                                    # family absent — honest
    _emit(out, json_out)


@app.command()
def metrics(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    as_of: Annotated[str, typer.Option(
        help="quarterly period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Full FONDTRIM quarterly row for one share class — verbatim fields."""
    root = data_dir or _data_dir()
    _emit(
        _run(lambda: quarterly_metrics(root / "dataset", identifier, as_of)),
        json_out,
    )


@app.command()
def fees(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    as_of: Annotated[str, typer.Option(
        help="quarterly period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """FONDTRIM fee block for one share class — percentages, verbatim."""
    root = data_dir or _data_dir()
    _emit(
        _run(lambda: quarterly_fees(root / "dataset", identifier, as_of)),
        json_out,
    )


@app.command(name="official-returns")
def official_returns_cmd(
    identifier: Annotated[str, typer.Argument(
        help="Share-class ISIN or key FI:<reg>:<comp>:<clase>")],
    from_period: Annotated[str | None, typer.Option(
        "--from", help="period YYYY-MM")] = None,
    to_period: Annotated[str | None, typer.Option(
        "--to", help="period YYYY-MM")] = None,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Official CNMV non-annualized return series — verbatim, never
    recomputed."""
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: official_returns(
        root / "dataset", identifier, from_period, to_period))
    _emit({"resolution": meta, "observations": rows}, json_out)


@app.command()
def allocation(
    identifier: Annotated[str, typer.Argument(
        help="Fund/compartment key or share-class ISIN")],
    as_of: Annotated[str, typer.Option(
        help="period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """FONDPATRIMDISVAR patrimony stock + flow rows per compartment.

    Monetary fields in the IIC currency are kept rigidly apart from
    signed percentage flows over average daily patrimonio.
    """
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: patrimony_allocation(
        root / "dataset", identifier, as_of))
    _emit({"resolution": meta, "compartments_rows": rows}, json_out)


@app.command()
def derivatives(
    identifier: Annotated[str, typer.Argument(
        help="Fund/compartment key or share-class ISIN")],
    as_of: Annotated[str, typer.Option(
        help="period YYYY-MM")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """FONDDERI derivative operations per compartment — verbatim
    evidence, never normalized."""
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: derivative_operations(
        root / "dataset", identifier, as_of))
    _emit({"resolution": meta, "compartments_rows": rows}, json_out)


@app.command(name="portfolio-diff")
def portfolio_diff_cmd(
    identifier: Annotated[str, typer.Argument(
        help="Fund/compartment key or share-class ISIN")],
    from_period: Annotated[str | None, typer.Argument(
        help="earlier snapshot YYYY-MM")] = None,
    to_period: Annotated[str | None, typer.Argument(
        help="later snapshot YYYY-MM")] = None,
    as_of: Annotated[str | None, typer.Option(
        help="later snapshot YYYY-MM (with --previous)")] = None,
    previous: Annotated[bool, typer.Option(
        "--previous-loaded", "--previous",
        help="compare to the owner's previous LOADED snapshot "
             "(publication_cadence=adjacent_available_snapshots); "
             "fails with previous_published_snapshot_not_loaded if a "
             "measured published snapshot is not in the dataset. "
             "--previous is an alias — a future flag may instead "
             "auto-resolve the previous PUBLISHED snapshot")] = False,
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compare two published FONDCART snapshots — a change ledger.

    "added"/"removed" describe snapshot presence, NEVER purchases or
    sales. Ambiguous identifier groups are reported unresolved, never
    paired by heuristic.
    """
    root = data_dir or _data_dir()
    if as_of is not None:
        if not previous:
            raise CnmvIicError("--as-of requires --previous")
        if from_period is not None or to_period is not None:
            raise CnmvIicError(
                "positional periods and --as-of are mutually exclusive")
        to, frm, prev = as_of, None, True
    else:
        if previous:
            raise CnmvIicError("--previous requires --as-of")
        if from_period is None or to_period is None:
            raise CnmvIicError(
                "usage: portfolio-diff IDENT FROM TO  or  "
                "portfolio-diff IDENT --as-of YYYY-MM --previous")
        to, frm, prev = to_period, from_period, False
    meta, rows = _run(lambda: portfolio_diff(
        root / "dataset", identifier, frm, to, previous=prev))
    _emit({"resolution": meta, "compartments_rows": rows}, json_out)


@app.command(name="position-history")
def position_history_cmd(
    identifier: Annotated[str, typer.Argument(
        help="Fund/compartment key or share-class ISIN")],
    isin: Annotated[str, typer.Argument(
        help="position identifier (verbatim ISIN)")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reported market-value history of an identifier — REPORTED
    values, never a buy/sell history."""
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: position_history(
        root / "dataset", identifier, isin))
    _emit({"resolution": meta, "compartments_rows": rows}, json_out)


@app.command(name="portfolio-history")
def portfolio_history_cmd(
    identifier: Annotated[str, typer.Argument(
        help="Fund/compartment key or share-class ISIN")],
    data_dir: Annotated[Path | None, typer.Option()] = None,
    json_out: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Per-snapshot reported position counts and totals — observed
    aggregates only."""
    root = data_dir or _data_dir()
    meta, rows = _run(lambda: portfolio_history(
        root / "dataset", identifier))
    _emit({"resolution": meta, "compartments_rows": rows}, json_out)


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
