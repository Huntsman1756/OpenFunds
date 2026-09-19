"""G9-B — lifecycle source-assertion ledger orchestration.

Acquisition writes immutable blob artifacts (weekly bulletin PDFs, HR
history/search pages) into the shared ``ArtifactStore`` under dedicated
source families. Export is a pure local function: artifacts -> source
documents -> source observations -> assertions -> candidate links ->
partitioned parquet + deterministic fingerprints. The only networked
step is acquisition; export runs fully offline.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from cnmv_iic.acquisition.weekly import (
    WEEKLY_PAGE,
    WeeklyBulletinClient,
    WeekOption,
)
from cnmv_iic.adapters.weekly_registry import (
    PARSER as WEEKLY_PARSER,
)
from cnmv_iic.adapters.weekly_registry import (
    PARSER_VERSION as WEEKLY_PARSER_VERSION,
)
from cnmv_iic.adapters.weekly_registry import (
    bulletin_assertions,
    parse_registry_document,
)
from cnmv_iic.artifacts.store import ArtifactStore, SourceArtifact
from cnmv_iic.errors import CnmvIicError
from cnmv_iic.lifecycle import (
    RULE_VERSION,
    DisappearanceCandidate,
    IdentityState,
    LifecycleAssertion,
    LifecycleSourceDocument,
    LifecycleSourceObservation,
    SourceFamily,
    make_assertion_id,
    make_candidate_id,
    make_source_document_id,
    make_source_observation_id,
)

WEEKLY_FAMILY = SourceFamily.WEEKLY_REGISTRY.value
HR_FAMILY = SourceFamily.RELEVANT_INFORMATION.value
WEEKLY_PREFIX = "cnmv-weekly-registry"
HR_PREFIX = "cnmv-iic-relevant-information"


# ---------------------------------------------------------------------------
# Observational candidates (G9-A grain, reproduced in production)
# ---------------------------------------------------------------------------


def _month_seq(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[5:])
    y2, m2 = int(b[:4]), int(b[5:])
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def disappearance_candidates(
        dataset_root: Path | str) -> list[DisappearanceCandidate]:
    """Contiguous adjacent-period fund-key diffs — same deterministic
    candidate_id as the G9-A2 measurement."""
    root = Path(dataset_root)
    con = duckdb.connect(database=":memory:")
    glob = str(root / "funds" / "period=*" / "*.parquet")
    funds = con.execute(  # noqa: S608 — local glob path, no user input
        f"SELECT period, fund_key, entity_type, numero_registro,"
        f" denominacion, gestora_numero_registro, source_artifact_id,"
        f" xml_locator FROM read_parquet('{glob}',"
        f" hive_partitioning=true)").fetchall()
    by_period: dict[str, set[str]] = {}
    row_at: dict[tuple[str, str], tuple] = {}
    presence: dict[str, list[str]] = {}
    for r in funds:
        period, key = r[0], r[1]
        by_period.setdefault(period, set()).add(key)
        row_at[(period, key)] = r
        presence.setdefault(key, []).append(period)
    periods = sorted(by_period)
    out: list[DisappearanceCandidate] = []
    for prev, curr in zip(periods, periods[1:], strict=False):
        if len(_month_seq(prev, curr)) != 2:
            continue  # non-contiguous: preserve observed bounds only
        for key in sorted(by_period[prev] - by_period[curr]):
            r = row_at[(prev, key)]
            out.append(DisappearanceCandidate(
                candidate_id=make_candidate_id(
                    "FUND_DISAPPEARED", key, prev, curr),
                candidate_type="FUND_DISAPPEARED",
                entity_key=key,
                previous_observed_period=prev,
                current_observed_period=curr,
                last_observed_present=prev,
                first_observed_absent=curr,
                previous_artifact_id=r[6],
                previous_locator=r[7],
                entity_type=r[2],
                denominacion=r[4],
                manager_register_number=r[5],
                lifespan_months=sum(1 for p in presence[key] if p <= prev),
            ))
    return out


def holdout_ids(manifest_path: Path | str) -> set[str]:
    m = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return {e["candidate_id"] for e in m["entries"]}


# ---------------------------------------------------------------------------
# Weekly bulletin acquisition
# ---------------------------------------------------------------------------


def _week_key(week_id: str, role: str) -> str:
    return f"{week_id}/{role}"


def _weeks_in_span(
        weeks: list[WeekOption], first: date, last: date
) -> list[WeekOption]:
    return [w for w in weeks if w.end >= first and w.start <= last]


@dataclass(frozen=True)
class WeekAcquireResult:
    week_id: str
    label: str | None
    status: str          # acquired | already_have | no_document | failed
    role: str | None
    artifact_id: str | None
    error: str | None = None


def acquire_weeks(
        store: ArtifactStore,
        dataset_root: Path | str,
        first: str,
        last: str,
        *,
        client: WeeklyBulletinClient | None = None,
        on_progress: object = None,
) -> dict:
    """Chronological, resumable weekly-bulletin acquisition.

    Per week in ``[first, last]`` (inclusive, YYYY-MM bounds widened to
    the containing weeks):
    - stored registro or boletin_completo artifact -> ``already_have``
      (0 network);
    - otherwise POST the selector, download ``lnkRegistro`` when
      present else ``lnkBoletinCompleto`` (general fallback, not a
      special case);
    - no document link -> store the selection page as evidence of the
      gap (role ``selection``, not parser-eligible);
    - per-week failures are isolated and reported.
    """
    client = client or WeeklyBulletinClient()
    first_d = date(int(first[:4]), int(first[5:]), 1)
    ly, lm = int(last[:4]), int(last[5:])
    last_d = date.fromordinal(
        date(ly + (lm == 12), lm % 12 + 1, 1).toordinal() - 1)
    weeks = _weeks_in_span(client.week_options(), first_d, last_d)

    index_path = Path(dataset_root) / "lifecycle" / "weekly_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    windex: dict = {}
    if index_path.exists():
        windex = json.loads(index_path.read_text(encoding="utf-8"))

    results: list[WeekAcquireResult] = []
    for i, w in enumerate(weeks):
        prior = (
            store.latest_for_period(
                _week_key(w.week_id, "registro"),
                source_family=WEEKLY_FAMILY)
            or store.latest_for_period(
                _week_key(w.week_id, "boletin_completo"),
                source_family=WEEKLY_FAMILY))
        if prior is not None and store.raw_path(prior).exists():
            results.append(WeekAcquireResult(
                week_id=w.week_id, label=w.label,
                status="already_have", role=prior.period.split("/")[1],
                artifact_id=prior.source_id))
            windex[w.week_id] = {
                "label": w.label, "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "role": prior.period.split("/")[1],
                "status": "already_have"}
            continue
        try:
            sel = client.select_week(w.week_id)
            role = "registro" if "registro" in sel.links else \
                "boletin_completo" if "boletin_completo" in sel.links \
                else None
            if role is None:
                artifact, _ = store.put_blob(
                    period=_week_key(w.week_id, "selection"),
                    source_page=WEEKLY_PAGE,
                    source_url=WEEKLY_PAGE,
                    content_type="text/html",
                    data=sel.raw_html.encode("utf-8"),
                    raw_suffix=".html",
                    retrieved_at=datetime.now(UTC),
                    source_family=WEEKLY_FAMILY,
                    source_id_prefix=WEEKLY_PREFIX)
                results.append(WeekAcquireResult(
                    week_id=w.week_id, label=w.label,
                    status="no_document", role="selection",
                    artifact_id=artifact.source_id))
            else:
                payload = client.fetch_document(sel.links[role])
                artifact, _ = store.put_blob(
                    period=_week_key(w.week_id, role),
                    source_page=WEEKLY_PAGE,
                    source_url=payload.url,
                    content_type=payload.content_type,
                    data=payload.data,
                    raw_suffix=".pdf",
                    retrieved_at=datetime.now(UTC),
                    source_family=WEEKLY_FAMILY,
                    source_id_prefix=WEEKLY_PREFIX)
                results.append(WeekAcquireResult(
                    week_id=w.week_id, label=w.label,
                    status="acquired", role=role,
                    artifact_id=artifact.source_id))
        except CnmvIicError as exc:
            results.append(WeekAcquireResult(
                week_id=w.week_id, label=w.label, status="failed",
                role=None, artifact_id=None, error=str(exc)[:300]))
            windex[w.week_id] = {
                "label": w.label, "start": w.start.isoformat(),
                "end": w.end.isoformat(), "role": None,
                "status": "failed", "error": str(exc)[:300]}
            continue
        res = results[-1]
        windex[w.week_id] = {
            "label": w.label, "start": w.start.isoformat(),
            "end": w.end.isoformat(), "role": res.role,
            "status": res.status,
            "selected_label": sel.selected_label}
        if callable(on_progress) and (i % 25 == 0 or i == len(weeks) - 1):
            on_progress(i + 1, len(weeks))
        time.sleep(client.request_delay)
    index_path.write_text(
        json.dumps(windex, indent=1, sort_keys=True), encoding="utf-8")
    return {
        "first": first, "last": last,
        "weeks_in_span": len(weeks),
        "already_have": sum(1 for r in results
                            if r.status == "already_have"),
        "acquired": sum(1 for r in results if r.status == "acquired"),
        "no_document": sum(1 for r in results
                           if r.status == "no_document"),
        "failed": [r.week_id for r in results if r.status == "failed"],
        "failures": [
            {"week_id": r.week_id, "error": r.error}
            for r in results if r.status == "failed"],
        "results": [r.__dict__ for r in results],
    }


# ---------------------------------------------------------------------------
# Source-document ledger (built from ArtifactStore at export time)
# ---------------------------------------------------------------------------

_DOC_ROLE_RE = re.compile(r"^(\d+)/(registro|boletin_completo|selection)$")


def weekly_document_rows(
        artifacts: list[SourceArtifact]) -> list[dict]:
    """Latest-version lifecycle_source_documents rows for weekly
    registry artifacts. ``supersedes_document_id`` points at the doc id
    of the immediately-previous byte version for the same logical key."""
    rows = []
    by_key: dict[str, list[SourceArtifact]] = {}
    for a in artifacts:
        if a.source_family != WEEKLY_FAMILY:
            continue
        m = _DOC_ROLE_RE.match(a.period)
        if not m:
            continue
        by_key.setdefault(a.period, []).append(a)
    for key in sorted(by_key):
        prev_doc_id = None
        for a in by_key[key]:
            week_id, role = key.split("/")
            doc_id = make_source_document_id(
                WEEKLY_FAMILY, f"weekly_registry/{key}", a.sha256)
            rows.append({
                "source_document_id": doc_id,
                "source_family": WEEKLY_FAMILY,
                "logical_source_key": f"weekly_registry/{key}",
                "source_role": role,
                "source_url": a.source_url_ephemeral,
                "publication_date": None,   # week end resolved at parse
                "publication_datetime": None,
                "retrieved_at": a.retrieved_at,
                "raw_sha256": a.sha256,
                "content_type": a.content_type,
                "size_bytes": a.size_bytes,
                "artifact_id": a.source_id,
                "supersedes_document_id": prev_doc_id,
                "parser_eligible": role in (
                    "registro", "boletin_completo"),
                "week_label": None,          # filled at parse
                "_artifact": a,              # internal, dropped pre-write
            })
            prev_doc_id = doc_id
    return rows


# ---------------------------------------------------------------------------
# Weekly parse → observations + assertions (pure, offline)
# ---------------------------------------------------------------------------


def weekly_ledger(
        store: ArtifactStore) -> tuple[
            list[LifecycleSourceDocument],
            list[LifecycleSourceObservation],
            list[LifecycleAssertion]]:
    """Parse every stored weekly artifact into source documents,
    observations and assertions. Fully deterministic — depends only on
    raw artifact bytes + parser/rule versions."""
    docs: list[LifecycleSourceDocument] = []
    observations: list[LifecycleSourceObservation] = []
    assertions: list[LifecycleAssertion] = []
    for a in store.load():
        if a.source_family != WEEKLY_FAMILY:
            continue
        m = _DOC_ROLE_RE.match(a.period)
        if not m:
            continue
        role = m.group(2)
        logical = f"weekly_registry/{a.period}"
        doc_id = make_source_document_id(
            WEEKLY_FAMILY, logical, a.sha256)
        if role not in ("registro", "boletin_completo"):
            docs.append(LifecycleSourceDocument(
                source_document_id=doc_id,
                source_family=WEEKLY_FAMILY,
                logical_source_key=logical,
                source_role=role,
                source_url=a.source_url_ephemeral,
                publication_date=None,
                publication_datetime=None,
                retrieved_at=a.retrieved_at,
                raw_sha256=a.sha256,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
                artifact_id=a.source_id,
                supersedes_document_id=None,
                parser_eligible=False,
                week_label=None))
            continue
        parsed = parse_registry_document(
            store.raw_path(a).read_bytes())
        pub_dt = None
        if parsed.week_label:
            end = parsed.week_label.split(" al ")[-1]
            try:
                pub_dt = datetime.strptime(
                    end, "%d/%m/%Y").date().isoformat()
            except ValueError:
                pub_dt = None
        docs.append(LifecycleSourceDocument(
            source_document_id=doc_id,
            source_family=WEEKLY_FAMILY,
            logical_source_key=logical,
            source_role=role,
            source_url=a.source_url_ephemeral,
            publication_date=pub_dt,
            publication_datetime=None,
            retrieved_at=a.retrieved_at,
            raw_sha256=a.sha256,
            content_type=a.content_type,
            size_bytes=a.size_bytes,
            artifact_id=a.source_id,
            supersedes_document_id=None,
            parser_eligible=True,
            week_label=parsed.week_label))
        for seq, o in enumerate(parsed.observations):
            obs_id = make_source_observation_id(doc_id, o.source_locator, seq)
            observations.append(LifecycleSourceObservation(
                source_observation_id=obs_id,
                source_document_id=doc_id,
                source_family=WEEKLY_FAMILY,
                logical_source_key=logical,
                source_section_raw=o.source_section_raw,
                subject_name_raw=o.subject_name_raw,
                subject_register_number_raw=o.subject_register_number_raw,
                regnums_in_text=json.dumps(
                    list(o.regnums_in_text), ensure_ascii=False),
                successor_regnums=json.dumps(
                    list(o.successor_regnums), ensure_ascii=False),
                entity_name_raw=None,
                entity_nif=None,
                entity_resolution_state=None,
                resolved_fund_key=None,
                official_event_registration_number=None,
                publication_datetime=pub_dt,
                category_raw=None,
                observation_text_verbatim=o.observation_text_verbatim,
                attachment_url=None,
                source_locator=o.source_locator,
                correction_indicator=False,
                representation=o.representation,
                parser=WEEKLY_PARSER,
                parser_version=WEEKLY_PARSER_VERSION))
            for aseq, (atype, stage, subj, obj, oname) in enumerate(
                    bulletin_assertions(o)):
                subject_key = f"FI:{subj}" if subj else None
                object_key = f"FI:{obj}" if obj else None
                assertions.append(LifecycleAssertion(
                    assertion_id=make_assertion_id(
                        obs_id, atype, subj or "", obj or "", aseq),
                    source_observation_id=obs_id,
                    source_document_id=doc_id,
                    source_family=WEEKLY_FAMILY,
                    assertion_type=atype,
                    assertion_stage=stage,
                    subject_key=subject_key,
                    subject_identifier_type=(
                        "cnmv_register_number" if subj else None),
                    subject_identifier_raw=subj,
                    object_key=object_key,
                    object_identifier_type=(
                        "cnmv_register_number" if obj else (
                            "verbatim_name" if oname else None)),
                    object_identifier_raw=obj or oname,
                    asserted_date=None,
                    asserted_date_semantics=None,
                    publication_datetime=pub_dt,
                    raw_text=o.observation_text_verbatim[:2000],
                    source_locator=o.source_locator,
                    identity_state=(
                        IdentityState.EXACT_REGISTER_NUMBER.value
                        if subj else IdentityState.UNRESOLVED.value),
                    representation=o.representation,
                    correction_of_observation_id=None,
                    supersedes_assertion_id=None,
                    correction_target_state=None,
                    parser_version=WEEKLY_PARSER_VERSION,
                    rule_version=RULE_VERSION))
    return docs, observations, assertions
