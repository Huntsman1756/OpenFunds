"""G9-B — official lifecycle source-assertion ledger domain.

Three mandatory levels (docs/g9/ledger-contract.md):

    lifecycle_source_documents     one official acquired artifact
    lifecycle_source_observations  one recognizable registry/event unit
    lifecycle_assertions           zero-or-more per observation

plus entity resolutions (HR identity discovery) and candidate linkage.

These are SOURCE ASSERTIONS — what official documents say — never
adjudicated lifecycle events. AUTHORIZED stays AUTHORIZED; BAJA stays
BAJA; no canonical MERGED_INTO/LIQUIDATED is materialized here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256

PARSER = "cnmv_iic.lifecycle"
PARSER_VERSION = "1"
RULE_VERSION = "1"


class SourceFamily(StrEnum):
    WEEKLY_REGISTRY = "cnmv_weekly_registry"
    RELEVANT_INFORMATION = "cnmv_iic_relevant_information"
    FONDREGISTRO = "fondregistro"


class SourceRole(StrEnum):
    REGISTRO = "registro"
    BOLETIN_COMPLETO = "boletin_completo"
    ENTITY_SEARCH = "entity-search"
    ENTITY_HISTORY = "entity-history"
    REGISTRY_MONTHLY = "registry-monthly"


class Representation(StrEnum):
    STRUCTURED = "structured"
    PARTIALLY_STRUCTURED = "partially_structured"
    VERBATIM_ONLY = "verbatim_only"


class EntityResolutionState(StrEnum):
    EXACT_REGNUM_CORROBORATED = "EXACT_REGNUM_CORROBORATED"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"


class AssertionType(StrEnum):
    # weekly registry bulletin acts
    REGISTRATION_RECORDED = "REGISTRATION_RECORDED"
    DEREGISTRATION_RECORDED = "DEREGISTRATION_RECORDED"
    MERGER_REGISTRATION_RECORDED = "MERGER_REGISTRATION_RECORDED"
    NAME_CHANGE_REGISTRATION_RECORDED = (
        "NAME_CHANGE_REGISTRATION_RECORDED")
    OTHER_REGISTRY_ACT = "OTHER_REGISTRY_ACT"
    UNKNOWN_REGISTRY_ASSERTION = "UNKNOWN_REGISTRY_ASSERTION"
    # relevant-information assertions
    MERGER_REQUESTED = "MERGER_REQUESTED"
    MERGER_PROPOSED = "MERGER_PROPOSED"
    MERGER_AUTHORIZED = "MERGER_AUTHORIZED"
    MERGER_REGISTERED = "MERGER_REGISTERED"
    MERGER_EXECUTED = "MERGER_EXECUTED"
    MERGER_RENOUNCED = "MERGER_RENOUNCED"
    DISSOLUTION_AGREED = "DISSOLUTION_AGREED"
    LIQUIDATION_EXECUTED = "LIQUIDATION_EXECUTED"
    DEREGISTRATION_REPORTED = "DEREGISTRATION_REPORTED"
    TRANSFORMATION_RECORDED = "TRANSFORMATION_RECORDED"
    MANAGER_SUBSTITUTION_REPORTED = "MANAGER_SUBSTITUTION_REPORTED"
    DEPOSITARY_SUBSTITUTION_REPORTED = "DEPOSITARY_SUBSTITUTION_REPORTED"
    RECTIFICATION_REPORTED = "RECTIFICATION_REPORTED"
    OTHER_LIFECYCLE_ASSERTION = "OTHER_LIFECYCLE_ASSERTION"
    UNKNOWN_ASSERTION = "UNKNOWN_ASSERTION"
    # FONDREGISTRO denominacion markers
    REGISTRY_NAME_BAJA_MARKER = "REGISTRY_NAME_BAJA_MARKER"
    REGISTRY_NAME_IN_LIQUIDATION_MARKER = (
        "REGISTRY_NAME_IN_LIQUIDATION_MARKER")


class AssertionStage(StrEnum):
    REQUESTED = "REQUESTED"
    PROPOSED = "PROPOSED"
    AUTHORIZED = "AUTHORIZED"
    APPROVED = "APPROVED"
    REGISTERED = "REGISTERED"
    EXECUTED = "EXECUTED"
    RENOUNCED = "RENOUNCED"
    DISSOLUTION_AGREED = "DISSOLUTION_AGREED"
    LIQUIDATION_EXECUTED = "LIQUIDATION_EXECUTED"
    DEREGISTERED = "DEREGISTERED"
    TRANSFORMATION_RECORDED = "TRANSFORMATION_RECORDED"
    REPORTED = "REPORTED"
    UNKNOWN_STAGE = "UNKNOWN_STAGE"


class AssertedDateSemantics(StrEnum):
    EFFECTIVE_DATE = "EFFECTIVE_DATE"
    EXECUTION_DATE = "EXECUTION_DATE"
    AUTHORIZATION_DATE = "AUTHORIZATION_DATE"
    REGISTRATION_DATE = "REGISTRATION_DATE"
    DISSOLUTION_DATE = "DISSOLUTION_DATE"
    LIQUIDATION_DATE = "LIQUIDATION_DATE"
    SOURCE_BAJA_MARKER_DATE = "SOURCE_BAJA_MARKER_DATE"
    OTHER_EXPLICIT_DATE = "OTHER_EXPLICIT_DATE"


class IdentityState(StrEnum):
    EXACT_REGISTER_NUMBER = "exact_register_number"
    UNRESOLVED = "unresolved"


class CorrectionTargetState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"


class LinkState(StrEnum):
    EXACT_SUBJECT_REGNUM = "EXACT_SUBJECT_REGNUM"
    EXACT_OBJECT_REGNUM = "EXACT_OBJECT_REGNUM"
    AMBIGUOUS = "AMBIGUOUS"


def _h(*parts: str) -> str:
    return sha256("|".join(parts).encode()).hexdigest()[:20]


def make_source_document_id(
        family: str, logical_key: str, raw_sha256: str) -> str:
    return "ldoc-" + _h("g9b-doc", family, logical_key, raw_sha256)


def make_source_observation_id(
        document_id: str, locator: str, seq: int) -> str:
    return "lobs-" + _h("g9b-obs", document_id, locator, str(seq))


def make_assertion_id(
        observation_id: str, atype: str, subject: str, obj: str,
        seq: int) -> str:
    return "lass-" + _h(
        "g9b-ass", observation_id, atype, subject, obj, str(seq))


def make_candidate_id(
        candidate_type: str, fund_key: str, prev: str, curr: str) -> str:
    """Same deterministic id used by the G9-A measurement."""
    return sha256(
        f"{candidate_type}|{fund_key}|{prev}|{curr}".encode()
    ).hexdigest()[:16]


@dataclass(frozen=True)
class LifecycleSourceDocument:
    source_document_id: str
    source_family: str
    logical_source_key: str
    source_role: str
    source_url: str
    publication_date: str | None       # ISO date — bulletin week end / FONDREG period end
    publication_datetime: str | None
    retrieved_at: str
    raw_sha256: str
    content_type: str | None
    size_bytes: int
    artifact_id: str
    supersedes_document_id: str | None
    parser_eligible: bool
    week_label: str | None = None      # bulletin "dd/mm/yyyy al dd/mm/yyyy"


@dataclass(frozen=True)
class LifecycleSourceObservation:
    source_observation_id: str
    source_document_id: str
    source_family: str
    logical_source_key: str
    source_section_raw: str | None
    subject_name_raw: str | None
    subject_register_number_raw: str | None
    regnums_in_text: str               # JSON list, verbatim order
    successor_regnums: str             # JSON list — ', por <fund>' clause
    entity_name_raw: str | None
    entity_nif: str | None
    entity_resolution_state: str | None
    resolved_fund_key: str | None
    official_event_registration_number: str | None
    publication_datetime: str | None
    category_raw: str | None
    observation_text_verbatim: str
    attachment_url: str | None
    source_locator: str
    correction_indicator: bool
    representation: str
    parser: str
    parser_version: str


@dataclass(frozen=True)
class LifecycleAssertion:
    assertion_id: str
    source_observation_id: str
    source_document_id: str
    source_family: str
    assertion_type: str
    assertion_stage: str
    subject_key: str | None            # FI:<regnum> when unambiguous
    subject_identifier_type: str | None
    subject_identifier_raw: str | None
    object_key: str | None             # FI:<regnum> exact domestic only
    object_identifier_type: str | None
    object_identifier_raw: str | None
    asserted_date: str | None          # explicit official date only
    asserted_date_semantics: str | None
    publication_datetime: str | None
    raw_text: str
    source_locator: str
    identity_state: str
    representation: str
    correction_of_observation_id: str | None
    supersedes_assertion_id: str | None
    correction_target_state: str | None
    parser_version: str
    rule_version: str


@dataclass(frozen=True)
class EntityResolution:
    """HR identity discovery: fund_key -> denominacion -> NIF."""
    entity_key: str                    # fund_key
    candidate_id: str
    denominacion_used: str
    entity_nif: str | None
    nif_candidates: str                # JSON list of NIFs seen
    resolution_state: str
    corroboration: str | None          # event_prose | entity_header | none
    search_document_id: str | None
    parser_version: str


@dataclass(frozen=True)
class CandidateEvidenceLink:
    candidate_id: str
    entity_key: str
    assertion_id: str
    source_observation_id: str
    source_document_id: str
    link_state: str
    parser_version: str
    rule_version: str


@dataclass(frozen=True)
class DisappearanceCandidate:
    """Observational FUND_DISAPPEARED candidate (G9-A grain)."""
    candidate_id: str
    candidate_type: str
    entity_key: str
    previous_observed_period: str
    current_observed_period: str
    last_observed_present: str
    first_observed_absent: str
    previous_artifact_id: str | None
    previous_locator: str | None
    entity_type: str
    denominacion: str | None
    manager_register_number: str | None
    lifespan_months: int
