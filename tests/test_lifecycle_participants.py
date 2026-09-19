"""G9-C — assertion participants + candidate evidence profiles."""
from __future__ import annotations

import json

from cnmv_iic.lifecycle import (
    DisappearanceCandidate,
    EntityResolution,
    LifecycleAssertion,
    LifecycleSourceObservation,
)
from cnmv_iic.lifecycle_ingest import assertion_participants
from cnmv_iic.lifecycle_research import evidence_profiles, profiles_fingerprint


def _obs(regs: list[str] | None = None,
         succ: list[str] | None = None,
         resolved: str | None = None,
         family: str = "cnmv_weekly_registry") -> LifecycleSourceObservation:
    return LifecycleSourceObservation(
        source_observation_id="lobs-x", source_document_id="ldoc-x",
        source_family=family, logical_source_key="k",
        source_section_raw=None, subject_name_raw="FONDO A",
        subject_register_number_raw=None,
        regnums_in_text=json.dumps(regs or []),
        successor_regnums=json.dumps(succ or []),
        entity_name_raw="FONDO A", entity_nif=None,
        entity_resolution_state=None, resolved_fund_key=resolved,
        official_event_registration_number=None,
        publication_datetime=None, category_raw=None,
        observation_text_verbatim="", attachment_url=None,
        source_locator="loc", correction_indicator=False,
        representation="structured", parser="t", parser_version="1")


def _assertion(
        atype: str = "MERGER_REGISTRATION_RECORDED",
        stage: str = "REGISTERED",
        subject: str | None = None, obj: str | None = None,
        aid: str = "lass-1") -> LifecycleAssertion:
    return LifecycleAssertion(
        assertion_id=aid,
        source_observation_id="lobs-x", source_document_id="ldoc-x",
        source_family="cnmv_weekly_registry",
        assertion_type=atype, assertion_stage=stage,
        subject_key=f"FI:{subject}" if subject else None,
        subject_identifier_type=(
            "cnmv_register_number" if subject else None),
        subject_identifier_raw=subject,
        object_key=f"FI:{obj}" if obj else None,
        object_identifier_type=(
            "cnmv_register_number" if obj else None),
        object_identifier_raw=obj,
        asserted_date=None, asserted_date_semantics=None,
        publication_datetime=None, raw_text="", source_locator="",
        identity_state="exact_register_number",
        representation="structured",
        correction_of_observation_id=None,
        supersedes_assertion_id=None, correction_target_state=None,
        parser_version="1", rule_version="1")


def _cand(cid: str = "c1", key: str = "FI:111") -> DisappearanceCandidate:
    return DisappearanceCandidate(
        candidate_id=cid, candidate_type="FUND_DISAPPEARED",
        entity_key=key, previous_observed_period="2012-01",
        current_observed_period="2012-02",
        last_observed_present="2012-01", first_observed_absent="2012-02",
        previous_artifact_id=None, previous_locator=None,
        entity_type="F", denominacion="FONDO A, FI",
        manager_register_number="1", lifespan_months=12)


def test_multiparty_merger_participants() -> None:
    obs = _obs(regs=["111", "112", "113"], succ=["999"])
    a = _assertion(subject="111", obj="999")
    parts = assertion_participants([a], [obs])
    roles = {p.participant_identifier_raw: p.participant_role
             for p in parts}
    assert roles == {"111": "ABSORBED", "112": "ABSORBED",
                     "113": "ABSORBED", "999": "ABSORBING"}
    assert all(p.participant_key == f"FI:{r}"
               for p, r in zip(parts, roles, strict=True))
    assert all(p.identity_state == "exact_register_number"
               for p in parts)


def test_executed_via_absorber_terse_text() -> None:
    """MERGER_EXECUTED with no text regnums: only the entity-context
    SUBJECT, never an inferred ABSORBING."""
    obs = _obs(resolved="FI:999", family="cnmv_iic_relevant_information")
    a = _assertion(atype="MERGER_EXECUTED", stage="EXECUTED",
                   subject=None, obj=None)
    parts = assertion_participants([a], [obs])
    assert len(parts) == 1
    assert parts[0].participant_role == "SUBJECT"
    assert parts[0].participant_key == "FI:999"
    assert parts[0].identity_state == "unresolved"


def test_entity_context_nonmerger_subject() -> None:
    """Unresolved HR event (e.g. dissolution) gets entity-context
    SUBJECT so the candidate can be measured as participant."""
    obs = _obs(resolved="FI:111", family="cnmv_iic_relevant_information")
    a = _assertion(atype="DISSOLUTION_AGREED", stage="REPORTED")
    a = LifecycleAssertion(**{**a.__dict__, "subject_key": None,
                              "subject_identifier_type": None,
                              "subject_identifier_raw": None,
                              "identity_state": "unresolved"})
    parts = assertion_participants([a], [obs])
    assert len(parts) == 1
    assert parts[0].participant_role == "SUBJECT"
    assert parts[0].participant_key == "FI:111"


def test_profile_absorbed_participant_not_subject() -> None:
    """Candidate 111 is ABSORBED in a merger whose subject is 999."""
    obs = _obs(regs=["111"], succ=["999"])
    a = _assertion(subject="999", obj=None)
    parts = assertion_participants([a], [obs])
    profs = evidence_profiles(
        [_cand("c1", "FI:111")], [a], parts, [], sealed=set())
    assert len(profs) == 1
    p = profs[0]
    assert p.candidate_is_absorbed_participant
    assert not p.candidate_is_absorbing_participant
    assert p.exact_successor_ids == ("999",)


def test_profile_multi_successor_conflict() -> None:
    o1 = _obs(regs=["111"], succ=["999"])
    a1 = _assertion(subject="999", aid="lass-1")
    o2 = _obs(regs=["111"], succ=["888"])
    o2 = LifecycleSourceObservation(
        **{**o2.__dict__, "source_observation_id": "lobs-y"})
    a2 = _assertion(subject="888", aid="lass-2")
    a2 = LifecycleAssertion(
        **{**a2.__dict__, "source_observation_id": "lobs-y"})
    parts = assertion_participants([a1, a2], [o1, o2])
    profs = evidence_profiles(
        [_cand("c1", "FI:111")], [a1, a2], parts, [], sealed=set())
    p = profs[0]
    assert set(p.exact_successor_ids) == {"888", "999"}
    assert "MULTI_SUCCESSOR" in p.contradiction_flags


def test_profile_conservation_and_holdout() -> None:
    cands = [_cand("c1", "FI:111"), _cand("sealed", "FI:222"),
             _cand("c3", "FI:333")]
    profs = evidence_profiles(cands, [], [], [], sealed={"sealed"})
    assert {p.candidate_id for p in profs} == {"c1", "c3"}
    # empty evidence still yields a profile
    assert all(p.assertion_ids == () for p in profs)


def test_signature_invariant_to_assertion_order() -> None:
    o1 = _obs(regs=["111"], succ=["999"])
    a1 = _assertion(subject="999", aid="lass-1")
    o2 = _obs(resolved="FI:111", family="cnmv_iic_relevant_information")
    o2 = LifecycleSourceObservation(
        **{**o2.__dict__, "source_observation_id": "lobs-z"})
    a2 = _assertion(atype="DEREGISTRATION_RECORDED", stage="REPORTED",
                    subject="111", aid="lass-3")
    a2 = LifecycleAssertion(
        **{**a2.__dict__, "source_observation_id": "lobs-z"})
    p1 = assertion_participants([a1, a2], [o1, o2])
    p2 = assertion_participants([a2, a1], [o2, o1])
    f1 = profiles_fingerprint(evidence_profiles(
        [_cand("c1", "FI:111")], [a1, a2], p1, [], sealed=set()))
    f2 = profiles_fingerprint(evidence_profiles(
        [_cand("c1", "FI:111")], [a2, a1], p2, [], sealed=set()))
    assert f1 == f2


def test_unrelated_assertion_does_not_change_profile() -> None:
    o1 = _obs(regs=["111"], succ=["999"])
    a1 = _assertion(subject="999", aid="lass-1")
    o2 = _obs(regs=["555"], succ=["666"])
    o2 = LifecycleSourceObservation(
        **{**o2.__dict__, "source_observation_id": "lobs-y"})
    a2 = _assertion(subject="666", aid="lass-2")
    a2 = LifecycleAssertion(
        **{**a2.__dict__, "source_observation_id": "lobs-y"})
    parts = assertion_participants([a1, a2], [o1, o2])
    base = evidence_profiles(
        [_cand("c1", "FI:111")], [a1], parts, [], sealed=set())
    with_other = evidence_profiles(
        [_cand("c1", "FI:111")], [a1, a2], parts, [], sealed=set())
    assert profiles_fingerprint(base) == profiles_fingerprint(with_other)


def test_renunciation_and_rectification_flags() -> None:
    o = _obs(resolved="FI:111", family="cnmv_iic_relevant_information")
    ren = _assertion(atype="MERGER_RENOUNCED", stage="RENOUNCED")
    auth = _assertion(atype="MERGER_AUTHORIZED", stage="AUTHORIZED",
                      aid="lass-2")
    auth = LifecycleAssertion(
        **{**auth.__dict__})
    parts = assertion_participants([ren, auth], [o, o])
    profs = evidence_profiles(
        [_cand("c1", "FI:111")], [ren, auth], parts, [], sealed=set())
    p = profs[0]
    assert p.has_merger_renounced and p.has_merger_authorized
    assert "RENOUNCED_WITH_OTHER_MERGER_EVIDENCE" in p.contradiction_flags


def test_unknown_role_for_extra_text_regnums() -> None:
    obs = _obs(regs=["777"], family="cnmv_weekly_registry")
    a = _assertion(atype="OTHER_REGISTRY_ACT", stage="REPORTED",
                   subject="111")
    parts = assertion_participants([a], [obs])
    roles = {p.participant_identifier_raw: p.participant_role
             for p in parts}
    assert roles == {"111": "SUBJECT", "777": "UNKNOWN"}


def test_resolution_state_recorded() -> None:
    res = EntityResolution(
        entity_key="FI:111", candidate_id="c1",
        denominacion_used="FONDO A", entity_nif="B1",
        nif_candidates='["B1"]',
        resolution_state="EXACT_REGNUM_CORROBORATED",
        corroboration="entity_header", search_document_id=None,
        parser_version="1")
    profs = evidence_profiles(
        [_cand("c1", "FI:111")], [], [], [res], sealed=set())
    assert profs[0].hr_resolution_state == "EXACT_REGNUM_CORROBORATED"
