"""ESMA FIRDS FULINS adapter (G7-C).

Streams pinned FULINS parts and extracts ``RefData`` records for the
corpus ISIN universe only — cnmv-iic is not a FIRDS replica.

Measured contract (docs/g7/oss-review.md + firds-lifecycle.md):
- record identity = ISIN x TradgVnRltdAttrbts/Id (venue MIC); 1..54
  records per ISIN — venue multiplicity is redundant evidence for ONE
  candidate, never N candidates.
- ``Issr`` is field 5 "issuer or operator of the trading venue" —
  preserved verbatim as ``firds_field5_issuer_or_venue_operator``,
  never normalized to ``isin_issuer_to_lei`` (C-type records point to
  subfund-level entities where GLEIF maps umbrellas).
- absence from the snapshot = ``no_match``, never ``not_applicable``.
"""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

from lxml import etree

from cnmv_iic.domain import (
    TEMPORAL_SEMANTICS,
    CandidateEvidence,
    ResolutionCandidate,
    ResolutionObservation,
    ResolutionState,
)
from cnmv_iic.errors import ParseError

PARSER = "cnmv_iic.adapters.firds_fulins"
PARSER_VERSION = "1"
PROVIDER = "esma_firds"
DATASET = "fulins"
SEMANTICS = "firds_field5_issuer_or_venue_operator"

_MEMBER_RE = re.compile(
    r"FULINS_([A-Z])_(\d{8})_(\d+)of(\d+)\.xml$")
_LEI_RE = re.compile(r"^[0-9A-Z]{18}[0-9]{2}$")


@dataclass(frozen=True)
class FirdsFileInfo:
    member_name: str
    asset_letter: str
    snapshot_date: str          # YYYY-MM-DD from member name
    part: int
    total_parts: int
    rptg_date: str | None = None  # RptgPrd/Dt inside the XML


def file_info(zf: zipfile.ZipFile) -> FirdsFileInfo:
    """Member metadata — exactly one FULINS xml member expected."""
    infos = []
    for n in zf.namelist():
        m = _MEMBER_RE.search(n)
        if m:
            infos.append(FirdsFileInfo(
                member_name=n, asset_letter=m.group(1),
                snapshot_date=(
                    f"{m.group(2)[:4]}-{m.group(2)[4:6]}-{m.group(2)[6:8]}"),
                part=int(m.group(3)), total_parts=int(m.group(4))))
    if len(infos) != 1:
        raise ParseError(
            f"expected exactly one FULINS_*_NNofMM.xml member, "
            f"found {len(infos)}")
    return infos[0]


def rptg_period_date(zf: zipfile.ZipFile, member: str) -> str | None:
    """The snapshot date declared inside the XML (RptgPrd/Dt)."""
    with zf.open(member) as f:
        for _ev, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname == "Dt":
                return (el.text or "").strip() or None
            if etree.QName(el).localname == "RefData":
                return None
    return None


def _t(el: etree._Element, path: str) -> str | None:
    child = el.find(path)
    if child is None or child.text is None:
        return None
    v = child.text.strip()
    return v or None


def parse_refdata(el: etree._Element) -> dict:
    """One RefData element -> verbatim field dict."""
    gnl = el.find("{*}FinInstrmGnlAttrbts")
    tvn = el.find("{*}TradgVnRltdAttrbts")
    tech = el.find("{*}TechAttrbts")
    pbl = tech.find("{*}PblctnPrd") if tech is not None else None
    ftd = pbl.find("{*}FrDtToDt") if pbl is not None else None
    return {
        "isin": _t(gnl, "{*}Id"),
        "full_name": _t(gnl, "{*}FullNm"),
        "fisn": _t(gnl, "{*}ShrtNm"),
        "cfi": _t(gnl, "{*}ClssfctnTp"),
        "notional_currency": _t(gnl, "{*}NtnlCcy"),
        "commodity_derivative": _t(gnl, "{*}CmmdtyDerivInd"),
        "issr": _t(el, "{*}Issr"),
        "venue": _t(tvn, "{*}Id"),
        "issuer_requested_admission": _t(tvn, "{*}IssrReq"),
        "admission_approval_date": _t(tvn, "{*}AdmssnApprvlDtByIssr"),
        "admission_request_date": _t(tvn, "{*}ReqForAdmssnDt"),
        "first_trade_date": _t(tvn, "{*}FrstTradDt"),
        "termination_date": _t(tvn, "{*}TermntnDt"),
        "competent_authority": _t(tech, "{*}RlvntCmptntAuthrty"),
        "publication_from": (
            _t(ftd, "{*}FrDt") if ftd is not None
            else _t(pbl, "{*}FrDt") if pbl is not None else None),
        "publication_to": (
            _t(ftd, "{*}ToDt") if ftd is not None else None),
        "relevant_venue": _t(tech, "{*}RlvntTradgVn"),
    }


def iter_refdata(
    zf: zipfile.ZipFile, member: str, wanted_isins: set[str],
) -> Iterator[tuple[int, dict]]:
    """Yield (record_ordinal, parsed record) for ISINs in ``wanted_isins``.

    The ordinal counts RefData elements in THIS file — the locator is
    ``<member>#RefData=<n>``.
    """
    ordinal = 0
    with zf.open(member) as f:
        for _ev, el in etree.iterparse(f, events=("end",)):
            if etree.QName(el).localname == "RefData":
                ordinal += 1
                isin = _t(el, "{*}FinInstrmGnlAttrbts/{*}Id")
                if isin in wanted_isins:
                    yield ordinal, parse_refdata(el)
                el.clear()


def build_observations(
    universe: dict[str, tuple[str, ...]],
    records: dict[str, list[tuple[str, int, dict]]],
    *,
    snapshot_date: str,
    artifact_ids: dict[str, str],
    source_sha256s: dict[str, str],
    member_sha256s: dict[str, str],
    retrieved_at: str,
) -> tuple[list[ResolutionObservation], list[ResolutionCandidate],
           list[CandidateEvidence]]:
    """Records -> observations/candidates/evidence rows.

    ``records`` maps isin -> [(source_file, ordinal, record_dict)].
    Candidates are unique valid-format Issr values; every record
    becomes an evidence row regardless (a record without Issr keeps
    candidate_lei="").
    """
    observations: list[ResolutionObservation] = []
    candidates: list[ResolutionCandidate] = []
    evidences: list[CandidateEvidence] = []
    first_file = sorted(artifact_ids)[0]
    for isin in sorted(universe):
        obs_id = f"{PROVIDER}/{snapshot_date}/{isin}"
        recs = records.get(isin, [])
        # unique candidate LEIs in deterministic (file, ordinal) order
        seen: list[str] = []
        for _f, _o, r in sorted(recs, key=lambda t: (t[0], t[1])):
            issr = r["issr"]
            if issr and _LEI_RE.match(issr) and issr not in seen:
                seen.append(issr)
        if not recs:
            state = ResolutionState.NO_MATCH
        elif len(seen) == 1:
            state = ResolutionState.MATCHED
        elif len(seen) > 1:
            state = ResolutionState.MULTIPLE_CANDIDATES
        else:
            state = ResolutionState.NO_CANDIDATE
        observations.append(ResolutionObservation(
            observation_id=obs_id,
            isin=isin,
            provider=PROVIDER,
            provider_dataset=DATASET,
            provider_snapshot_date=snapshot_date,
            provider_artifact_id=artifact_ids.get(first_file, ""),
            state=state,
            candidate_count=len(seen),
            holding_periods=universe[isin],
            temporal_semantics=TEMPORAL_SEMANTICS,
            retrieved_at=retrieved_at,
            source_sha256=source_sha256s.get(first_file, ""),
            member_name=first_file,
            member_sha256=member_sha256s.get(first_file, ""),
            parser=PARSER,
            parser_version=PARSER_VERSION,
        ))
        for i, lei in enumerate(seen, start=1):
            candidates.append(ResolutionCandidate(
                observation_id=obs_id,
                candidate_index=i,
                candidate_lei=lei,
                relationship_semantics=SEMANTICS,
                provider_record_locator=next(
                    f"{f}#RefData={o}" for f, o, r in sorted(
                        recs, key=lambda t: (t[0], t[1]))
                    if r["issr"] == lei),
                raw_json=json.dumps(
                    {"issr": lei, "record_count": sum(
                        1 for _f, _o, r in recs if r["issr"] == lei)},
                    sort_keys=True),
            ))
        for j, (fname, ordinal, rec) in enumerate(
                sorted(recs, key=lambda t: (t[0], t[1])), start=1):
            evidences.append(CandidateEvidence(
                evidence_id=f"{obs_id}#{j}",
                observation_id=obs_id,
                candidate_lei=(
                    rec["issr"]
                    if rec["issr"] and _LEI_RE.match(rec["issr"]) else ""),
                evidence_index=j,
                provider_record_locator=f"{fname}#RefData={ordinal}",
                source_file=fname,
                trading_venue=rec["venue"],
                relevant_venue=rec["relevant_venue"],
                first_trade_date=rec["first_trade_date"],
                termination_date=rec["termination_date"],
                raw_json=json.dumps(rec, sort_keys=True),
            ))
    return observations, candidates, evidences
