"""G9-B — lifecycle source-assertion ledger parquet schemas + writer.

Mirrors storage.py conventions: pyarrow schemas, deterministic row
sorting, canonical fingerprints independent of parquet metadata.

Five tables, three mandatory levels plus resolutions/links:

    lifecycle_source_documents      official acquired artifact
    lifecycle_source_observations   recognizable registry/event unit
    lifecycle_assertions            descriptive source assertions
    lifecycle_entity_resolutions    HR identity discovery results
    lifecycle_candidate_links       candidate_id -> assertion linkage
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa

from cnmv_iic.lifecycle import (
    AssertionParticipant,
    CandidateEvidenceLink,
    DisappearanceCandidate,
    EntityResolution,
    LifecycleAssertion,
    LifecycleSourceDocument,
    LifecycleSourceObservation,
)
from cnmv_iic.lifecycle_adjudicate import LifecycleAdjudicationRow, LineageEdge
from cnmv_iic.storage import _write_table, canonical_fingerprint
from cnmv_iic.versions import contract

SOURCE_DOCUMENTS_SCHEMA = pa.schema([
    ("source_document_id", pa.string()),
    ("source_family", pa.string()),
    ("logical_source_key", pa.string()),
    ("source_role", pa.string()),
    ("source_url", pa.string()),
    ("publication_date", pa.string()),
    ("publication_datetime", pa.string()),
    ("retrieved_at", pa.string()),
    ("raw_sha256", pa.string()),
    ("content_type", pa.string()),
    ("size_bytes", pa.int64()),
    ("artifact_id", pa.string()),
    ("supersedes_document_id", pa.string()),
    ("parser_eligible", pa.bool_()),
    ("week_label", pa.string()),
])

SOURCE_OBSERVATIONS_SCHEMA = pa.schema([
    ("source_observation_id", pa.string()),
    ("source_document_id", pa.string()),
    ("source_family", pa.string()),
    ("logical_source_key", pa.string()),
    ("source_section_raw", pa.string()),
    ("subject_name_raw", pa.string()),
    ("subject_register_number_raw", pa.string()),
    ("regnums_in_text", pa.string()),
    ("successor_regnums", pa.string()),
    ("entity_name_raw", pa.string()),
    ("entity_nif", pa.string()),
    ("entity_resolution_state", pa.string()),
    ("resolved_fund_key", pa.string()),
    ("official_event_registration_number", pa.string()),
    ("publication_datetime", pa.string()),
    ("category_raw", pa.string()),
    ("observation_text_verbatim", pa.string()),
    ("attachment_url", pa.string()),
    ("source_locator", pa.string()),
    ("correction_indicator", pa.bool_()),
    ("representation", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

ASSERTIONS_SCHEMA = pa.schema([
    ("assertion_id", pa.string()),
    ("source_observation_id", pa.string()),
    ("source_document_id", pa.string()),
    ("source_family", pa.string()),
    ("assertion_type", pa.string()),
    ("assertion_stage", pa.string()),
    ("subject_key", pa.string()),
    ("subject_identifier_type", pa.string()),
    ("subject_identifier_raw", pa.string()),
    ("object_key", pa.string()),
    ("object_identifier_type", pa.string()),
    ("object_identifier_raw", pa.string()),
    ("asserted_date", pa.string()),
    ("asserted_date_semantics", pa.string()),
    ("publication_datetime", pa.string()),
    ("raw_text", pa.string()),
    ("source_locator", pa.string()),
    ("identity_state", pa.string()),
    ("representation", pa.string()),
    ("correction_of_observation_id", pa.string()),
    ("supersedes_assertion_id", pa.string()),
    ("correction_target_state", pa.string()),
    ("parser_version", pa.string()),
    ("rule_version", pa.string()),
])

ENTITY_RESOLUTIONS_SCHEMA = pa.schema([
    ("entity_key", pa.string()),
    ("candidate_id", pa.string()),
    ("denominacion_used", pa.string()),
    ("entity_nif", pa.string()),
    ("nif_candidates", pa.string()),
    ("resolution_state", pa.string()),
    ("corroboration", pa.string()),
    ("search_document_id", pa.string()),
    ("parser_version", pa.string()),
])

ASSERTION_PARTICIPANTS_SCHEMA = pa.schema([
    ("participant_id", pa.string()),
    ("assertion_id", pa.string()),
    ("source_observation_id", pa.string()),
    ("source_document_id", pa.string()),
    ("participant_ordinal", pa.int64()),
    ("participant_key", pa.string()),
    ("participant_identifier_scheme", pa.string()),
    ("participant_identifier_raw", pa.string()),
    ("participant_name_raw", pa.string()),
    ("participant_role", pa.string()),
    ("identity_state", pa.string()),
    ("source_locator", pa.string()),
])

ADJUDICATIONS_SCHEMA = pa.schema([
    ("adjudication_id", pa.string()),
    ("candidate_id", pa.string()),
    ("entity_key", pa.string()),
    ("adjudication", pa.string()),
    ("successor_key", pa.string()),
    ("rule_id", pa.string()),
    ("engine_version", pa.string()),
    ("evidence_signature", pa.string()),
    ("evidence_profile_id", pa.string()),
    ("authorization_assertion_ids", pa.string()),
    ("registration_assertion_ids", pa.string()),
    ("deregistration_assertion_ids", pa.string()),
    ("execution_assertion_ids", pa.string()),
    ("participant_assertion_ids", pa.string()),
    ("cross_source_corroborated", pa.bool_()),
    ("authorization_date", pa.string()),
    ("registration_date", pa.string()),
    ("deregistration_date", pa.string()),
    ("execution_date", pa.string()),
    ("source_artifact_ids", pa.string()),
    ("flags", pa.string()),
    ("adjudicated_at_build", pa.string()),
])

LINEAGE_EDGES_SCHEMA = pa.schema([
    ("edge_id", pa.string()),
    ("from_entity_key", pa.string()),
    ("to_entity_key", pa.string()),
    ("edge_type", pa.string()),
    ("evidence_state", pa.string()),
    ("rule_id", pa.string()),
    ("engine_version", pa.string()),
    ("candidate_id", pa.string()),
    ("source_assertion_ids", pa.string()),
])

CANDIDATE_LINKS_SCHEMA = pa.schema([
    ("candidate_id", pa.string()),
    ("entity_key", pa.string()),
    ("assertion_id", pa.string()),
    ("source_observation_id", pa.string()),
    ("source_document_id", pa.string()),
    ("link_state", pa.string()),
    ("parser_version", pa.string()),
    ("rule_version", pa.string()),
])

CANDIDATES_SCHEMA = pa.schema([
    ("candidate_id", pa.string()),
    ("candidate_type", pa.string()),
    ("entity_key", pa.string()),
    ("previous_observed_period", pa.string()),
    ("current_observed_period", pa.string()),
    ("last_observed_present", pa.string()),
    ("first_observed_absent", pa.string()),
    ("previous_artifact_id", pa.string()),
    ("previous_locator", pa.string()),
    ("entity_type", pa.string()),
    ("denominacion", pa.string()),
    ("manager_register_number", pa.string()),
    ("lifespan_months", pa.int64()),
])


def document_rows(docs: list[LifecycleSourceDocument]) -> list[dict]:
    return [{
        "source_document_id": d.source_document_id,
        "source_family": d.source_family,
        "logical_source_key": d.logical_source_key,
        "source_role": d.source_role,
        "source_url": d.source_url,
        "publication_date": d.publication_date,
        "publication_datetime": d.publication_datetime,
        "retrieved_at": d.retrieved_at,
        "raw_sha256": d.raw_sha256,
        "content_type": d.content_type,
        "size_bytes": d.size_bytes,
        "artifact_id": d.artifact_id,
        "supersedes_document_id": d.supersedes_document_id,
        "parser_eligible": d.parser_eligible,
        "week_label": d.week_label,
    } for d in sorted(
        docs, key=lambda d: (
            d.source_family, d.logical_source_key, d.source_document_id))]


def observation_rows(
        obs: list[LifecycleSourceObservation]) -> list[dict]:
    return [{
        "source_observation_id": o.source_observation_id,
        "source_document_id": o.source_document_id,
        "source_family": o.source_family,
        "logical_source_key": o.logical_source_key,
        "source_section_raw": o.source_section_raw,
        "subject_name_raw": o.subject_name_raw,
        "subject_register_number_raw": o.subject_register_number_raw,
        "regnums_in_text": o.regnums_in_text,
        "successor_regnums": o.successor_regnums,
        "entity_name_raw": o.entity_name_raw,
        "entity_nif": o.entity_nif,
        "entity_resolution_state": o.entity_resolution_state,
        "resolved_fund_key": o.resolved_fund_key,
        "official_event_registration_number":
            o.official_event_registration_number,
        "publication_datetime": o.publication_datetime,
        "category_raw": o.category_raw,
        "observation_text_verbatim": o.observation_text_verbatim,
        "attachment_url": o.attachment_url,
        "source_locator": o.source_locator,
        "correction_indicator": o.correction_indicator,
        "representation": o.representation,
        "parser": o.parser,
        "parser_version": o.parser_version,
    } for o in sorted(
        obs, key=lambda o: (
            o.source_document_id, o.source_locator,
            o.source_observation_id))]


def assertion_rows(
        assertions: list[LifecycleAssertion]) -> list[dict]:
    return [{
        "assertion_id": a.assertion_id,
        "source_observation_id": a.source_observation_id,
        "source_document_id": a.source_document_id,
        "source_family": a.source_family,
        "assertion_type": a.assertion_type,
        "assertion_stage": a.assertion_stage,
        "subject_key": a.subject_key,
        "subject_identifier_type": a.subject_identifier_type,
        "subject_identifier_raw": a.subject_identifier_raw,
        "object_key": a.object_key,
        "object_identifier_type": a.object_identifier_type,
        "object_identifier_raw": a.object_identifier_raw,
        "asserted_date": a.asserted_date,
        "asserted_date_semantics": a.asserted_date_semantics,
        "publication_datetime": a.publication_datetime,
        "raw_text": a.raw_text,
        "source_locator": a.source_locator,
        "identity_state": a.identity_state,
        "representation": a.representation,
        "correction_of_observation_id": a.correction_of_observation_id,
        "supersedes_assertion_id": a.supersedes_assertion_id,
        "correction_target_state": a.correction_target_state,
        "parser_version": a.parser_version,
        "rule_version": a.rule_version,
    } for a in sorted(assertions, key=lambda a: a.assertion_id)]


def entity_resolution_rows(
        res: list[EntityResolution]) -> list[dict]:
    return [{
        "entity_key": r.entity_key,
        "candidate_id": r.candidate_id,
        "denominacion_used": r.denominacion_used,
        "entity_nif": r.entity_nif,
        "nif_candidates": r.nif_candidates,
        "resolution_state": r.resolution_state,
        "corroboration": r.corroboration,
        "search_document_id": r.search_document_id,
        "parser_version": r.parser_version,
    } for r in sorted(res, key=lambda r: (r.entity_key, r.candidate_id))]


def participant_rows(
        parts: list[AssertionParticipant]) -> list[dict]:
    return [{
        "participant_id": p.participant_id,
        "assertion_id": p.assertion_id,
        "source_observation_id": p.source_observation_id,
        "source_document_id": p.source_document_id,
        "participant_ordinal": p.participant_ordinal,
        "participant_key": p.participant_key,
        "participant_identifier_scheme": p.participant_identifier_scheme,
        "participant_identifier_raw": p.participant_identifier_raw,
        "participant_name_raw": p.participant_name_raw,
        "participant_role": p.participant_role,
        "identity_state": p.identity_state,
        "source_locator": p.source_locator,
    } for p in sorted(
        parts, key=lambda p: (p.assertion_id, p.participant_ordinal))]


def adjudication_rows(
        rows: list[LifecycleAdjudicationRow]) -> list[dict]:
    return [r.__dict__.copy() for r in sorted(
        rows, key=lambda r: r.candidate_id)]


def lineage_edge_rows(edges: list[LineageEdge]) -> list[dict]:
    return [e.__dict__.copy() for e in sorted(
        edges, key=lambda e: e.edge_id)]


def candidate_link_rows(
        links: list[CandidateEvidenceLink]) -> list[dict]:
    return [{
        "candidate_id": lk.candidate_id,
        "entity_key": lk.entity_key,
        "assertion_id": lk.assertion_id,
        "source_observation_id": lk.source_observation_id,
        "source_document_id": lk.source_document_id,
        "link_state": lk.link_state,
        "parser_version": lk.parser_version,
        "rule_version": lk.rule_version,
    } for lk in sorted(
        links, key=lambda lk: (lk.candidate_id, lk.assertion_id))]


def candidate_rows(
        cands: list[DisappearanceCandidate]) -> list[dict]:
    return [{
        "candidate_id": c.candidate_id,
        "candidate_type": c.candidate_type,
        "entity_key": c.entity_key,
        "previous_observed_period": c.previous_observed_period,
        "current_observed_period": c.current_observed_period,
        "last_observed_present": c.last_observed_present,
        "first_observed_absent": c.first_observed_absent,
        "previous_artifact_id": c.previous_artifact_id,
        "previous_locator": c.previous_locator,
        "entity_type": c.entity_type,
        "denominacion": c.denominacion,
        "manager_register_number": c.manager_register_number,
        "lifespan_months": c.lifespan_months,
    } for c in sorted(cands, key=lambda c: c.candidate_id)]


def write_lifecycle(
        dataset_root: Path | str,
        *,
        documents: list[LifecycleSourceDocument],
        observations: list[LifecycleSourceObservation],
        assertions: list[LifecycleAssertion],
        entity_resolutions: list[EntityResolution],
        candidate_links: list[CandidateEvidenceLink],
        candidates: list[DisappearanceCandidate],
        participants: list[AssertionParticipant] | None = None,
        adjudications: list[LifecycleAdjudicationRow] | None = None,
        lineage_edges: list[LineageEdge] | None = None,
) -> dict:
    """Write the lifecycle ledger to ``lifecycle/`` parquet tables and
    return fingerprints + counts. Pure function — callers supply all
    rows; no network, no clocks."""
    root = Path(dataset_root) / "lifecycle"
    drow = document_rows(documents)
    orow = observation_rows(observations)
    arow = assertion_rows(assertions)
    rrow = entity_resolution_rows(entity_resolutions)
    lrow = candidate_link_rows(candidate_links)
    crow = candidate_rows(candidates)
    prow = participant_rows(participants or [])
    _write_table(
        drow, SOURCE_DOCUMENTS_SCHEMA,
        root / "source_documents" / "part-0.parquet")
    _write_table(
        orow, SOURCE_OBSERVATIONS_SCHEMA,
        root / "source_observations" / "part-0.parquet")
    _write_table(
        arow, ASSERTIONS_SCHEMA,
        root / "assertions" / "part-0.parquet")
    _write_table(
        rrow, ENTITY_RESOLUTIONS_SCHEMA,
        root / "entity_resolutions" / "part-0.parquet")
    _write_table(
        lrow, CANDIDATE_LINKS_SCHEMA,
        root / "candidate_links" / "part-0.parquet")
    _write_table(
        crow, CANDIDATES_SCHEMA,
        root / "candidates" / "part-0.parquet")
    _write_table(
        prow, ASSERTION_PARTICIPANTS_SCHEMA,
        root / "assertion_participants" / "part-0.parquet")
    adjrow = adjudication_rows(adjudications or [])
    edgrow = lineage_edge_rows(lineage_edges or [])
    _write_table(
        adjrow, ADJUDICATIONS_SCHEMA,
        root / "adjudications" / "part-0.parquet")
    _write_table(
        edgrow, LINEAGE_EDGES_SCHEMA,
        Path(dataset_root) / "lineage" / "edges" / "part-0.parquet")
    manifest = {
        "documents": len(drow),
        "observations": len(orow),
        "assertions": len(arow),
        "entity_resolutions": len(rrow),
        "candidate_links": len(lrow),
        "candidates": len(crow),
        "assertion_participants": len(prow),
        "adjudications": len(adjrow),
        "lineage_edges": len(edgrow),
        "ledger_fingerprint": canonical_fingerprint(
            drow, orow, arow, rrow, lrow),
        "participants_fingerprint": canonical_fingerprint(prow),
        "adjudications_fingerprint": canonical_fingerprint(adjrow),
        "lineage_edges_fingerprint": canonical_fingerprint(edgrow),
        "candidates_fingerprint": canonical_fingerprint(crow),
        "versions": contract(),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest
