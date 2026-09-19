"""G9-E — adjudication engine rule tests (preregistered R1–R7)."""
from __future__ import annotations

from cnmv_iic.lifecycle import AssertionParticipant
from cnmv_iic.lifecycle_adjudicate import adjudicate, check_invariants, records_fingerprint
from cnmv_iic.lifecycle_research import CandidateEvidenceProfile


def _prof(**kw) -> CandidateEvidenceProfile:
    base = dict(
        candidate_id="c1", entity_key="FI:111",
        last_observed_present="2012-01", first_observed_absent="2012-02",
        lifespan_months=12,
        assertion_ids=(),
        assertion_types=("MERGER_AUTHORIZED",
                         "MERGER_REGISTRATION_RECORDED"),
        assertion_stages=(),
        participant_roles=(), hr_resolution_state=None,
        has_deregistration_recorded=True,
        has_merger_authorized=True, has_merger_registration=True,
        has_merger_executed=False, has_merger_renounced=False,
        has_dissolution=False, has_liquidation=False,
        has_in_liquidation_marker=False, has_baja_marker=False,
        has_transformation=False, has_rectification=False,
        candidate_is_absorbed_participant=True,
        candidate_is_absorbing_participant=False,
        exact_successor_ids=("999",), exact_predecessor_ids=(),
        earliest_assertion_datetime=None, latest_assertion_datetime=None,
        explicit_effective_date_count=0,
        contradiction_flags=(), correction_flags=())
    base.update(kw)
    return CandidateEvidenceProfile(**base)


def test_absorbed_by_single_successor() -> None:
    recs = adjudicate([_prof()], [], [])
    assert recs[0].outcome == "ADJUDICATED_ABSORBED_BY"
    assert recs[0].successor_key == "FI:999"
    assert recs[0].rule_id == "R4"


def test_multi_successor_never_adjudicated() -> None:
    recs = adjudicate([_prof(
        exact_successor_ids=("888", "999"),
        contradiction_flags=("MULTI_SUCCESSOR",))], [], [])
    assert recs[0].outcome == "INDETERMINATE_MULTIPLE_SUCCESSORS"
    assert recs[0].successor_key is None


def test_no_successor_not_forced() -> None:
    recs = adjudicate([_prof(
        exact_successor_ids=(),
        contradiction_flags=("MERGER_AND_BAJA_NO_SUCCESSOR",))], [], [])
    assert recs[0].outcome == "INDETERMINATE_NO_SUCCESSOR"


def test_renunciation_blocks_adjudication() -> None:
    recs = adjudicate([_prof(has_merger_renounced=True)], [], [])
    assert recs[0].outcome == "INDETERMINATE_CORRECTION_OR_RENUNCIATION"


def test_rectification_blocks_adjudication() -> None:
    recs = adjudicate([_prof(has_rectification=True)], [], [])
    assert recs[0].outcome == "INDETERMINATE_CORRECTION_OR_RENUNCIATION"


def test_merger_plus_liquidation_conflict() -> None:
    recs = adjudicate([_prof(
        has_liquidation=True,
        exact_successor_ids=(),
        contradiction_flags=("MERGER_PLUS_DISSOLUTION",))], [], [])
    assert recs[0].outcome == "INDETERMINATE_CONFLICTING_EVIDENCE"


def test_liquidation_adjudicated_without_merger() -> None:
    recs = adjudicate([_prof(
        assertion_types=(),
        has_merger_authorized=False, has_merger_registration=False,
        candidate_is_absorbed_participant=False,
        exact_successor_ids=(),
        has_in_liquidation_marker=True)], [], [])
    assert recs[0].outcome == "ADJUDICATED_LIQUIDATED"
    assert recs[0].rule_id == "R6"


def test_unknown_exit_residual() -> None:
    recs = adjudicate([_prof(
        assertion_types=(),
        has_merger_authorized=False, has_merger_registration=False,
        candidate_is_absorbed_participant=False,
        exact_successor_ids=())], [], [])
    assert recs[0].outcome == "UNKNOWN_EXIT"


def test_conservation_and_determinism() -> None:
    succ = AssertionParticipant(
        participant_id="lpar-1", assertion_id="a1",
        source_observation_id="o1", source_document_id="d1",
        participant_ordinal=0, participant_key="FI:999",
        participant_identifier_scheme="cnmv_register_number",
        participant_identifier_raw="999", participant_name_raw=None,
        participant_role="ABSORBING",
        identity_state="exact_register_number", source_locator="")
    profs = [_prof(candidate_id="c2"), _prof(candidate_id="c1",
             assertion_types=(),
             exact_successor_ids=(), has_merger_authorized=False,
             has_merger_registration=False,
             candidate_is_absorbed_participant=False)]
    r1 = adjudicate(profs, [], [succ])
    r2 = adjudicate(list(reversed(profs)), [], [succ])
    assert records_fingerprint(r1) == records_fingerprint(r2)
    assert {r.candidate_id for r in r1} == {"c1", "c2"}
    inv = check_invariants(r1, profs, [succ])
    assert all(v == 0 for v in inv.values())
