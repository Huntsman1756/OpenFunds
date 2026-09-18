"""GLEIF Golden Copy adapters (G7-B): LEI-CDF 3.1, RR-CDF 2.1, Repex 2.1.

Streaming extractors filtered by a wanted-LEI set — cnmv-iic is not a
GLEIF replica; only entities reachable from resolution evidence plus the
bounded one-hop closure over relationship end nodes are materialized.

Contract (docs/g7/contract.md + user gates):
- relationship_type / relationship_status / exception vocabulary are
  verbatim GLEIF — IS_FUND-MANAGED_BY and IS_SUBFUND_OF are never
  renamed to a generic "parent".
- Reporting exceptions are rows, not NULLs; absence of an RR record is
  NOT absence of a parent.
- relationship_periods are preserved, never reduced to a single as_of.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator

from lxml import etree

from cnmv_iic.domain import (
    LegalEntityObservation,
    RelationshipExceptionObservation,
    RelationshipObservation,
)
from cnmv_iic.errors import ParseError

PARSER = "cnmv_iic.adapters.gleif_golden"
PARSER_VERSION = "1"
PROVIDER = "gleif"
DATASET_LEI = "lei-cdf-3.1"
DATASET_RR = "rr-cdf-2.1"
DATASET_REPEX = "repex-2.1"

_MEMBER_RE = re.compile(
    r"(\d{8})-gleif-concatenated-file-(lei2|rr|repex)\.xml$")
_KIND_DATASET = {"lei2": DATASET_LEI, "rr": DATASET_RR,
                 "repex": DATASET_REPEX}


def member_info(zf: zipfile.ZipFile, kind: str) -> tuple[str, str]:
    """(member_name, snapshot_date) for the expected file kind."""
    names = [n for n in zf.namelist()
             if (m := _MEMBER_RE.search(n)) and m.group(2) == kind]
    if len(names) != 1:
        raise ParseError(
            f"expected exactly one *-gleif-concatenated-file-{kind}.xml "
            f"member, found {len(names)}")
    d = _MEMBER_RE.search(names[0]).group(1)  # type: ignore[union-attr]
    return names[0], f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def _t(el: etree._Element, path: str) -> str | None:
    child = el.find(path)
    if child is None or child.text is None:
        return None
    v = child.text.strip()
    return v or None


def _addr(el: etree._Element | None) -> dict | None:
    if el is None:
        return None
    return {
        "first_address_line": _t(el, "{*}FirstAddressLine"),
        "additional_address_line": _t(el, "{*}AdditionalAddressLine"),
        "additional_address_line2": _t(el, "{*}AdditionalAddressLine2"),
        "additional_address_line3": _t(el, "{*}AdditionalAddressLine3"),
        "city": _t(el, "{*}City"),
        "region": _t(el, "{*}Region"),
        "country": _t(el, "{*}Country"),
        "postal_code": _t(el, "{*}PostalCode"),
    }


def parse_lei_record(el: etree._Element) -> dict:
    """LEI-CDF 3.1 LEIRecord -> verbatim field dict."""
    ent = el.find("{*}Entity")
    reg = el.find("{*}Registration")
    other = [
        {"name": (o.text or "").strip(), "lang": o.get("{*}lang"),
         "type": o.get("type")}
        for o in el.findall("{*}Entity/{*}OtherEntityNames/{*}OtherEntityName")
    ]
    lf = el.find("{*}Entity/{*}LegalForm")
    va = reg.find("{*}ValidationAuthority") if reg is not None else None
    ra = ent.find("{*}RegistrationAuthority") if ent is not None else None
    rec = {
        "lei": _t(el, "{*}LEI"),
        "legal_name": _t(ent, "{*}LegalName") if ent is not None else None,
        "legal_name_lang": (
            ent.find("{*}LegalName").get("{*}lang")
            if ent is not None and ent.find("{*}LegalName") is not None
            else None),
        "other_names": other,
        "legal_address": _addr(
            ent.find("{*}LegalAddress") if ent is not None else None),
        "headquarters_address": _addr(
            ent.find("{*}HeadquartersAddress") if ent is not None else None),
        "registration_authority": (
            {"id": _t(ra, "{*}RegistrationAuthorityID"),
             "entity_id": _t(ra, "{*}RegistrationAuthorityEntityID")}
            if ra is not None else None),
        "legal_jurisdiction": (
            _t(ent, "{*}LegalJurisdiction") if ent is not None else None),
        "entity_category": (
            _t(ent, "{*}EntityCategory") if ent is not None else None),
        "legal_form_code": (
            _t(lf, "{*}EntityLegalFormCode") if lf is not None else None),
        "other_legal_form": (
            _t(lf, "{*}OtherLegalForm") if lf is not None else None),
        "entity_status": (
            _t(ent, "{*}EntityStatus") if ent is not None else None),
        "entity_creation_date": (
            _t(ent, "{*}EntityCreationDate") if ent is not None else None),
        "entity_expiration_date": (
            _t(ent, "{*}EntityExpirationDate") if ent is not None else None),
        "registration": {
            "initial_registration_date": (
                _t(reg, "{*}InitialRegistrationDate")
                if reg is not None else None),
            "last_update_date": (
                _t(reg, "{*}LastUpdateDate") if reg is not None else None),
            "registration_status": (
                _t(reg, "{*}RegistrationStatus")
                if reg is not None else None),
            "next_renewal_date": (
                _t(reg, "{*}NextRenewalDate") if reg is not None else None),
            "managing_lou": (
                _t(reg, "{*}ManagingLOU") if reg is not None else None),
            "validation_sources": (
                _t(reg, "{*}ValidationSources")
                if reg is not None else None),
            "validation_authority": (
                {"id": _t(va, "{*}ValidationAuthorityID"),
                 "entity_id": _t(va, "{*}ValidationAuthorityEntityID")}
                if va is not None else None),
        },
    }
    return rec


def iter_lei_records(
    zf: zipfile.ZipFile, member: str, wanted: set[str],
) -> Iterator[tuple[int, dict]]:
    """Yield (record_ordinal, parsed record) for LEIs in ``wanted``."""
    ordinal = 0
    with zf.open(member) as f:
        for _ev, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname == "LEIRecord":
                ordinal += 1
                lei = _t(el, "{*}LEI")
                if lei in wanted:
                    yield ordinal, parse_lei_record(el)
                el.clear()


def parse_relationship_record(el: etree._Element) -> dict:
    rel = el.find("{*}Relationship")
    reg = el.find("{*}Registration")
    periods = [
        {"period_type": _t(p, "{*}PeriodType"),
         "start_date": _t(p, "{*}StartDate"),
         "end_date": _t(p, "{*}EndDate")}
        for p in el.findall(
            "{*}Relationship/{*}RelationshipPeriods/{*}RelationshipPeriod")
    ]
    qualifiers = [
        {"dimension": _t(q, "{*}QualifierDimension"),
         "category": _t(q, "{*}QualifierCategory")}
        for q in el.findall(
            "{*}Relationship/{*}RelationshipQualifiers/"
            "{*}RelationshipQualifier")
    ]
    quantifiers = [
        {"method": _t(q, "{*}MeasurementMethod"),
         "amount": _t(q, "{*}QuantifierAmount"),
         "units": _t(q, "{*}QuantifierUnits")}
        for q in el.findall(
            "{*}Relationship/{*}RelationshipQuantifiers/"
            "{*}RelationshipQuantifier")
    ]
    return {
        "start_lei": _t(rel, "{*}StartNode/{*}NodeID"),
        "start_node_type": _t(rel, "{*}StartNode/{*}NodeIDType"),
        "end_lei": _t(rel, "{*}EndNode/{*}NodeID"),
        "end_node_type": _t(rel, "{*}EndNode/{*}NodeIDType"),
        "relationship_type": _t(rel, "{*}RelationshipType"),
        "periods": periods,
        "status": _t(rel, "{*}RelationshipStatus"),
        "qualifiers": qualifiers,
        "quantifiers": quantifiers,
        "registration": {
            "registration_status": (
                _t(reg, "{*}RegistrationStatus")
                if reg is not None else None),
            "initial_registration_date": (
                _t(reg, "{*}InitialRegistrationDate")
                if reg is not None else None),
            "last_update_date": (
                _t(reg, "{*}LastUpdateDate") if reg is not None else None),
            "next_renewal_date": (
                _t(reg, "{*}NextRenewalDate") if reg is not None else None),
            "managing_lou": (
                _t(reg, "{*}ManagingLOU") if reg is not None else None),
            "validation_sources": (
                _t(reg, "{*}ValidationSources")
                if reg is not None else None),
            "validation_documents": (
                _t(reg, "{*}ValidationDocuments")
                if reg is not None else None),
            "validation_reference": (
                _t(reg, "{*}ValidationReference")
                if reg is not None else None),
        },
    }


def iter_relationships(
    zf: zipfile.ZipFile, member: str, wanted_starts: set[str],
) -> Iterator[tuple[int, dict]]:
    """Yield (record_ordinal, parsed record) where start LEI is wanted."""
    ordinal = 0
    with zf.open(member) as f:
        for _ev, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname == "RelationshipRecord":
                ordinal += 1
                start = _t(el, "{*}Relationship/{*}StartNode/{*}NodeID")
                if start in wanted_starts:
                    yield ordinal, parse_relationship_record(el)
                el.clear()


def iter_exceptions(
    zf: zipfile.ZipFile, member: str, wanted: set[str],
) -> Iterator[tuple[int, dict]]:
    """Yield (record_ordinal, {lei, category, reason}) for wanted LEIs."""
    ordinal = 0
    with zf.open(member) as f:
        for _ev, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname == "Exception":
                ordinal += 1
                lei = _t(el, "{*}LEI")
                if lei in wanted:
                    yield ordinal, {
                        "lei": lei,
                        "exception_category": _t(el, "{*}ExceptionCategory"),
                        "exception_reason": _t(el, "{*}ExceptionReason"),
                    }
                el.clear()


def build_entity_observation(
    rec: dict, *, role: str, snapshot_date: str, artifact_id: str,
    source_sha256: str, member_name: str, member_sha256: str,
    retrieved_at: str, ordinal: int,
) -> LegalEntityObservation:
    reg = rec["registration"]
    return LegalEntityObservation(
        entity_id=f"{PROVIDER}/{DATASET_LEI}/{snapshot_date}/{rec['lei']}",
        lei=rec["lei"],
        provider=PROVIDER,
        provider_dataset=DATASET_LEI,
        provider_snapshot_date=snapshot_date,
        provider_artifact_id=artifact_id,
        evidence_role=role,
        legal_name=rec["legal_name"],
        other_names_json=json.dumps(rec["other_names"], sort_keys=True),
        legal_address_json=json.dumps(
            rec["legal_address"], sort_keys=True),
        headquarters_address_json=json.dumps(
            rec["headquarters_address"], sort_keys=True),
        legal_jurisdiction=rec["legal_jurisdiction"],
        entity_category=rec["entity_category"],
        entity_status=rec["entity_status"],
        legal_form=rec["legal_form_code"] or rec["other_legal_form"],
        registration_status=reg["registration_status"],
        initial_registration_date=reg["initial_registration_date"],
        last_update_date=reg["last_update_date"],
        next_renewal_date=reg["next_renewal_date"],
        managing_lou=reg["managing_lou"],
        provider_record_locator=f"{member_name}#LEIRecord={ordinal}",
        raw_json=json.dumps(rec, sort_keys=True),
        retrieved_at=retrieved_at,
        source_sha256=source_sha256,
        member_name=member_name,
        member_sha256=member_sha256,
        parser=PARSER,
        parser_version=PARSER_VERSION,
    )


def build_relationship_observation(
    rec: dict, *, snapshot_date: str, artifact_id: str,
    source_sha256: str, member_name: str, member_sha256: str,
    retrieved_at: str, ordinal: int,
) -> RelationshipObservation:
    return RelationshipObservation(
        relationship_id=(
            f"{PROVIDER}/{DATASET_RR}/{snapshot_date}/"
            f"{rec['start_lei']}/{rec['relationship_type']}/"
            f"{rec['end_lei']}"),
        start_lei=rec["start_lei"],
        end_lei=rec["end_lei"],
        relationship_type=rec["relationship_type"],
        relationship_status=rec["status"],
        relationship_periods_json=json.dumps(
            rec["periods"], sort_keys=True),
        validation_sources=rec["registration"]["validation_sources"],
        registration_status=rec["registration"]["registration_status"],
        provider=PROVIDER,
        provider_dataset=DATASET_RR,
        provider_snapshot_date=snapshot_date,
        provider_artifact_id=artifact_id,
        provider_record_locator=(
            f"{member_name}#RelationshipRecord={ordinal}"),
        raw_json=json.dumps(rec, sort_keys=True),
        retrieved_at=retrieved_at,
        source_sha256=source_sha256,
        member_name=member_name,
        member_sha256=member_sha256,
        parser=PARSER,
        parser_version=PARSER_VERSION,
    )


def build_exception_observation(
    rec: dict, *, snapshot_date: str, artifact_id: str,
    source_sha256: str, member_name: str, member_sha256: str,
    retrieved_at: str, ordinal: int,
) -> RelationshipExceptionObservation:
    return RelationshipExceptionObservation(
        exception_id=(
            f"{PROVIDER}/{DATASET_REPEX}/{snapshot_date}/"
            f"{rec['lei']}/{rec['exception_category']}"),
        lei=rec["lei"],
        exception_category=rec["exception_category"],
        exception_reason=rec["exception_reason"],
        provider=PROVIDER,
        provider_dataset=DATASET_REPEX,
        provider_snapshot_date=snapshot_date,
        provider_artifact_id=artifact_id,
        provider_record_locator=f"{member_name}#Exception={ordinal}",
        raw_json=json.dumps(rec, sort_keys=True),
        retrieved_at=retrieved_at,
        source_sha256=source_sha256,
        member_name=member_name,
        member_sha256=member_sha256,
        parser=PARSER,
        parser_version=PARSER_VERSION,
    )
