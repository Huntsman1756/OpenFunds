"""G9-E — lifecycle adjudication engine (protocol v1, preregistered).

Implements docs/g9/adjudication-rules.md verbatim: R1–R7 precedence,
frozen output vocabulary, zero-promotion invariants. Pure function —
same inputs -> same records -> same fingerprint.

Output is an adjudication record per candidate, NOT a canonical
lifecycle event table and NOT a materialized lineage edge.
"""
from __future__ import annotations

from dataclasses import dataclass

from cnmv_iic.lifecycle import AssertionParticipant, LifecycleAssertion
from cnmv_iic.lifecycle_research import CandidateEvidenceProfile
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
