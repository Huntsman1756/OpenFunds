"""G9-C — candidate evidence profiles + taxonomy measurement helpers.

Derived RESEARCH layer over the G9-B source-assertion ledger. These
profiles measure what official evidence exists per disappearance
candidate; they are not lifecycle events and adjudicate nothing.

Determinism: same ledger inputs -> same profiles -> same fingerprint.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from cnmv_iic.lifecycle import (
    AssertionParticipant,
    DisappearanceCandidate,
    EntityResolution,
    LifecycleAssertion,
    ParticipantRole,
)
from cnmv_iic.storage import canonical_fingerprint

MERGER_TYPES = frozenset({
    "MERGER_REQUESTED", "MERGER_PROPOSED", "MERGER_AUTHORIZED",
    "MERGER_REGISTERED", "MERGER_EXECUTED", "MERGER_RENOUNCED",
    "MERGER_REGISTRATION_RECORDED"})


@dataclass(frozen=True)
class CandidateEvidenceProfile:
    """One derived evidence profile per dev FUND_DISAPPEARED candidate.

    Pure measurement — no canonical cause, successor or event."""
    candidate_id: str
    entity_key: str
    last_observed_present: str
    first_observed_absent: str
    lifespan_months: int
    assertion_ids: tuple[str, ...]
    assertion_types: tuple[str, ...]
    assertion_stages: tuple[str, ...]
    participant_roles: tuple[str, ...]
    hr_resolution_state: str | None
    has_deregistration_recorded: bool
    has_merger_authorized: bool
    has_merger_registration: bool
    has_merger_executed: bool
    has_merger_renounced: bool
    has_dissolution: bool
    has_liquidation: bool
    has_in_liquidation_marker: bool
    has_baja_marker: bool
    has_transformation: bool
    has_rectification: bool
    candidate_is_absorbed_participant: bool
    candidate_is_absorbing_participant: bool
    exact_successor_ids: tuple[str, ...]
    exact_predecessor_ids: tuple[str, ...]
    earliest_assertion_datetime: str | None
    latest_assertion_datetime: str | None
    explicit_effective_date_count: int
    contradiction_flags: tuple[str, ...]
    correction_flags: tuple[str, ...]


def evidence_profiles(
        candidates: list[DisappearanceCandidate],
        assertions: list[LifecycleAssertion],
        participants: list[AssertionParticipant],
        resolutions: list[EntityResolution],
        sealed: set[str]) -> list[CandidateEvidenceProfile]:
    """One profile per non-sealed candidate — conservation guaranteed
    (a profile exists even with zero linked evidence)."""
    by_assertion = {a.assertion_id: a for a in assertions}
    parts_by_assertion: dict[str, list[AssertionParticipant]] = {}
    for p in participants:
        parts_by_assertion.setdefault(p.assertion_id, []).append(p)
    res_by_entity = {r.entity_key: r for r in resolutions}

    profiles: list[CandidateEvidenceProfile] = []
    for c in candidates:
        if c.candidate_id in sealed:
            continue
        regnum = c.entity_key.split(":")[-1]
        mine: dict[str, list[AssertionParticipant]] = {}
        for p in participants:
            if (p.participant_identifier_raw == regnum
                    or p.participant_key == c.entity_key):
                mine.setdefault(p.assertion_id, []).append(p)
        # assertions where the candidate participates (any role)
        my_asserts = [by_assertion[aid] for aid in sorted(mine)
                      if aid in by_assertion]
        types = sorted({a.assertion_type for a in my_asserts})
        stages = sorted({a.assertion_stage for a in my_asserts})
        roles = sorted({p.participant_role
                        for ps in mine.values() for p in ps})

        successors: set[str] = set()
        predecessors: set[str] = set()
        for aid, ps in mine.items():
            all_ps = parts_by_assertion.get(aid, [])
            for p in ps:
                if (p.participant_role == ParticipantRole.ABSORBED.value
                        and p.participant_identifier_raw == regnum):
                    for q in all_ps:
                        if (q.participant_role ==
                                ParticipantRole.ABSORBING.value
                                and q.participant_identifier_raw):
                            successors.add(q.participant_identifier_raw)
                if (p.participant_role == ParticipantRole.ABSORBING.value
                        and p.participant_identifier_raw == regnum):
                    for q in all_ps:
                        if (q.participant_role ==
                                ParticipantRole.ABSORBED.value
                                and q.participant_identifier_raw):
                            predecessors.add(q.participant_identifier_raw)

        dts = sorted(a.publication_datetime for a in my_asserts
                     if a.publication_datetime)
        eff = sum(1 for a in my_asserts if a.asserted_date)
        flags: list[str] = []
        tset = set(types)
        if (tset & MERGER_TYPES) and (
                {"DISSOLUTION_AGREED", "LIQUIDATION_EXECUTED"} & tset):
            flags.append("MERGER_PLUS_DISSOLUTION")
        if (tset & MERGER_TYPES) and "DEREGISTRATION_RECORDED" in tset \
                and not successors:
            flags.append("MERGER_AND_BAJA_NO_SUCCESSOR")
        if len(successors) > 1:
            flags.append("MULTI_SUCCESSOR")
        if "MERGER_RENOUNCED" in tset and (
                (tset & MERGER_TYPES) - {"MERGER_RENOUNCED"}):
            flags.append("RENOUNCED_WITH_OTHER_MERGER_EVIDENCE")
        corr: list[str] = []
        for a in my_asserts:
            if a.assertion_type == "RECTIFICATION_REPORTED":
                corr.append(
                    "RECTIFICATION_" + (a.correction_target_state or
                                        "UNRESOLVED").upper())
            if a.correction_target_state:
                corr.append("CORRECTION_TARGET_" +
                            a.correction_target_state.upper())
        res = res_by_entity.get(c.entity_key)
        profiles.append(CandidateEvidenceProfile(
            candidate_id=c.candidate_id,
            entity_key=c.entity_key,
            last_observed_present=c.last_observed_present,
            first_observed_absent=c.first_observed_absent,
            lifespan_months=c.lifespan_months,
            assertion_ids=tuple(a.assertion_id for a in my_asserts),
            assertion_types=tuple(types),
            assertion_stages=tuple(stages),
            participant_roles=tuple(roles),
            hr_resolution_state=(
                res.resolution_state if res else None),
            has_deregistration_recorded=(
                "DEREGISTRATION_RECORDED" in tset),
            has_merger_authorized="MERGER_AUTHORIZED" in tset,
            has_merger_registration=(
                "MERGER_REGISTRATION_RECORDED" in tset
                or "MERGER_REGISTERED" in tset),
            has_merger_executed="MERGER_EXECUTED" in tset,
            has_merger_renounced="MERGER_RENOUNCED" in tset,
            has_dissolution="DISSOLUTION_AGREED" in tset,
            has_liquidation="LIQUIDATION_EXECUTED" in tset,
            has_in_liquidation_marker=(
                "REGISTRY_NAME_IN_LIQUIDATION_MARKER" in tset),
            has_baja_marker="REGISTRY_NAME_BAJA_MARKER" in tset,
            has_transformation="TRANSFORMATION_RECORDED" in tset,
            has_rectification="RECTIFICATION_REPORTED" in tset,
            candidate_is_absorbed_participant=(
                ParticipantRole.ABSORBED.value in roles),
            candidate_is_absorbing_participant=(
                ParticipantRole.ABSORBING.value in roles),
            exact_successor_ids=tuple(sorted(successors)),
            exact_predecessor_ids=tuple(sorted(predecessors)),
            earliest_assertion_datetime=dts[0] if dts else None,
            latest_assertion_datetime=dts[-1] if dts else None,
            explicit_effective_date_count=eff,
            contradiction_flags=tuple(sorted(set(flags))),
            correction_flags=tuple(sorted(set(corr)))))
    return profiles


_SIGNATURE_FIELDS: tuple[tuple[str, str], ...] = (
    ("DEREG", "has_deregistration_recorded"),
    ("MERGER_AUTH", "has_merger_authorized"),
    ("MERGER_REG", "has_merger_registration"),
    ("MERGER_EXEC", "has_merger_executed"),
    ("MERGER_REN", "has_merger_renounced"),
    ("DISSOLUTION", "has_dissolution"),
    ("LIQUIDATION", "has_liquidation"),
    ("IN_LIQ", "has_in_liquidation_marker"),
    ("BAJA_MK", "has_baja_marker"),
    ("TRANSFORM", "has_transformation"),
    ("RECTIF", "has_rectification"),
    ("ABSORBED", "candidate_is_absorbed_participant"),
    ("ABSORBING", "candidate_is_absorbing_participant"),
)


def evidence_signature(p: CandidateEvidenceProfile) -> str:
    """Deterministic categorical signature — ignores text, timestamps,
    ordering. Drives G9-E complexity: count before designing rules."""
    bits = {name: int(getattr(p, field))
            for name, field in _SIGNATURE_FIELDS}
    n_succ = len(p.exact_successor_ids)
    succ_consistent = int(n_succ <= 1)
    conflict = int(bool(p.contradiction_flags))
    core = "|".join(f"{k}={v}" for k, v in bits.items())
    return (f"{core}|EXACT_SUCCESSORS={min(n_succ, 2)}"
            f"|SUCCESSOR_CONSISTENT={succ_consistent}"
            f"|CONFLICT={conflict}")


def profile_dict(p: CandidateEvidenceProfile) -> dict:
    """JSON-serializable profile incl. signature."""
    d = {k: (list(v) if isinstance(v, tuple) else v)
         for k, v in p.__dict__.items()}
    d["exact_successor_count"] = len(p.exact_successor_ids)
    d["evidence_signature"] = evidence_signature(p)
    return d


def profiles_fingerprint(profiles: list[CandidateEvidenceProfile]) -> str:
    return canonical_fingerprint(
        [profile_dict(p) for p in profiles])


def signature_distribution(
        profiles: list[CandidateEvidenceProfile]) -> Counter:
    return Counter(evidence_signature(p) for p in profiles)


def merger_paths(
        profiles: list[CandidateEvidenceProfile]) -> Counter:
    """Merger evidence-path per candidate (§6)."""
    paths: Counter[str] = Counter()
    for p in profiles:
        has_m = (p.has_merger_authorized or p.has_merger_registration
                 or p.has_merger_executed or p.has_merger_renounced)
        if not has_m:
            continue
        parts = []
        if p.has_merger_authorized:
            parts.append("AUTHORIZED")
        if p.has_merger_registration:
            parts.append("REGISTERED")
        if p.has_merger_executed:
            parts.append("EXECUTED")
        if p.has_merger_renounced:
            parts.append("RENOUNCED")
        paths["->".join(parts) or "other"] += 1
    return paths


def successor_consistency(
        profiles: list[CandidateEvidenceProfile]) -> Counter:
    """§7 research states — never resolves conflicts."""
    out: Counter[str] = Counter()
    for p in profiles:
        n = len(p.exact_successor_ids)
        if n == 0:
            out["SUCCESSOR_ABSENT"] += 1
        elif n == 1:
            out["SUCCESSOR_SINGLE"] += 1
        else:
            out["SUCCESSOR_CONFLICT"] += 1
    return out
