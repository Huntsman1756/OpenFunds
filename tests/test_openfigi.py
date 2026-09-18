"""G7-D — OpenFIGI instrument evidence: transport + extraction ledger."""

from __future__ import annotations

import json

import pytest

from cnmv_iic.errors import ParseError
from cnmv_iic.openfigi_client import (
    HttpResult,
    RateLimiter,
    iter_campaign,
    plan_batches,
    read_batch,
    run_campaign,
)
from cnmv_iic.provider_ingest import ingest_openfigi
from cnmv_iic.query import instrument_evidence
from tests.test_resolution_gleif import ISIN_A, ISIN_B, ISIN_C, _positions

RETRIEVED = "2026-09-18T12:00:00+00:00"

ROW_SINGLE = {
    "figi": "BBG000B9XRY4", "name": "APPLE INC", "ticker": "AAPL",
    "exchCode": "US", "compositeFIGI": "BBG000B9XRY4",
    "securityType": "Common Stock", "marketSector": "Equity",
    "securityType2": "Common Stock", "securityDescription": "AAPL"}
ROW_VENUE1 = {
    "figi": "BBG000QF76F0", "name": "POLO CAPITAL", "ticker": "SL018",
    "exchCode": "SM", "compositeFIGI": "BBG000QF76F0",
    "securityType": "Open-End Fund", "marketSector": "Equity",
    "shareClassFIGI": "BBG001SS3JK8", "securityType2": "Mutual Fund",
    "securityDescription": "SL018"}
ROW_VENUE2 = {
    "figi": "BBG004N7CSV1", "name": "POLO CAPITAL", "ticker": "SL018",
    "exchCode": "SQ", "compositeFIGI": "BBG000QF76F0",
    "securityType": "Open-End Fund", "marketSector": "Equity",
    "shareClassFIGI": "BBG001SS3JK8", "securityType2": "Mutual Fund",
    "securityDescription": "SL018"}


class FakePoster:
    """Deterministic in-memory /v3/mapping: handler sees the jobs list."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[list[dict]] = []

    def post(self, url, payload, headers):
        jobs = json.loads(payload)
        self.calls.append(jobs)
        return self.handler(jobs, len(self.calls))


def _limiter():
    return RateLimiter(0.0, sleep=lambda _s: None)


def _ok(results_by_isin: dict[str, object]):
    def handler(jobs, _n):
        body = [results_by_isin.get(j["idValue"],
                                    {"warning": "No identifier found."})
                for j in jobs]
        return HttpResult(200, {}, json.dumps(body).encode())
    return handler


def _campaign(tmp_path, isins, handler, batch_size=10,
              name="2026-09-18"):
    bdir = tmp_path / "dataset" / "provider_raw" / "openfigi" / name / "batches"
    outcomes = run_campaign(
        bdir, isins, poster=FakePoster(handler), limiter=_limiter(),
        batch_size=batch_size, retrieved_at=lambda: RETRIEVED)
    return bdir.parent, outcomes


# ---------------------------------------------------------------------------
# transport
# ---------------------------------------------------------------------------

def test_plan_batches_deterministic():
    b1 = plan_batches([ISIN_C, ISIN_A, ISIN_B], 2)
    b2 = plan_batches([ISIN_B, ISIN_C, ISIN_A], 2)
    assert b1 == b2                                # order-independent
    assert [b.isins for b in b1] == [
        (ISIN_B, ISIN_A), (ISIN_C,)]               # sorted + chunked
    assert all(len(b.batch_id) == 64 for b in b1)


def test_campaign_stores_and_resume_skips(tmp_path):
    isins = [ISIN_A, ISIN_B, ISIN_C]
    poster = FakePoster(_ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    bdir = tmp_path / "c" / "batches"
    r1 = run_campaign(bdir, isins, poster=poster, limiter=_limiter(),
                      batch_size=10, retrieved_at=lambda: RETRIEVED)
    assert [o.status for o in r1] == ["stored"]
    assert len(poster.calls) == 1                  # one HTTP request
    r2 = run_campaign(bdir, isins, poster=poster, limiter=_limiter(),
                      batch_size=10, retrieved_at=lambda: RETRIEVED)
    assert [o.status for o in r2] == ["skipped"]
    assert len(poster.calls) == 1                  # nothing re-requested
    batches = iter_campaign(bdir)
    assert len(batches) == 1
    assert batches[0].request_jobs[0]["idType"] == "ID_ISIN"
    assert batches[0].meta["response_sha256"]


def test_retry_429_then_success(tmp_path):
    attempts = []

    def handler(jobs, n):
        attempts.append(n)
        if n == 1:
            return HttpResult(429, {"ratelimit-reset": "0"}, b"")
        return HttpResult(200, {}, json.dumps(
            [{"data": [ROW_SINGLE]} for _ in jobs]).encode())

    bdir, outcomes = _campaign(
        tmp_path, [ISIN_A], handler, name="2026-09-18")
    assert outcomes[0].status == "stored"
    assert attempts == [1, 2]                      # retried once


def test_retry_exhausted_is_bounded(tmp_path):
    def handler(jobs, n):
        return HttpResult(503, {}, b"")

    poster = FakePoster(handler)
    bdir = tmp_path / "c" / "batches"
    outcomes = run_campaign(
        bdir, [ISIN_A], poster=poster, limiter=_limiter(),
        batch_size=10, retrieved_at=lambda: RETRIEVED)
    assert outcomes[0].status == "failed"
    assert outcomes[0].detail == "retry_exhausted"
    assert len(poster.calls) == 6                  # bounded attempts
    assert list(bdir.glob("*.zip")) == []          # nothing stored


def test_transport_error_retried_not_fatal(tmp_path):
    """URLError/timeout on attempt 1 must not abort the campaign."""
    from cnmv_iic.errors import AcquisitionError

    def handler(jobs, n):
        if n == 1:
            raise AcquisitionError("conn reset")
        return HttpResult(200, {}, json.dumps(
            [{"data": [ROW_SINGLE]} for _ in jobs]).encode())

    _bdir, outcomes = _campaign(tmp_path, [ISIN_A], handler)
    assert outcomes[0].status == "stored"


def test_transport_error_exhausted_is_failed_not_fatal(tmp_path):
    from cnmv_iic.errors import AcquisitionError

    def handler(jobs, n):
        raise AcquisitionError("timeout")

    _bdir, outcomes = _campaign(tmp_path, [ISIN_A], handler)
    assert outcomes[0].status == "failed"
    assert "transport_error" in outcomes[0].detail


def test_cardinality_mismatch_rejected(tmp_path):
    def handler(jobs, n):
        return HttpResult(200, {}, json.dumps(
            [{"data": []}]).encode())              # 1 result for 2 jobs

    _bdir, outcomes = _campaign(
        tmp_path, [ISIN_A, ISIN_B], handler, batch_size=2)
    assert outcomes[0].status == "failed"
    assert "cardinality_mismatch" in outcomes[0].detail


def test_read_batch_tamper_detected(tmp_path):
    bdir, _ = _campaign(
        tmp_path, [ISIN_A], _ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    # rewrite meta with a different batch_id -> fail closed
    import zipfile
    path = next(bdir.glob("batches/*.zip"))
    meta = json.loads(zipfile.ZipFile(path).read("meta.json"))
    meta["batch_id"] = "0" * 64
    import io
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in ("request.json", "response.json"):
            zf.writestr(n, zipfile.ZipFile(path).read(n))
        zf.writestr("meta.json", json.dumps(meta))
    path.write_bytes(buf.getvalue())
    with pytest.raises(ParseError, match="batch_id mismatch"):
        read_batch(path)


# ---------------------------------------------------------------------------
# extraction + evidence tables
# ---------------------------------------------------------------------------

def _full_campaign(artifact, tmp_path, name="2026-09-18",
                   handler=None):
    _positions(artifact, tmp_path)
    handler = handler or _ok({
        ISIN_A: {"data": [ROW_SINGLE]},
        ISIN_B: {"data": [ROW_VENUE1, ROW_VENUE2]},
        ISIN_C: {"warning": "No identifier found."}})
    bdir, _ = _campaign(
        tmp_path, [ISIN_A, ISIN_B, ISIN_C], handler, name=name)
    return bdir


def test_states_and_candidates(artifact, tmp_path):
    cdir = _full_campaign(artifact, tmp_path)
    res = ingest_openfigi(tmp_path / "dataset", cdir)
    assert res.observations == 3
    assert res.matched_single == 1
    assert res.matched_multi == 1
    assert res.no_match == 1
    assert res.candidates == 3                     # 1 + 2 venue rows
    ev = instrument_evidence(tmp_path / "dataset", ISIN_B)
    obs = ev["observations"][0]
    assert obs["state"] == "matched_multi"
    assert obs["campaign"] == "2026-09-18"
    assert obs["temporal_semantics"] == (
        "current_api_enrichment_of_historical_security")
    assert obs["batch_id"] and obs["response_sha256"]
    rows = obs["results"]
    assert [r["exch_code"] for r in rows] == ["SM", "SQ"]
    # venue figis differ; composite + share-class preserved verbatim
    assert rows[0]["figi"] != rows[1]["figi"]
    assert {r["composite_figi"] for r in rows} == {"BBG000QF76F0"}
    assert {r["share_class_figi"] for r in rows} == {"BBG001SS3JK8"}
    assert all("#job=" in r["provider_record_locator"]
               and "/data=" in r["provider_record_locator"] for r in rows)


def test_missing_job_is_provider_error(artifact, tmp_path):
    _positions(artifact, tmp_path)
    # campaign only fetched ISIN_A — ISIN_B/C jobs absent
    bdir, _ = _campaign(
        tmp_path, [ISIN_A], _ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    res = ingest_openfigi(tmp_path / "dataset", bdir)
    assert res.provider_error == 2                 # visible, not skipped
    ev = instrument_evidence(tmp_path / "dataset", ISIN_C)
    assert ev["observations"][0]["state"] == "provider_error"


def test_error_payload_is_provider_error(artifact, tmp_path):
    _positions(artifact, tmp_path)
    bdir, _ = _campaign(
        tmp_path, [ISIN_A, ISIN_B, ISIN_C],
        _ok({ISIN_A: {"error": "TIMEOUT"}}))
    res = ingest_openfigi(tmp_path / "dataset", bdir)
    assert res.provider_error == 1
    assert res.no_match == 2                       # others -> warning


def test_invalid_response_shape(artifact, tmp_path):
    _positions(artifact, tmp_path)
    bdir, _ = _campaign(
        tmp_path, [ISIN_A, ISIN_B, ISIN_C],
        _ok({ISIN_A: {"something": "else"},
             ISIN_B: {"data": "not-a-list"}}))
    res = ingest_openfigi(tmp_path / "dataset", bdir)
    assert res.invalid_response == 2


def test_export_deterministic(artifact, tmp_path):
    cdir = _full_campaign(artifact, tmp_path)
    r1 = ingest_openfigi(tmp_path / "dataset", cdir)
    r2 = ingest_openfigi(tmp_path / "dataset", cdir)
    assert r1.instrument_fingerprint == r2.instrument_fingerprint
    assert r1.instrument_fingerprint


def test_new_campaign_appends(artifact, tmp_path):
    _full_campaign(artifact, tmp_path, name="2026-09-18")
    _full_campaign(artifact, tmp_path, name="2026-09-19",
                   handler=_ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    for c in ("2026-09-18", "2026-09-19"):
        ingest_openfigi(
            tmp_path / "dataset",
            tmp_path / "dataset/provider_raw/openfigi" / c)
    import duckdb
    con = duckdb.connect()
    glob = str(tmp_path / "dataset" / "instrument_observations"
               / "provider=*" / "retrieval=*" / "part-0.parquet")
    n = con.execute(
        "SELECT count(DISTINCT retrieval) FROM read_parquet(?, "
        "hive_partitioning=true)", [glob]).fetchone()[0]
    assert n == 2                                  # append-only


def test_prior_evidence_intact(artifact, tmp_path):
    cdir = _full_campaign(artifact, tmp_path)
    mpath = (tmp_path / "dataset" / "manifests" / "2025-12.json")
    before = mpath.read_text()
    ingest_openfigi(tmp_path / "dataset", cdir)
    assert mpath.read_text() == before
