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

from cnmv_iic.acquisition.hr import HrClient, result_pages
from cnmv_iic.acquisition.weekly import (
    WEEKLY_PAGE,
    WeeklyBulletinClient,
    WeekOption,
)
from cnmv_iic.adapters.relevant_information import (
    PARSER as HR_PARSER,
)
from cnmv_iic.adapters.relevant_information import (
    PARSER_VERSION as HR_PARSER_VERSION,
)
from cnmv_iic.adapters.relevant_information import (
    hr_assertions,
    parse_history_page,
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
    CandidateEvidenceLink,
    DisappearanceCandidate,
    EntityResolution,
    EntityResolutionState,
    IdentityState,
    LifecycleAssertion,
    LifecycleSourceDocument,
    LifecycleSourceObservation,
    LinkState,
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


# ---------------------------------------------------------------------------
# HR acquisition — per-entity crawler, blind holdout excluded
# ---------------------------------------------------------------------------

_HR_PERIOD_RE = re.compile(r"^hr/(.+)/(search|history_p\d+)$")


def _hr_window(c: DisappearanceCandidate) -> tuple[str, str]:
    """Search window: -14 months / +4 months around first_observed_absent
    (measured practical bound in the probe)."""
    fa = c.first_observed_absent
    fy, fm = int(fa[:4]), int(fa[5:])
    d0 = date(fy, fm, 1)
    desde = date.fromordinal(d0.toordinal() - 425)
    hasta = date.fromordinal(d0.toordinal() + 155)
    return desde.strftime("%d/%m/%Y"), hasta.strftime("%d/%m/%Y")


@dataclass(frozen=True)
class HrAcquireResult:
    entity_key: str
    candidate_id: str
    status: str          # resolved | ambiguous | not_found | already_have | failed
    nif: str | None
    n_pages: int
    error: str | None = None


def acquire_hr(
        store: ArtifactStore,
        dataset_root: Path | str,
        holdout_manifest: Path | str,
        *,
        candidates: list[DisappearanceCandidate] | None = None,
        client: HrClient | None = None,
        on_progress: object = None) -> dict:
    """Entity-oriented HR crawl for development/regression candidates.

    The blind holdout is never queried, never linked, never inspected:
    candidates whose id is sealed are skipped before any request."""
    sealed = holdout_ids(holdout_manifest)
    cands = candidates if candidates is not None else \
        disappearance_candidates(dataset_root)
    client = client or HrClient()
    results: list[HrAcquireResult] = []
    seen_keys: set[str] = set()
    eligible = [
        c for c in cands
        if c.candidate_id not in sealed and c.entity_key not in seen_keys]
    for c in eligible:
        seen_keys.add(c.entity_key)
    for i, c in enumerate(eligible):
        if c.candidate_id in sealed:          # defense in depth
            continue
        key = c.entity_key
        prior = store.latest_for_period(
            f"hr/{key}/search", source_family=HR_FAMILY)
        if prior is not None and store.raw_path(prior).exists():
            n_pages = sum(
                1 for a in store.load()
                if a.source_family == HR_FAMILY
                and a.period.startswith(f"hr/{key}/"))
            results.append(HrAcquireResult(
                entity_key=key, candidate_id=c.candidate_id,
                status="already_have", nif=None, n_pages=n_pages))
            continue
        try:
            desde, hasta = _hr_window(c)
            res = client.search_entity(
                c.denominacion or "", desde=desde, hasta=hasta)
            store.put_blob(
                period=f"hr/{key}/search",
                source_page=res.final_url,
                source_url=res.final_url,
                content_type="text/html",
                data=res.raw_html.encode("utf-8"),
                raw_suffix=".html",
                retrieved_at=datetime.now(UTC),
                source_family=HR_FAMILY,
                source_id_prefix=HR_PREFIX)
            if res.no_results:
                results.append(HrAcquireResult(
                    entity_key=key, candidate_id=c.candidate_id,
                    status="not_found", nif=None, n_pages=1))
                continue
            if res.nif is None:
                results.append(HrAcquireResult(
                    entity_key=key, candidate_id=c.candidate_id,
                    status="ambiguous", nif=None,
                    n_pages=len(res.nif_candidates)))
                continue
            n_done = 1
            for pg in result_pages(res.raw_html):
                page = client.fetch_result_page(
                    res.final_url + f"&page={pg}")
                store.put_blob(
                    period=f"hr/{key}/history_p{pg}",
                    source_page=page.url,
                    source_url=page.url,
                    content_type="text/html",
                    data=page.raw_html.encode("utf-8"),
                    raw_suffix=".html",
                    retrieved_at=datetime.now(UTC),
                    source_family=HR_FAMILY,
                    source_id_prefix=HR_PREFIX)
                n_done += 1
                time.sleep(client.request_delay)
            results.append(HrAcquireResult(
                entity_key=key, candidate_id=c.candidate_id,
                status="resolved", nif=res.nif, n_pages=n_done))
        except CnmvIicError as exc:
            results.append(HrAcquireResult(
                entity_key=key, candidate_id=c.candidate_id,
                status="failed", nif=None, n_pages=0,
                error=str(exc)[:300]))
        if callable(on_progress) and (i % 25 == 0 or i == len(eligible) - 1):
            on_progress(i + 1, len(eligible))
        time.sleep(client.request_delay)
    # persist per-entity context so the offline ledger can emit
    # EntityResolution rows without re-running candidates
    index_path = Path(dataset_root) / "lifecycle" / "hr_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    hindex: dict = {}
    if index_path.exists():
        hindex = json.loads(index_path.read_text(encoding="utf-8"))
    for c in eligible:
        hindex[c.entity_key] = {
            "candidate_id": c.candidate_id,
            "denominacion": c.denominacion,
            "first_observed_absent": c.first_observed_absent}
    index_path.write_text(
        json.dumps(hindex, indent=1, sort_keys=True), encoding="utf-8")
    return {
        "eligible": len(eligible),
        "sealed_skipped": len(cands) - len(eligible),
        "resolved": sum(1 for r in results if r.status == "resolved"),
        "ambiguous": sum(1 for r in results if r.status == "ambiguous"),
        "not_found": sum(1 for r in results if r.status == "not_found"),
        "already_have": sum(
            1 for r in results if r.status == "already_have"),
        "failed": [r.entity_key for r in results if r.status == "failed"],
        "failures": [
            {"entity_key": r.entity_key, "error": r.error}
            for r in results if r.status == "failed"],
        "results": [r.__dict__ for r in results],
    }


# ---------------------------------------------------------------------------
# HR ledger — artifacts -> documents -> observations -> assertions
# ---------------------------------------------------------------------------


def hr_ledger(
        store: ArtifactStore,
        hr_index: dict[str, dict] | None = None) -> tuple[
            list[LifecycleSourceDocument],
            list[LifecycleSourceObservation],
            list[LifecycleAssertion],
            list[EntityResolution]]:
    """Parse stored HR artifacts into ledger rows + entity resolutions.

    ``hr_index`` carries the per-entity acquisition context
    (candidate_id, denominacion) persisted by ``acquire_hr`` — the
    ledger stays offline; candidate linkage re-checks the seal."""
    hr_index = hr_index or {}
    docs: list[LifecycleSourceDocument] = []
    observations: list[LifecycleSourceObservation] = []
    assertions: list[LifecycleAssertion] = []
    resolutions: dict[str, EntityResolution] = {}
    for a in store.load():
        if a.source_family != HR_FAMILY:
            continue
        m = _HR_PERIOD_RE.match(a.period)
        if not m:
            continue
        entity_key, role = m.group(1), m.group(2)
        logical = f"relevant_information/{a.period}"
        doc_id = make_source_document_id(HR_FAMILY, logical, a.sha256)
        docs.append(LifecycleSourceDocument(
            source_document_id=doc_id,
            source_family=HR_FAMILY,
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
            parser_eligible=True,
            week_label=None))
        html = store.raw_path(a).read_bytes().decode("utf-8", "replace")
        parsed = parse_history_page(html)
        # entity resolution: exact fund regnum corroborated by prose
        fund_reg = entity_key.split(":")[-1]
        nifs = sorted(set(re.findall(r"[?&]nif=([A-Z0-9-]+)", html)))
        nif = nifs[0] if len(nifs) == 1 else None
        if "No se han encontrado" in html:
            state = EntityResolutionState.NOT_FOUND.value
        elif len(nifs) > 1 and nif is None:
            state = EntityResolutionState.AMBIGUOUS.value
        else:
            state = EntityResolutionState.DISCOVERY_ONLY.value
        for o in parsed.observations:
            if fund_reg in o.regnums_in_text:
                state = EntityResolutionState\
                    .EXACT_REGNUM_CORROBORATED.value
        ctx = hr_index.get(entity_key, {})
        resolutions[entity_key] = EntityResolution(
            entity_key=entity_key,
            candidate_id=ctx.get("candidate_id", ""),
            denominacion_used=ctx.get("denominacion", ""),
            entity_nif=nif,
            nif_candidates=json.dumps(nifs, ensure_ascii=False),
            resolution_state=state,
            corroboration=(
                "event_prose" if state == EntityResolutionState
                .EXACT_REGNUM_CORROBORATED.value else None),
            search_document_id=doc_id,
            parser_version=HR_PARSER_VERSION)
        for seq, o in enumerate(parsed.observations):
            obs_id = make_source_observation_id(
                doc_id, o.source_locator, seq)
            pub_dt = (
                f"{o.publication_date}T{o.publication_time}"
                if o.publication_date and o.publication_time
                else o.publication_date)
            observations.append(LifecycleSourceObservation(
                source_observation_id=obs_id,
                source_document_id=doc_id,
                source_family=HR_FAMILY,
                logical_source_key=logical,
                source_section_raw=None,
                subject_name_raw=None,
                subject_register_number_raw=None,
                regnums_in_text=json.dumps(
                    list(o.regnums_in_text), ensure_ascii=False),
                successor_regnums=json.dumps(
                    list(o.successor_regnums), ensure_ascii=False),
                entity_name_raw=parsed.entity_header,
                entity_nif=nif,
                entity_resolution_state=state,
                resolved_fund_key=(
                    entity_key if state == EntityResolutionState
                    .EXACT_REGNUM_CORROBORATED.value else None),
                official_event_registration_number=
                o.hr_event_reg_number,
                publication_datetime=pub_dt,
                category_raw=o.category_raw,
                observation_text_verbatim=o.summary_raw,
                attachment_url=o.doc_url,
                source_locator=o.source_locator,
                correction_indicator=o.correction_indicator,
                representation=o.representation,
                parser=HR_PARSER,
                parser_version=HR_PARSER_VERSION))
            for aseq, ad in enumerate(hr_assertions(o)):
                subject_key = (
                    f"FI:{ad.subject_regnum}"
                    if ad.subject_regnum else None)
                object_key = (
                    f"FI:{ad.object_regnum}"
                    if ad.object_regnum else None)
                assertions.append(LifecycleAssertion(
                    assertion_id=make_assertion_id(
                        obs_id, ad.assertion_type,
                        ad.subject_regnum or "",
                        ad.object_regnum or "", aseq),
                    source_observation_id=obs_id,
                    source_document_id=doc_id,
                    source_family=HR_FAMILY,
                    assertion_type=ad.assertion_type,
                    assertion_stage=ad.assertion_stage,
                    subject_key=subject_key,
                    subject_identifier_type=(
                        "cnmv_register_number"
                        if ad.subject_regnum else None),
                    subject_identifier_raw=ad.subject_regnum,
                    object_key=object_key,
                    object_identifier_type=(
                        "cnmv_register_number" if ad.object_regnum else (
                            "verbatim_name" if ad.object_name_raw
                            else None)),
                    object_identifier_raw=(
                        ad.object_regnum or ad.object_name_raw),
                    asserted_date=ad.asserted_date,
                    asserted_date_semantics=ad.asserted_date_semantics,
                    publication_datetime=pub_dt,
                    raw_text=o.summary_raw[:2000],
                    source_locator=o.source_locator,
                    identity_state=(
                        IdentityState.EXACT_REGISTER_NUMBER.value
                        if ad.subject_regnum
                        else IdentityState.UNRESOLVED.value),
                    representation=o.representation,
                    correction_of_observation_id=None,
                    supersedes_assertion_id=None,
                    correction_target_state=None,
                    parser_version=HR_PARSER_VERSION,
                    rule_version=RULE_VERSION))
    return docs, observations, assertions, list(resolutions.values())


# ---------------------------------------------------------------------------
# FONDREGISTRO terminal markers — auxiliary source assertions
# ---------------------------------------------------------------------------

_BAJA_MARKER = re.compile(r"\bbaja\s+(\d{2})\.(\d{2})\.(\d{2,4})", re.I)
_EN_LIQ = re.compile(r"\(?\s*EN LIQUIDACI.N\s*\)?", re.I)


def fondregistro_markers(
        dataset_root: Path | str,
        store: ArtifactStore) -> tuple[
            list[LifecycleSourceDocument],
            list[LifecycleSourceObservation],
            list[LifecycleAssertion]]:
    """Terminal markers embedded in the FONDREGISTRO denominacion
    itself (``baja dd.mm.yy``, ``(EN LIQUIDACION)``) — auxiliary
    assertions, never promoted to lifecycle cause."""
    root = Path(dataset_root)
    con = duckdb.connect(database=":memory:")
    glob = str(root / "funds" / "period=*" / "*.parquet")
    rows = con.execute(  # noqa: S608 — local glob, no user input
        f"SELECT period, fund_key, numero_registro, denominacion,"
        f" source_artifact_id, xml_locator"
        f" FROM read_parquet('{glob}', hive_partitioning=true)"
        f" WHERE denominacion ILIKE '%baja %'"
        f" OR denominacion ILIKE '%EN LIQUIDACION%'").fetchall()
    docs: dict[str, LifecycleSourceDocument] = {}
    artifacts = {a.source_id: a for a in store.load()}
    observations: list[LifecycleSourceObservation] = []
    assertions: list[LifecycleAssertion] = []
    for period, key, regnum, denom, art_id, locator in sorted(rows):
        art = artifacts.get(art_id)
        logical = f"fondregistro/{period}"
        doc_id = make_source_document_id(
            SourceFamily.FONDREGISTRO.value, logical,
            art.sha256 if art else art_id or "")
        if doc_id not in docs:
            docs[doc_id] = LifecycleSourceDocument(
                source_document_id=doc_id,
                source_family=SourceFamily.FONDREGISTRO.value,
                logical_source_key=logical,
                source_role="registry-monthly",
                source_url=art.source_url_ephemeral if art else "",
                publication_date=period + "-01",
                publication_datetime=None,
                retrieved_at=art.retrieved_at if art else "",
                raw_sha256=art.sha256 if art else "",
                content_type=art.content_type if art else None,
                size_bytes=art.size_bytes if art else 0,
                artifact_id=art_id or "",
                supersedes_document_id=None,
                parser_eligible=True,
                week_label=None)
        obs_id = make_source_observation_id(
            doc_id, f"{locator}/{key}", 0)
        observations.append(LifecycleSourceObservation(
            source_observation_id=obs_id,
            source_document_id=doc_id,
            source_family=SourceFamily.FONDREGISTRO.value,
            logical_source_key=logical,
            source_section_raw="FONDREGISTRO_DENOMINACION",
            subject_name_raw=denom,
            subject_register_number_raw=regnum,
            regnums_in_text=json.dumps([regnum] if regnum else []),
            successor_regnums="[]",
            entity_name_raw=None,
            entity_nif=None,
            entity_resolution_state=None,
            resolved_fund_key=key,
            official_event_registration_number=None,
            publication_datetime=period + "-01",
            category_raw=None,
            observation_text_verbatim=denom or "",
            attachment_url=None,
            source_locator=f"{locator or 'funds'}/{key}",
            correction_indicator=False,
            representation="structured",
            parser="cnmv_iic.lifecycle_ingest",
            parser_version="1"))
        m = _BAJA_MARKER.search(denom or "")
        marks: list[tuple[str, str, str | None, str | None]] = []
        if m:
            y = int(m.group(3))
            y += 2000 if y < 100 else 0
            marks.append((
                "REGISTRY_NAME_BAJA_MARKER", "REPORTED",
                f"{y:04d}-{int(m.group(2)):02d}-{int(m.group(1)):02d}",
                "SOURCE_BAJA_MARKER_DATE"))
        if _EN_LIQ.search(denom or ""):
            marks.append((
                "REGISTRY_NAME_IN_LIQUIDATION_MARKER", "REPORTED",
                None, None))
        for aseq, (atype, stage, d_iso, d_sem) in enumerate(marks):
            assertions.append(LifecycleAssertion(
                assertion_id=make_assertion_id(
                    obs_id, atype, regnum or "", "", aseq),
                source_observation_id=obs_id,
                source_document_id=doc_id,
                source_family=SourceFamily.FONDREGISTRO.value,
                assertion_type=atype,
                assertion_stage=stage,
                subject_key=key,
                subject_identifier_type="cnmv_register_number",
                subject_identifier_raw=regnum,
                object_key=None,
                object_identifier_type=None,
                object_identifier_raw=None,
                asserted_date=d_iso,
                asserted_date_semantics=d_sem,
                publication_datetime=period + "-01",
                raw_text=denom or "",
                source_locator=f"{locator or 'funds'}/{key}",
                identity_state=IdentityState.EXACT_REGISTER_NUMBER.value,
                representation="structured",
                correction_of_observation_id=None,
                supersedes_assertion_id=None,
                correction_target_state=None,
                parser_version="1",
                rule_version=RULE_VERSION))
    return list(docs.values()), observations, assertions


# ---------------------------------------------------------------------------
# Candidate linkage — exact regnum only, holdout never linked
# ---------------------------------------------------------------------------


def candidate_links(
        candidates: list[DisappearanceCandidate],
        assertions: list[LifecycleAssertion],
        sealed: set[str]) -> list[CandidateEvidenceLink]:
    """candidate_source_evidence rows.

    EXACT_SUBJECT_REGNUM / EXACT_OBJECT_REGNUM only — temporal proximity
    alone never creates a link, and sealed blind-holdout candidates are
    skipped before any matching (the required guard)."""
    links: list[CandidateEvidenceLink] = []
    for c in candidates:
        if c.candidate_id in sealed:          # holdout guard — required
            continue
        regnum = c.entity_key.split(":")[-1]
        for a in assertions:
            state = None
            if a.subject_identifier_raw == regnum:
                state = LinkState.EXACT_SUBJECT_REGNUM
            elif a.object_identifier_raw == regnum:
                state = LinkState.EXACT_OBJECT_REGNUM
            if state is None:
                continue
            links.append(CandidateEvidenceLink(
                candidate_id=c.candidate_id,
                entity_key=c.entity_key,
                assertion_id=a.assertion_id,
                source_observation_id=a.source_observation_id,
                source_document_id=a.source_document_id,
                link_state=state.value,
                parser_version=a.parser_version,
                rule_version=RULE_VERSION))
    return links
