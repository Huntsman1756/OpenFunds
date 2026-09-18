"""OpenFIGI instrument-evidence extraction (G7-D2).

Input: stored campaign batch artifacts written by
``cnmv_iic.openfigi_client`` — raw request/response JSON per batch,
never re-fetched. Extraction is a pure local function of the stored
bytes, so re-running it over the same campaign is byte-deterministic.

Semantics (docs/g7/contract.md):

- instrument domain, NOT issuer resolution: candidates are OpenFIGI
  result rows, never LEIs.
- per-job payload shapes: ``{"data": [...]}`` -> matched_single /
  matched_multi by cardinality; ``{"warning": ...}`` -> no_match;
  ``{"error": ...}`` -> provider_error; anything else ->
  invalid_response. No result row is ever silently discarded.
- ``matched_multi`` is not ambiguity: venue FIGIs under one
  composite/share-class FIGI are normal — all rows are preserved
  verbatim with their position in the provider's data array.
- every job must map back to its request ISIN positionally; a batch
  whose response cardinality differs from its request was already
  rejected at acquisition time, and ``read_batch`` re-verifies it.
"""

from __future__ import annotations

import json

from cnmv_iic.domain import (
    TEMPORAL_SEMANTICS_API,
    InstrumentCandidate,
    InstrumentObservation,
    InstrumentState,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.openfigi_client import PROVIDER, PROVIDER_DATASET, StoredBatch

PARSER = "cnmv_iic.adapters.openfigi"
PARSER_VERSION = "1"

_RESULT_FIELDS = (
    "figi", "name", "ticker", "exchCode", "compositeFIGI",
    "securityType", "marketSector", "shareClassFIGI",
    "securityType2", "securityDescription",
)


def _job_state(payload: object) -> tuple[InstrumentState, list]:
    """Classify one per-job response payload; returns (state, rows)."""
    if not isinstance(payload, dict):
        return InstrumentState.INVALID_RESPONSE, []
    if "data" in payload:
        data = payload["data"]
        if not isinstance(data, list):
            return InstrumentState.INVALID_RESPONSE, []
        if not all(isinstance(r, dict) for r in data):
            return InstrumentState.INVALID_RESPONSE, []
        if len(data) == 0:
            return InstrumentState.INVALID_RESPONSE, []
        return (InstrumentState.MATCHED_SINGLE if len(data) == 1
                else InstrumentState.MATCHED_MULTI), data
    if "warning" in payload:
        return InstrumentState.NO_MATCH, []
    if "error" in payload:
        return InstrumentState.PROVIDER_ERROR, []
    return InstrumentState.INVALID_RESPONSE, []


def build_observations(
    universe: dict[str, tuple[str, ...]],
    batches: list[StoredBatch],
    *,
    campaign: str,
) -> tuple[list[InstrumentObservation], list[InstrumentCandidate]]:
    """Join the corpus ISIN universe against stored batch responses.

    Every universe ISIN produces exactly one observation; ISINs whose
    job is absent from all stored batches become ``provider_error``
    (the batch failed or has not been fetched) — never silently
    skipped (gate 25).
    """
    # isin -> (batch, job_index_1based, payload)
    jobs: dict[str, tuple[StoredBatch, int, object]] = {}
    for batch in batches:
        for i, (job, payload) in enumerate(
                zip(batch.request_jobs, batch.response, strict=True),
                start=1):
            isin = job.get("idValue")
            if not isinstance(isin, str):
                raise ParseError(
                    f"batch {batch.batch_id}: job {i} has no idValue")
            if job.get("idType") != "ID_ISIN":
                raise ParseError(
                    f"batch {batch.batch_id}: job {i} idType "
                    f"{job.get('idType')!r} != 'ID_ISIN'")
            if isin in jobs:
                raise ParseError(
                    f"ISIN {isin} mapped by two jobs — batch "
                    f"{batch.batch_id} duplicates a request")
            jobs[isin] = (batch, i, payload)

    observations: list[InstrumentObservation] = []
    candidates: list[InstrumentCandidate] = []
    for isin in sorted(universe):
        obs_id = f"{PROVIDER}/{campaign}/{isin}"
        found = jobs.get(isin)
        if found is None:
            observations.append(InstrumentObservation(
                observation_id=obs_id, isin=isin, provider=PROVIDER,
                provider_dataset=PROVIDER_DATASET, campaign=campaign,
                state=InstrumentState.PROVIDER_ERROR, result_count=0,
                holding_periods=universe[isin],
                temporal_semantics=TEMPORAL_SEMANTICS_API,
                retrieved_at="", batch_id="", batch_job_index=0,
                request_sha256="", response_sha256="",
                parser=PARSER, parser_version=PARSER_VERSION))
            continue
        batch, job_idx, payload = found
        state, rows = _job_state(payload)
        observations.append(InstrumentObservation(
            observation_id=obs_id, isin=isin, provider=PROVIDER,
            provider_dataset=PROVIDER_DATASET, campaign=campaign,
            state=state, result_count=len(rows),
            holding_periods=universe[isin],
            temporal_semantics=TEMPORAL_SEMANTICS_API,
            retrieved_at=batch.meta["retrieved_at"],
            batch_id=batch.batch_id, batch_job_index=job_idx,
            request_sha256=batch.meta["request_sha256"],
            response_sha256=batch.meta["response_sha256"],
            parser=PARSER, parser_version=PARSER_VERSION))
        for j, row in enumerate(rows, start=1):
            candidates.append(InstrumentCandidate(
                observation_id=obs_id, result_index=j,
                figi=_opt(row.get("figi")),
                composite_figi=_opt(row.get("compositeFIGI")),
                share_class_figi=_opt(row.get("shareClassFIGI")),
                name=_opt(row.get("name")),
                ticker=_opt(row.get("ticker")),
                exch_code=_opt(row.get("exchCode")),
                security_type=_opt(row.get("securityType")),
                security_type2=_opt(row.get("securityType2")),
                market_sector=_opt(row.get("marketSector")),
                security_description=_opt(
                    row.get("securityDescription")),
                provider_record_locator=(
                    f"{batch.batch_id}#job={job_idx}/data={j}"),
                raw_json=json.dumps(row, sort_keys=True)))
    return observations, candidates


def _opt(v: object) -> str | None:
    return v if isinstance(v, str) and v else (
        str(v) if v is not None else None)
