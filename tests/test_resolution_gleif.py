"""G7-A — GLEIF/ANNA ISIN->LEI resolution evidence ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnmv_iic.adapters.fondcart import parse_fondcart
from cnmv_iic.adapters.gleif_isin_lei import (
    member_snapshot_date,
)
from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.provider_ingest import ingest_gleif_isin_lei
from cnmv_iic.query import security_evidence
from cnmv_iic.storage import write_period
from tests.conftest import make_zip
from tests.test_portfolio_diff import _cart, _pos

ISIN_A = "US0378331005"   # valid
ISIN_B = "ES0113900J37"   # valid
ISIN_C = "XS2902091292"   # valid
LEI_A = "5493006QMFDDMYWIAM13"
LEI_B = "54930037JLX5M6M3VTS03"
LEI_B2 = "HWUPKR0MPOU8FGXBT394"


def _gleif_zip(rows: list[tuple[str, str]], date: str = "20260101") -> Path:
    csv = "LEI,ISIN\n" + "".join(f"{lei},{isin}\n" for lei, isin in rows)
    return make_zip({f"lei-isin-{date}T000000.csv": csv.encode()})


def _positions(artifact, tmp_path):
    """Two-period corpus with valid, masked and absent ISINs."""
    old = _cart("202512", [
        _pos("I", "Renta Variable", ISIN_A, "A|APPLE", "USD", "100.00"),
        _pos("I", "Renta Variable", ISIN_B, "A|SAN", "EUR", "50.00"),
        _pos("I", "IIC", "XXXXXXXXXXXX", "F|MASKED", "EUR", "10.00"),
        _pos("I", "Renta Fija", None, "B|NONE", "EUR", "20.00"),
    ])
    new = _cart("202603", [
        _pos("I", "Renta Variable", ISIN_A, "A|APPLE", "USD", "110.00"),
        _pos("I", "Renta Variable", ISIN_C, "A|XS", "EUR", "40.00"),
    ])
    for period, xml in (("2025-12", old), ("2026-03", new)):
        snaps = parse_fondcart(
            xml, artifact=artifact, member_name=f"FONDCART_{period}.xml",
            member_sha256="m" * 64)
        write_period(tmp_path / "dataset", snaps, period=period,
                     artifact_id=f"art-{period}")
    return tmp_path / "dataset"


def _ingest(artifact, tmp_path, gleif_zip: bytes, date: str = "20260101"):
    zp = tmp_path / "gleif.zip"
    zp.write_bytes(gleif_zip)
    store = ArtifactStore(tmp_path / "artifacts")
    return ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)


def test_snapshot_date_from_member():
    assert member_snapshot_date(
        "lei-isin-20260918T071512.csv") == "2026-09-18"
    with pytest.raises(ParseError):
        member_snapshot_date("lei-isin-bad.csv")


def test_matched_and_no_match(artifact, tmp_path):
    _positions(artifact, tmp_path)
    res = _ingest(artifact, tmp_path, _gleif_zip([
        (LEI_A, ISIN_A), (LEI_B, ISIN_B)]))
    assert res.universe_isins == 3            # masked/absent excluded
    assert res.matched == 2
    assert res.no_match == 1                  # ISIN_C absent from snapshot
    assert res.candidates == 2


def test_multiple_candidates_preserved(artifact, tmp_path):
    _positions(artifact, tmp_path)
    res = _ingest(artifact, tmp_path, _gleif_zip([
        (LEI_B, ISIN_B), (LEI_B2, ISIN_B), (LEI_A, ISIN_A)]))
    assert res.multiple_candidates == 1
    assert res.candidates == 3
    ev = security_evidence(tmp_path / "dataset", ISIN_B)
    obs = ev["observations"][0]
    assert obs["state"] == "multiple_candidates"
    assert obs["candidate_count"] == 2
    leis = {c["candidate_lei"] for c in obs["candidates"]}
    assert leis == {LEI_B, LEI_B2}            # never collapsed


def test_no_match_semantics(artifact, tmp_path):
    _positions(artifact, tmp_path)
    _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    ev = security_evidence(tmp_path / "dataset", ISIN_C)
    obs = ev["observations"][0]
    assert obs["state"] == "no_match"         # valid result, not error
    assert obs["candidate_count"] == 0
    assert obs["candidates"] == []
    # "no ISIN->LEI row in this snapshot" — NOT "issuer has no LEI"
    assert obs["provider_snapshot_date"] == "2026-01-01"
    assert obs["temporal_semantics"] == (
        "current_enrichment_of_historical_security")


def test_masked_and_absent_never_observed(artifact, tmp_path):
    _positions(artifact, tmp_path)
    res = _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    assert res.universe_isins == 3            # only the 3 valid ISINs
    import duckdb
    con = duckdb.connect(database=":memory:")
    glob = str(tmp_path / "dataset" / "resolution_observations"
               / "provider=*" / "snapshot=*" / "*.parquet")
    isins = {r[0] for r in con.execute(
        "SELECT DISTINCT isin FROM read_parquet(?, "
        "hive_partitioning=true)", [glob]).fetchall()}
    assert "XXXXXXXXXXXX" not in isins
    assert isins == {ISIN_A, ISIN_B, ISIN_C}


def test_provenance_to_csv_row(artifact, tmp_path):
    _positions(artifact, tmp_path)
    _ingest(artifact, tmp_path, _gleif_zip([
        (LEI_A, ISIN_A), (LEI_B, ISIN_B)]))
    ev = security_evidence(tmp_path / "dataset", ISIN_B)
    cand = ev["observations"][0]["candidates"][0]
    assert cand["provider_record_locator"].endswith("#row=2")
    assert cand["relationship_semantics"] == "isin_issuer_to_lei"
    raw = json.loads(cand["raw_json"])
    assert raw == {"ISIN": ISIN_B, "LEI": LEI_B}


def test_holding_periods_separate_from_snapshot(artifact, tmp_path):
    _positions(artifact, tmp_path)
    _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    ev = security_evidence(tmp_path / "dataset", ISIN_A)
    obs = ev["observations"][0]
    periods = json.loads(obs["holding_periods"])
    assert periods == ["2025-12", "2026-03"]   # both corpus periods
    assert obs["provider_snapshot_date"] == "2026-01-01"
    # enrichment date can never be confused with holding dates
    assert obs["temporal_semantics"] == (
        "current_enrichment_of_historical_security")


def test_idempotent_reingest(artifact, tmp_path):
    _positions(artifact, tmp_path)
    gz = _gleif_zip([(LEI_A, ISIN_A), (LEI_B, ISIN_B)])
    r1 = _ingest(artifact, tmp_path, gz)
    r2 = _ingest(artifact, tmp_path, gz)
    assert r1.exported and r1.artifact_new
    assert not r2.exported and not r2.artifact_new
    assert r1.resolution_fingerprint == r2.resolution_fingerprint


def test_new_snapshot_appends_evidence(artifact, tmp_path):
    _positions(artifact, tmp_path)
    _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    r2 = _ingest(artifact, tmp_path,
                 _gleif_zip([(LEI_A, ISIN_A), (LEI_B, ISIN_B)],
                            date="20260201"))
    assert r2.exported
    # both snapshots retained as separate evidence
    ev = security_evidence(tmp_path / "dataset", ISIN_B)
    states = [(o["provider_snapshot_date"], o["state"])
            for o in ev["observations"]]
    assert ("2026-01-01", "no_match") in states
    assert ("2026-02-01", "matched") in states
    # never an overwrite — the old no_match observation still exists


def test_universe_requires_positions(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    zp = tmp_path / "gleif.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A)]))
    with pytest.raises(NotFoundError, match="no FONDCART positions"):
        ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)


def test_security_evidence_fail_closed(artifact, tmp_path):
    _positions(artifact, tmp_path)
    _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    with pytest.raises(NotFoundError, match="not a valid ISIN"):
        security_evidence(tmp_path / "dataset", "XXXXXXXXXXXX")
    with pytest.raises(NotFoundError, match="not a valid ISIN"):
        security_evidence(tmp_path / "dataset", "GARBAGE")


def test_ingest_does_not_touch_period_manifests(artifact, tmp_path):
    dataset = _positions(artifact, tmp_path)
    mpath = dataset / "manifests" / "2025-12.json"
    before = mpath.read_text()
    _ingest(artifact, tmp_path, _gleif_zip([(LEI_A, ISIN_A)]))
    assert mpath.read_text() == before        # G1-G6 fingerprints intact
