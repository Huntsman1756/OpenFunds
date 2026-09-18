"""OpenFIGI /v3/mapping transport (G7-D1).

Reproducible batched acquisition, not a thin API wrapper:

- deterministic batch composition: valid ISINs sorted lexicographically
  and chunked; ``batch_id = sha256(endpoint + ordered jobs)`` so a
  batch is fully described by its content
- raw evidence: every POST's request/response bytes are stored in a
  content-addressed ZIP (``request.json`` / ``response.json`` /
  ``meta.json``) under ``provider_raw/openfigi/<campaign>/batches/``
- checkpoint/resume: an existing batch artifact means the request was
  already performed — resuming never repeats it; a deliberate future
  re-acquisition uses a NEW campaign dir (append-only, gate 20)
- positional cardinality: OpenFIGI answers jobs in request order —
  ``len(response) == len(request)`` is validated fail-closed
- rate limits: paced from the documented anonymous limit and the
  ``ratelimit-*`` response headers; HTTP 429 waits the reset window,
  5xx uses bounded exponential backoff — never an unbounded retry loop

The API key is optional (env ``OPENFIGI_API_KEY`` only — never written
to files, logs, or manifests). It changes throughput/batch size, never
semantics.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol

from cnmv_iic.errors import AcquisitionError, ParseError

ENDPOINT = "https://api.openfigi.com/v3/mapping"
PROVIDER = "openfigi"
PROVIDER_DATASET = "openfigi-mapping-v3"
CLIENT = "cnmv_iic.openfigi_client"
CLIENT_VERSION = "1"

# documented limits (api.openfigi.com): anonymous 10 jobs/request and
# 25 requests/minute; with key 100 jobs/request and 25 requests/6s
BATCH_SIZE_ANON = 10
BATCH_SIZE_KEY = 100
_ANON_MIN_INTERVAL = 60.0 / 25      # seconds between requests, no key
_KEY_MIN_INTERVAL = 6.0 / 25        # seconds between requests, with key
_MAX_ATTEMPTS = 6                   # bounded: no infinite retry loops


@dataclass(frozen=True)
class PlannedBatch:
    """One deterministic unit of acquisition."""

    batch_id: str            # sha256 over endpoint + ordered jobs
    index: int               # 0-based position in the campaign
    isins: tuple[str, ...]


def plan_batches(
    isins: list[str] | tuple[str, ...], batch_size: int
) -> tuple[PlannedBatch, ...]:
    """Sort ISINs and chunk them into deterministic batches."""
    ordered = sorted(isins)
    out = []
    for i in range(0, len(ordered), batch_size):
        chunk = tuple(ordered[i : i + batch_size])
        bid = sha256(
            ("openfigi/v3/mapping\n" + "\n".join(chunk)).encode("utf-8")
        ).hexdigest()
        out.append(PlannedBatch(batch_id=bid, index=i // batch_size,
                                isins=chunk))
    return tuple(out)


def jobs_for(isins: tuple[str, ...]) -> list[dict]:
    return [{"idType": "ID_ISIN", "idValue": s} for s in isins]


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes


class Poster(Protocol):
    """Injectable HTTP POST for tests; production uses UrllibPoster."""

    def post(self, url: str, payload: bytes,
             headers: dict[str, str]) -> HttpResult: ...


class UrllibPoster:
    def __init__(self, api_key: str | None = None, timeout: float = 60.0):
        self._api_key = api_key
        self._timeout = timeout

    def post(self, url: str, payload: bytes,
             headers: dict[str, str]) -> HttpResult:
        if os.environ.get("CNMV_IIC_OFFLINE"):
            raise AcquisitionError(
                "CNMV_IIC_OFFLINE is set — network requests are "
                "forbidden; rebuild derived data from stored raw "
                "artifacts instead")
        if not url.startswith("https://api.openfigi.com/"):
            raise AcquisitionError(
                f"URL outside OpenFIGI origin rejected: {url}")
        h = {"Content-Type": "application/json",
             "User-Agent": "cnmv-iic"}
        if self._api_key:
            h["X-OPENFIGI-APIKEY"] = self._api_key
        h.update(headers)
        req = urllib.request.Request(  # noqa: S310 — origin allowlisted
            url, data=payload, headers=h)
        try:
            with urllib.request.urlopen(  # noqa: S310 — allowlisted
                    req, timeout=self._timeout) as r:
                return HttpResult(r.status, dict(r.headers), r.read())
        except urllib.error.HTTPError as e:
            return HttpResult(e.code, dict(e.headers), e.read())
        except urllib.error.URLError as e:
            raise AcquisitionError(f"openfigi transport error: {e}") from e


class RateLimiter:
    """Pace requests from documented limits + ratelimit-* headers."""

    def __init__(self, min_interval: float,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self._interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last = 0.0

    def wait(self) -> None:
        gap = self._clock() - self._last
        if gap < self._interval:
            self._sleep(self._interval - gap)
        self._last = self._clock()

    def backoff(self, result: HttpResult, attempt: int) -> None:
        """429 -> wait the declared reset window; 5xx -> exp backoff."""
        lowered = {k.lower(): v for k, v in result.headers.items()}
        reset = (lowered.get("ratelimit-reset")
                 or lowered.get("retry-after"))
        try:
            wait = float(reset) if reset is not None else 0.0
        except ValueError:
            wait = 0.0
        if result.status == 429:
            self._sleep(max(wait, self._interval * (attempt + 1)))
        else:  # 5xx
            self._sleep(max(wait, min(2.0 ** attempt, 60.0)))


def _write_batch_zip(path: Path, batch: PlannedBatch, request: bytes,
                     result: HttpResult, retrieved_at: str) -> None:
    """Store request/response/meta as an immutable batch artifact."""
    meta = {
        "batch_id": batch.batch_id,
        "batch_index": batch.index,
        "endpoint": ENDPOINT,
        "isins": list(batch.isins),
        "request_sha256": sha256(request).hexdigest(),
        "response_sha256": sha256(result.body).hexdigest(),
        "http_status": result.status,
        "response_headers": {
            k: v for k, v in result.headers.items()
            if k.lower().startswith("ratelimit")
            or k.lower() in ("retry-after", "content-type")},
        "retrieved_at": retrieved_at,
        "client": CLIENT,
        "client_version": CLIENT_VERSION,
    }
    # deterministic zip bytes: fixed date_time so identical content
    # produces identical sha256
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in (("request.json", request),
                           ("response.json", result.body),
                           ("meta.json", json.dumps(
                               meta, indent=1, sort_keys=True).encode())):
            zi = zipfile.ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zf.writestr(zi, data)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(buf.getvalue())
    tmp.replace(path)


@dataclass(frozen=True)
class BatchOutcome:
    batch: PlannedBatch
    status: str          # stored | skipped | failed
    detail: str


def run_campaign(
    batches_dir: Path | str,
    isins: list[str] | tuple[str, ...],
    *,
    poster: Poster,
    limiter: RateLimiter,
    batch_size: int = BATCH_SIZE_ANON,
    retrieved_at: Callable[[], str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[BatchOutcome]:
    """Fetch every planned batch once; existing artifacts are skipped.

    ``retrieved_at``: callable returning an ISO-8601 string (injected
    so tests are deterministic). ``on_progress(done, total)`` optional.
    """
    batches_dir = Path(batches_dir)
    batches_dir.mkdir(parents=True, exist_ok=True)
    planned = plan_batches(isins, batch_size)
    outcomes: list[BatchOutcome] = []
    for n, batch in enumerate(planned, start=1):
        path = batches_dir / f"{batch.batch_id}.zip"
        if path.exists():
            outcomes.append(BatchOutcome(batch, "skipped", ""))
            if on_progress:
                on_progress(n, len(planned))
            continue
        request = json.dumps(jobs_for(batch.isins)).encode("utf-8")
        result: HttpResult | None = None
        error = ""
        for attempt in range(_MAX_ATTEMPTS):
            limiter.wait()
            try:
                result = poster.post(ENDPOINT, request, {})
            except AcquisitionError as e:
                # transport-level failure (timeout, conn reset) —
                # retriable like 5xx, never aborts the campaign
                result = None
                if attempt == _MAX_ATTEMPTS - 1:
                    error = f"transport_error: {e}"
                    break
                limiter.backoff(
                    HttpResult(503, {}, b""), attempt)
                continue
            if result.status == 200:
                break
            if result.status in (429, 500, 502, 503, 504):
                limiter.backoff(result, attempt)
                continue
            error = f"http_{result.status}"
            break
        else:
            result = None
            error = "retry_exhausted"
        if result is not None and result.status == 200:
            try:
                body = json.loads(result.body)
            except json.JSONDecodeError:
                error = "invalid_response_body"
            else:
                if not isinstance(body, list) or len(body) != len(
                        batch.isins):
                    error = ("cardinality_mismatch: "
                             f"{len(body) if isinstance(body, list) else 'non-list'}"
                             f" results for {len(batch.isins)} jobs")
                else:
                    _write_batch_zip(path, batch, request, result,
                                     retrieved_at())
                    outcomes.append(BatchOutcome(batch, "stored", ""))
        if result is None or error:
            outcomes.append(BatchOutcome(batch, "failed", error))
        if on_progress:
            on_progress(n, len(planned))
    return outcomes


@dataclass(frozen=True)
class StoredBatch:
    """A batch artifact read back from disk."""

    batch_id: str
    meta: dict
    request_jobs: list[dict]
    response: list


def read_batch(path: Path | str) -> StoredBatch:
    """Re-verify a stored batch artifact — the evidence is only
    trustworthy if every byte matches what was pinned at write time.

    Fail-closed on: truncated/not-a-zip, missing or duplicated members,
    batch_id mismatch, request/response sha256 mismatch, reordered or
    altered jobs vs meta.isins, response cardinality mismatch, and
    missing HTTP metadata (status, retrieved_at)."""
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if len(names) != len(set(names)):
                raise ParseError(
                    f"batch artifact {path.name}: duplicated member")
            raw_request = zf.read("request.json")
            raw_response = zf.read("response.json")
            raw_meta = zf.read("meta.json")
    except KeyError as e:
        raise ParseError(
            f"batch artifact {path.name}: missing member {e}") from e
    meta = json.loads(raw_meta)
    request = json.loads(raw_request)
    response = json.loads(raw_response)
    if meta.get("batch_id") != path.stem:
        raise ParseError(
            f"batch artifact {path.name}: meta batch_id mismatch")
    if meta.get("request_sha256") != sha256(raw_request).hexdigest():
        raise ParseError(
            f"batch artifact {path.name}: request sha256 mismatch")
    if meta.get("response_sha256") != sha256(raw_response).hexdigest():
        raise ParseError(
            f"batch artifact {path.name}: response sha256 mismatch")
    if meta.get("http_status") is None or meta.get("retrieved_at") is None:
        raise ParseError(
            f"batch artifact {path.name}: missing HTTP metadata")
    if (isinstance(meta.get("isins"), list)
            and meta["isins"] != [j.get("idValue") for j in request]):
        raise ParseError(
            f"batch artifact {path.name}: "
            "request jobs do not match meta.isins")
    if not isinstance(response, list) or len(response) != len(request):
        raise ParseError(
            f"batch artifact {path.name}: "
            f"{len(response)} results for {len(request)} jobs")
    return StoredBatch(batch_id=meta["batch_id"], meta=meta,
                       request_jobs=request, response=response)


def iter_campaign(batches_dir: Path | str) -> list[StoredBatch]:
    """Read all stored batch artifacts, ordered by batch_index."""
    batches_dir = Path(batches_dir)
    stored = [read_batch(p) for p in sorted(batches_dir.glob("*.zip"))]
    return sorted(stored, key=lambda b: b.meta["batch_index"])
