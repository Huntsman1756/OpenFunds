"""G7-C — ESMA FIRDS FULINS resolution evidence.

Grain: ISIN x venue records are redundant evidence for ONE candidate —
never N candidates. ``Issr`` preserved verbatim as field 5
"issuer or operator of the trading venue". Absence = no_match.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.provider_ingest import ingest_firds_fulins
from cnmv_iic.query import security_evidence
from tests.conftest import make_zip
from tests.test_resolution_gleif import (
    ISIN_A,
    ISIN_B,
    ISIN_C,
    LEI_A,
    _positions,
)

LEI_B = "54930037JLX5M6M3VT03"
LEI_OTHER = "213800OTHERLEI000000"  # 20-char format, 2 check digits


def _refdata(isin: str, issr: str | None, venue: str,
             rvenue: str | None = None, cfi: str = "ESVUFR",
             term: str | None = None) -> str:
    issr_el = f"<Issr>{issr}</Issr>" if issr else ""
    term_el = (f"<TermntnDt>{term}</TermntnDt>" if term else "")
    return (
        f"<RefData><FinInstrmGnlAttrbts><Id>{isin}</Id>"
        f"<FullNm>{isin} NAME</FullNm><ShrtNm>FISN</ShrtNm>"
        f"<ClssfctnTp>{cfi}</ClssfctnTp><NtnlCcy>EUR</NtnlCcy>"
        f"<CmmdtyDerivInd>false</CmmdtyDerivInd></FinInstrmGnlAttrbts>"
        f"{issr_el}"
        f"<TradgVnRltdAttrbts><Id>{venue}</Id><IssrReq>true</IssrReq>"
        f"<FrstTradDt>2015-01-01T00:00:00Z</FrstTradDt>{term_el}"
        f"</TradgVnRltdAttrbts>"
        f"<TechAttrbts><RlvntCmptntAuthrty>ES</RlvntCmptntAuthrty>"
        f"<PblctnPrd><FrDt>2020-01-01</FrDt></PblctnPrd>"
        f"<RlvntTradgVn>{rvenue or venue}</RlvntTradgVn></TechAttrbts>"
        f"</RefData>")


def _fulins_zip(records: list[str], *, asset: str = "E",
                date: str = "20260912", part: int = 1,
                total: int = 1, rptg: str = "2026-09-12") -> bytes:
    member = f"FULINS_{asset}_{date}_{part:02d}of{total:02d}.xml"
    xml = (
        '<BizData xmlns="urn:iso:std:iso:20022:tech:xsd:head.003.001.01">'
        "<Pyld><Document xmlns="
        '"urn:iso:std:iso:20022:tech:xsd:auth.017.001.02">'
        "<FinInstrmRptgRefDataRpt><RptHdr><RptgNtty>"
        "<NtlCmptntAuthrty>EU</NtlCmptntAuthrty></RptgNtty>"
        f"<RptgPrd><Dt>{rptg}</Dt></RptgPrd></RptHdr>"
        f"{''.join(records)}"
        "</FinInstrmRptgRefDataRpt></Document></Pyld></BizData>")
    return make_zip({member: xml.encode()})


def _write(tmp_path, name: str, data: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _ingest(store, tmp_path, zips):
    return ingest_firds_fulins(
        store, tmp_path / "dataset", zips)


def test_same_snapshot_date_required(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z1 = _write(tmp_path, "a.zip", _fulins_zip(
        [_refdata(ISIN_A, LEI_A, "XMAD")], date="20260912"))
    z2 = _write(tmp_path, "b.zip", _fulins_zip(
        [_refdata(ISIN_B, LEI_B, "XLON")], asset="D", date="20260913",
        rptg="2026-09-13"))
    with pytest.raises(ParseError, match="snapshot_date_mismatch"):
        _ingest(store, tmp_path, [z1, z2])


def test_rptg_date_disagreement_fails(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip(
        [_refdata(ISIN_A, LEI_A, "XMAD")],
        date="20260912", rptg="2026-09-11"))
    with pytest.raises(ParseError, match="disagrees"):
        _ingest(store, tmp_path, [z])


def test_incomplete_parts_fail(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip(
        [_refdata(ISIN_A, LEI_A, "XMAD")], part=1, total=2))
    with pytest.raises(ParseError, match="incomplete FULINS"):
        _ingest(store, tmp_path, [z])


def test_venue_multiplicity_one_candidate(artifact, tmp_path):
    """3 venue records for one ISIN -> matched, ONE candidate, 3 evidence."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD"),
        _refdata(ISIN_A, LEI_A, "XLON", term="2020-06-01T00:00:00Z"),
        _refdata(ISIN_A, LEI_A, "XETR", rvenue="FRAB"),
    ]))
    res = _ingest(store, tmp_path, [z])
    assert res.matched == 1
    assert res.evidence_records == 3
    ev = security_evidence(tmp_path / "dataset", ISIN_A)
    obs = next(o for o in ev["observations"]
               if o["provider"] == "esma_firds")
    assert obs["state"] == "matched"
    assert obs["candidate_count"] == 1          # venues != candidates
    assert len(obs["candidates"]) == 1
    evs = obs["candidate_evidence"]
    assert {e["trading_venue"] for e in evs} == {"XMAD", "XLON", "XETR"}
    # the terminated venue record is preserved, not filtered
    assert {e["termination_date"] for e in evs} == {
        None, "2020-06-01T00:00:00Z"}
    # reporting venue may differ from the record's venue — kept verbatim
    assert {e["relevant_venue"] for e in evs} == {
        "XMAD", "XLON", "FRAB"}
    locs = [e["provider_record_locator"] for e in evs]
    assert all("#RefData=" in x for x in locs)


def test_different_leis_are_multiple_candidates(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD"),
        _refdata(ISIN_A, LEI_OTHER, "XLON"),
    ]))
    res = _ingest(store, tmp_path, [z])
    assert res.multiple_candidates == 1
    ev = security_evidence(tmp_path / "dataset", ISIN_A)
    obs = next(o for o in ev["observations"]
               if o["provider"] == "esma_firds")
    assert {c["candidate_lei"] for c in obs["candidates"]} == {
        LEI_A, LEI_OTHER}                          # never collapsed


def test_no_match_not_not_applicable(artifact, tmp_path):
    """ISIN absent from the snapshot = no_match, never not_applicable."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD")]))
    _ingest(store, tmp_path, [z])
    ev = security_evidence(tmp_path / "dataset", ISIN_C)
    obs = next(o for o in ev["observations"]
               if o["provider"] == "esma_firds")
    assert obs["state"] == "no_match"
    assert obs["candidate_count"] == 0


def test_record_without_issr_is_no_candidate(artifact, tmp_path):
    """A record with no Issr: state no_candidate, record still evidence."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD"),
        _refdata(ISIN_B, None, "XLON"),        # record exists, no Issr
    ]))
    res = _ingest(store, tmp_path, [z])
    assert res.no_candidate == 1
    ev = security_evidence(tmp_path / "dataset", ISIN_B)
    obs = next(o for o in ev["observations"]
               if o["provider"] == "esma_firds")
    assert obs["state"] == "no_candidate"
    assert obs["candidates"] == []
    assert obs["candidate_evidence"][0]["candidate_lei"] == ""


def test_semantics_verbatim_field5(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD")]))
    _ingest(store, tmp_path, [z])
    ev = security_evidence(tmp_path / "dataset", ISIN_A)
    obs = next(o for o in ev["observations"]
               if o["provider"] == "esma_firds")
    assert obs["candidates"][0]["relationship_semantics"] == (
        "firds_field5_issuer_or_venue_operator")
    # temporal semantics: current enrichment, never as-of-holding
    assert obs["temporal_semantics"] == (
        "current_enrichment_of_historical_security")
    assert obs["provider_snapshot_date"] == "2026-09-12"
    assert json.loads(obs["holding_periods"]) == ["2025-12", "2026-03"]


def test_multifile_snapshot(artifact, tmp_path):
    """Parts of one asset letter + another letter = one snapshot."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z1 = _write(tmp_path, "d1.zip", _fulins_zip(
        [_refdata(ISIN_A, LEI_A, "XMAD")],
        asset="D", part=1, total=2))
    z2 = _write(tmp_path, "d2.zip", _fulins_zip(
        [_refdata(ISIN_B, LEI_B, "XLON")],
        asset="D", part=2, total=2))
    z3 = _write(tmp_path, "c1.zip", _fulins_zip(
        [_refdata(ISIN_C, LEI_OTHER, "XETR", cfi="CBVUXR")],
        asset="C"))
    res = _ingest(store, tmp_path, [z1, z2, z3])
    assert res.matched == 3
    assert res.artifacts_new == 3
    assert len(res.artifact_ids) == 3


def test_idempotent_reingest(artifact, tmp_path):
    """Multi-part snapshot: re-ingesting identical bytes is a no-op.

    Each part needs its own dedupe key — a shared source_family would
    collide on (period, provider, family) and re-register every part.
    """
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z1 = _write(tmp_path, "d1.zip", _fulins_zip(
        [_refdata(ISIN_A, LEI_A, "XMAD")], asset="D", part=1, total=2))
    z2 = _write(tmp_path, "d2.zip", _fulins_zip(
        [_refdata(ISIN_B, LEI_B, "XLON")], asset="D", part=2, total=2))
    r1 = _ingest(store, tmp_path, [z1, z2])
    r2 = _ingest(store, tmp_path, [z1, z2])
    assert r1.exported and r1.artifacts_new == 2
    assert not r2.exported and r2.artifacts_new == 0
    assert r1.resolution_fingerprint == r2.resolution_fingerprint
    assert len([a for a in store.load() if a.provider == "esma"]) == 2


def test_new_snapshot_appends(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    z1 = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD")]))
    _ingest(store, tmp_path, [z1])
    z2 = _write(tmp_path, "b.zip", _fulins_zip([
        _refdata(ISIN_B, LEI_B, "XLON")], date="20260919",
        rptg="2026-09-19"))
    r2 = _ingest(store, tmp_path, [z2])
    assert r2.exported
    ev = security_evidence(tmp_path / "dataset", ISIN_B)
    snaps = {o["provider_snapshot_date"] for o in ev["observations"]}
    assert "2026-09-12" in snaps and "2026-09-19" in snaps


def test_prior_evidence_intact(artifact, tmp_path):
    _positions(artifact, tmp_path)
    dataset = tmp_path / "dataset"
    mpath = dataset / "manifests" / "2025-12.json"
    before = mpath.read_text()
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD")]))
    _ingest(store, tmp_path, [z])
    assert mpath.read_text() == before


def test_requires_positions(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    z = _write(tmp_path, "a.zip", _fulins_zip([
        _refdata(ISIN_A, LEI_A, "XMAD")]))
    with pytest.raises(NotFoundError, match="no FONDCART positions"):
        _ingest(store, tmp_path, [z])
