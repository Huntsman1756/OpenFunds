"""G9-E — lifecycle adjudication engine (protocol v1, preregistered).

Implements docs/g9/adjudication-rules.md verbatim: R1–R7 precedence,
frozen output vocabulary, zero-promotion invariants. Pure function —
same inputs -> same records -> same fingerprint.

Output is an adjudication record per candidate, NOT a canonical
lifecycle event table and NOT a materialized lineage edge.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from cnmv_iic.lifecycle import AssertionParticipant, LifecycleAssertion, LifecycleSourceDocument
from cnmv_iic.lifecycle_research import CandidateEvidenceProfile, evidence_signature, profile_dict
from cnmv_iic.storage import canonical_fingerprint

ENGINE_VERSION = "g9e-v1"

OUTCOMES = frozenset({
    "ADJUDICATED_ABSORBED_BY",
    "ADJUDICATED_LIQUIDATED",
    "INDETERMINATE_MULTIPLE_SUCCESSORS",
    "INDETERMINATE_NO_SUCCESSOR",
    "INDETERMINATE_CONFLICTING_EVIDENCE",
    "INDETERMINATE_CORRECTION_OR_RENUNCIATION",
    "UNKNOWN_EXIT",
})

_MERGER_TYPES = frozenset({
    "MERGER_AUTHORIZED", "MERGER_REGISTRATION_RECORDED",
    "MERGER_REGISTERED", "MERGER_EXECUTED", "MERGER_RENOUNCED",
    "MERGER_REQUESTED", "MERGER_PROPOSED"})


@dataclass(frozen=True)
class AdjudicationRecord:
    candidate_id: str
    entity_key: str
    outcome: str                       # one of OUTCOMES
    rule_id: str                       # R1..R7
    successor_key: str | None          # only ADJUDICATED_ABSORBED_BY
    successor_corroborated: bool       # asserted in >=2 source families
    evidence_assertion_ids: tuple[str, ...]
    flags: tuple[str, ...]             # preserved contradictions/corrections
    engine_version: str


def _corroborated(
        p: CandidateEvidenceProfile,
        assertions: dict[str, LifecycleAssertion],
        participants: dict[str, list[AssertionParticipant]]) -> bool:
    """Successor asserted as ABSORBING participant in >=2 families."""
    if len(p.exact_successor_ids) != 1:
        return False
    succ = p.exact_successor_ids[0]
    fams = set()
    for aid in p.assertion_ids:
        a = assertions.get(aid)
        if a is None or a.assertion_type not in _MERGER_TYPES:
            continue
        if any(q.participant_role == "ABSORBING"
               and q.participant_identifier_raw == succ
               for q in participants.get(aid, [])):
            fams.add(a.source_family)
    return len(fams) >= 2


def adjudicate(
        profiles: list[CandidateEvidenceProfile],
        assertions: list[LifecycleAssertion],
        participants: list[AssertionParticipant],
        ) -> list[AdjudicationRecord]:
    """Apply preregistered rules R1–R7 in order. One record per
    profile — conservation guaranteed by construction."""
    by_aid = {a.assertion_id: a for a in assertions}
    parts_by_aid: dict[str, list[AssertionParticipant]] = {}
    for q in participants:
        parts_by_aid.setdefault(q.assertion_id, []).append(q)

    records: list[AdjudicationRecord] = []
    for p in sorted(profiles, key=lambda p: p.candidate_id):
        tset = set(p.assertion_types)
        has_merger = bool(tset & _MERGER_TYPES)
        n_succ = len(p.exact_successor_ids)
        flags = tuple(p.contradiction_flags) + tuple(
            f for f in p.correction_flags)

        rule, outcome, succ_key = "R7", "UNKNOWN_EXIT", None
        if p.has_merger_renounced and has_merger or p.has_rectification:
            rule = "R1"
            outcome = "INDETERMINATE_CORRECTION_OR_RENUNCIATION"
        elif any(f.startswith("MERGER_PLUS")
                 for f in p.contradiction_flags):
            rule = "R2"
            outcome = "INDETERMINATE_CONFLICTING_EVIDENCE"
        elif p.candidate_is_absorbed_participant and n_succ > 1:
            rule = "R3"
            outcome = "INDETERMINATE_MULTIPLE_SUCCESSORS"
        elif (p.candidate_is_absorbed_participant and n_succ == 1
                and has_merger):
            rule = "R4"
            outcome = "ADJUDICATED_ABSORBED_BY"
            succ_key = f"FI:{p.exact_successor_ids[0]}"
        elif has_merger and n_succ == 0:
            rule = "R5"
            outcome = "INDETERMINATE_NO_SUCCESSOR"
        elif (p.has_liquidation or p.has_in_liquidation_marker):
            rule = "R6"
            outcome = "ADJUDICATED_LIQUIDATED"

        records.append(AdjudicationRecord(
            candidate_id=p.candidate_id,
            entity_key=p.entity_key,
            outcome=outcome,
            rule_id=rule,
            successor_key=succ_key,
            successor_corroborated=(
                _corroborated(p, by_aid, parts_by_aid)
                if outcome == "ADJUDICATED_ABSORBED_BY" else False),
            evidence_assertion_ids=tuple(p.assertion_ids),
            flags=flags,
            engine_version=ENGINE_VERSION))
    return records


def record_dict(r: AdjudicationRecord) -> dict:
    return {
        "candidate_id": r.candidate_id,
        "entity_key": r.entity_key,
        "outcome": r.outcome,
        "rule_id": r.rule_id,
        "successor_key": r.successor_key,
        "successor_corroborated": r.successor_corroborated,
        "evidence_assertion_ids": list(r.evidence_assertion_ids),
        "flags": list(r.flags),
        "engine_version": r.engine_version,
    }


def records_fingerprint(records: list[AdjudicationRecord]) -> str:
    return canonical_fingerprint([record_dict(r) for r in records])


def check_invariants(
        records: list[AdjudicationRecord],
        profiles: list[CandidateEvidenceProfile],
        participants: list[AssertionParticipant]) -> dict:
    """Preregistered zero-invariants G1–G6. Returns violations."""
    v: dict[str, int] = {
        "identity_promotion": 0,
        "multi_successor_adjudicated": 0,
        "contradiction_collapsed": 0,
        "correction_dropped": 0,
        "conservation_fail": 0,
    }
    exact_keys = {q.participant_key for q in participants
                  if q.identity_state == "exact_register_number"}
    by_cid = {p.candidate_id: p for p in profiles}
    seen: set[str] = set()
    for r in records:
        if r.candidate_id in seen:
            v["conservation_fail"] += 1
        seen.add(r.candidate_id)
        p = by_cid.get(r.candidate_id)
        if p is None:
            v["conservation_fail"] += 1
            continue
        if r.outcome == "ADJUDICATED_ABSORBED_BY":
            if r.successor_key not in exact_keys:
                v["identity_promotion"] += 1
            if len(p.exact_successor_ids) > 1:
                v["multi_successor_adjudicated"] += 1
            if any(f.startswith("MERGER_PLUS")
                   for f in p.contradiction_flags):
                v["contradiction_collapsed"] += 1
        if (p.has_merger_renounced or p.has_rectification
                or p.correction_flags) and not (
                r.flags or r.outcome ==
                "INDETERMINATE_CORRECTION_OR_RENUNCIATION"):
            v["correction_dropped"] += 1
    v["conservation_fail"] += abs(len(profiles) - len(seen))
    return v


# ---------------------------------------------------------------------
# G9-F — derived read model: adjudications table + ABSORBED_BY edges.
# Rows are the deterministic conclusion of assertion sets — explicitly
# derived evidence_state, never source observations themselves.
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class LifecycleAdjudicationRow:
    """Materialized adjudication — one row per disappearance candidate."""
    adjudication_id: str
    candidate_id: str
    entity_key: str
    adjudication: str                # outcome label (g9e-v1 vocab)
    successor_key: str | None
    rule_id: str
    engine_version: str
    evidence_signature: str
    evidence_profile_id: str
    authorization_assertion_ids: str   # JSON list
    registration_assertion_ids: str    # JSON list
    deregistration_assertion_ids: str  # JSON list
    execution_assertion_ids: str       # JSON list
    participant_assertion_ids: str     # JSON list — all evidence
    cross_source_corroborated: bool
    authorization_date: str | None
    registration_date: str | None
    deregistration_date: str | None
    execution_date: str | None
    source_artifact_ids: str           # JSON list — raw_sha256-backed
    flags: str                         # JSON list
    adjudicated_at_build: str          # content stamp, not a clock


@dataclass(frozen=True)
class LineageEdge:
    """Derived ABSORBED_BY edge — conclusion of an assertion set, not a
    directly observed source fact. Emitted only for
    ADJUDICATED_ABSORBED_BY under g9e-v1."""
    edge_id: str
    from_entity_key: str             # absorbed fund (the candidate)
    to_entity_key: str               # absorbing/surviving fund
    edge_type: str                   # ABSORBED_BY only
    evidence_state: str              # ADJUDICATED
    rule_id: str
    engine_version: str
    candidate_id: str
    source_assertion_ids: str        # JSON list


_REG_TYPES = frozenset({
    "MERGER_REGISTRATION_RECORDED", "MERGER_REGISTERED"})
_DEREG_TYPES = frozenset({
    "DEREGISTRATION_RECORDED", "DEREGISTRATION_REPORTED"})


def _aids(p: CandidateEvidenceProfile,
          by_aid: dict[str, LifecycleAssertion],
          types: frozenset[str]) -> list[str]:
    return [aid for aid in p.assertion_ids
            if aid in by_aid and by_aid[aid].assertion_type in types]


def _earliest(aids: list[str],
              by_aid: dict[str, LifecycleAssertion]) -> str | None:
    dts = sorted(dt for aid in aids
                 if (dt := by_aid[aid].publication_datetime))
    return dts[0] if dts else None


def enrich_adjudications(
        records: list[AdjudicationRecord],
        profiles: list[CandidateEvidenceProfile],
        assertions: list[LifecycleAssertion],
        documents: list[LifecycleSourceDocument],
        ) -> list[LifecycleAdjudicationRow]:
    """Join records to profiles + assertion/doc provenance."""
    by_aid = {a.assertion_id: a for a in assertions}
    by_cid = {p.candidate_id: p for p in profiles}
    doc_art = {d.source_document_id: d.artifact_id
               for d in documents}
    rows: list[LifecycleAdjudicationRow] = []
    for r in records:
        p = by_cid[r.candidate_id]
        auth = _aids(p, by_aid, frozenset({"MERGER_AUTHORIZED"}))
        reg = _aids(p, by_aid, _REG_TYPES)
        dereg = _aids(p, by_aid, _DEREG_TYPES)
        execu = _aids(p, by_aid, frozenset({"MERGER_EXECUTED"}))
        arts = sorted({doc_art[by_aid[aid].source_document_id]
                       for aid in p.assertion_ids
                       if aid in by_aid
                       and by_aid[aid].source_document_id in doc_art})
        prof_id = "lprof-" + canonical_fingerprint(
            [profile_dict(p)])[:16]
        rows.append(LifecycleAdjudicationRow(
            adjudication_id="ladj-" + canonical_fingerprint(
                [{"c": r.candidate_id, "v": ENGINE_VERSION}])[:16],
            candidate_id=r.candidate_id,
            entity_key=r.entity_key,
            adjudication=r.outcome,
            successor_key=r.successor_key,
            rule_id=r.rule_id,
            engine_version=r.engine_version,
            evidence_signature=evidence_signature(p),
            evidence_profile_id=prof_id,
            authorization_assertion_ids=json.dumps(auth),
            registration_assertion_ids=json.dumps(reg),
            deregistration_assertion_ids=json.dumps(dereg),
            execution_assertion_ids=json.dumps(execu),
            participant_assertion_ids=json.dumps(
                list(p.assertion_ids)),
            cross_source_corroborated=r.successor_corroborated,
            authorization_date=_earliest(auth, by_aid),
            registration_date=_earliest(reg, by_aid),
            deregistration_date=_earliest(dereg, by_aid),
            execution_date=_earliest(execu, by_aid),
            source_artifact_ids=json.dumps(arts),
            flags=json.dumps(list(r.flags)),
            adjudicated_at_build=ENGINE_VERSION))
    return rows


def derive_edges(
        records: list[AdjudicationRecord]) -> list[LineageEdge]:
    """ABSORBED_BY only. Never from INDETERMINATE_* or UNKNOWN_EXIT."""
    edges: list[LineageEdge] = []
    for r in records:
        if r.outcome != "ADJUDICATED_ABSORBED_BY" or not r.successor_key:
            continue
        edges.append(LineageEdge(
            edge_id="ledge-" + canonical_fingerprint(
                [{"c": r.candidate_id, "t": r.successor_key,
                  "v": ENGINE_VERSION}])[:16],
            from_entity_key=r.entity_key,
            to_entity_key=r.successor_key,
            edge_type="ABSORBED_BY",
            evidence_state="ADJUDICATED",
            rule_id=r.rule_id,
            engine_version=r.engine_version,
            candidate_id=r.candidate_id,
            source_assertion_ids=json.dumps(
                list(r.evidence_assertion_ids))))
    return sorted(edges, key=lambda e: e.edge_id)
