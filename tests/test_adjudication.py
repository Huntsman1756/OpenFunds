"""G7-E — adjudication layer over provider evidence.

Derived data only: the rules are deliberately boring — equal LEIs
corroborate, different LEIs conflict, nothing breaks a tie, and
conflict classification never changes resolved_lei=NULL.
"""

from __future__ import annotations

import json

import pytest

from cnmv_iic.adjudication import adjudicate, discover_bundle
from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.errors import NotFoundError
from cnmv_iic.provider_ingest import (
    ingest_firds_fulins,
    ingest_gleif_golden,
    ingest_gleif_isin_lei,
    ingest_openfigi,
)
from cnmv_iic.query import (
    resolution_conflicts,
    resolution_coverage,
    security_resolution,
)
from tests.test_firds_fulins import _fulins_zip, _refdata
from tests.test_gleif_golden import _lei_zip, _rel, _repex_zip, _rr_zip
from tests.test_openfigi import (
    ROW_SINGLE,
    ROW_VENUE1,
    ROW_VENUE2,
    _campaign,
    _ok,
)
from tests.test_resolution_gleif import (
    ISIN_A,
    ISIN_B,
    ISIN_C,
    LEI_A,
    LEI_B,
    _gleif_zip,
    _positions,
)

LEI_X = "213800FIRDSONLY00000"       # FIRDS-only candidate (20 chars)
LEI_SUB = "213800SUBFUND0000000"     # FIRDS-only subfund LEI


def _gleif(store, tmp_path, rows):
    zp = tmp_path / "gleif.zip"
    zp.write_bytes(_gleif_zip(rows))
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)


def _firds(store, tmp_path, records):
    zp = tmp_path / "firds.zip"
    zp.write_bytes(_fulins_zip(records))
    ingest_firds_fulins(store, tmp_path / "dataset", [zp])


def _openfigi(tmp_path, results):
    cdir, _ = _campaign(tmp_path, [ISIN_A, ISIN_B, ISIN_C], _ok(results))
    ingest_openfigi(tmp_path / "dataset", cdir)


def _golden(store, tmp_path, lei_recs=None, rr_recs=None):
    """Ingest a GLEIF golden bundle — may carry extra LEIs/relations the
    G7-B wanted-set does not load."""
    zlei = tmp_path / "lei.zip"
    zlei.write_bytes(_lei_zip(lei_recs or {}))
    zrr = tmp_path / "rr.zip"
    zrr.write_bytes(_rr_zip(rr_recs or []))
    zrep = tmp_path / "repex.zip"
    zrep.write_bytes(_repex_zip([]))
    ingest_gleif_golden(store, tmp_path / "dataset", zlei, zrr, zrep)


def test_state_matrix(artifact, tmp_path):
    """corroborated / gleif_only / firds_only / no_authoritative."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A), (LEI_B, ISIN_B)])
    _firds(store, tmp_path, [
        _refdata(ISIN_A, LEI_A, "XMAD"),           # same LEI -> corroborated
        _refdata(ISIN_C, LEI_X, "XLON"),           # firds only
    ])
    res = adjudicate(tmp_path / "dataset", store,
                     adjudicated_at="2026-10-01T00:00:00Z")
    assert res.exported
    by_isin = {r["isin"]: r for r in _sec_rows(tmp_path)}
    assert by_isin[ISIN_A]["state"] == "corroborated"
    assert by_isin[ISIN_A]["resolved_lei"] == LEI_A
    assert by_isin[ISIN_B]["state"] == "gleif_only"
    assert by_isin[ISIN_B]["resolved_lei"] == LEI_B
    assert by_isin[ISIN_C]["state"] == "firds_only"
    assert by_isin[ISIN_C]["resolved_lei"] == LEI_X
    # conservation: every universe ISIN gets exactly one verdict
    assert res.securities == 3
    assert sum(res.security_states.values()) == 3


def test_conflict_never_resolves(artifact, tmp_path):
    """gleif=A firds=B A!=B -> conflict, resolved_lei NULL — no winner."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    _firds(store, tmp_path, [_refdata(ISIN_A, LEI_SUB, "XMAD")])
    adjudicate(tmp_path / "dataset", store)
    rows = _sec_rows(tmp_path)
    a = next(r for r in rows if r["isin"] == ISIN_A)
    assert a["state"] == "conflict"
    assert a["resolved_lei"] is None
    assert a["gleif_candidate_lei"] == LEI_A
    assert a["firds_candidate_lei"] == LEI_SUB
    ctx = json.loads(a["conflict_context_json"])
    assert ctx["kind"] in ("no_direct_gleif_relation",
                           "entity_metadata_difference", "unknown")
    # non-conflicted ISINs carry no context
    assert all(r["conflict_context_json"] is None
               for r in rows if r["isin"] != ISIN_A)


def test_multiple_candidates_never_collapsed(artifact, tmp_path):
    """Any provider >1 candidate -> multiple_candidates, NULL, even when
    the other provider matched cleanly."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_B), (LEI_B, ISIN_B)])
    _firds(store, tmp_path, [_refdata(ISIN_B, LEI_A, "XMAD")])
    adjudicate(tmp_path / "dataset", store)
    b = next(r for r in _sec_rows(tmp_path) if r["isin"] == ISIN_B)
    assert b["state"] == "multiple_candidates"
    assert b["resolved_lei"] is None


def test_conflict_context_direct_relation_loaded(artifact, tmp_path):
    """A->B relation already in the loaded RR table -> direct context."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    _firds(store, tmp_path, [_refdata(ISIN_A, LEI_X, "XMAD")])
    # golden bundle: LEI_A -> LEI_X IS_ULTIMATELY_CONSOLIDATED_BY loaded
    _golden(store, tmp_path,
            lei_recs={LEI_A: "BANCO A", LEI_X: "ENTIDAD X"},
            rr_recs=[_rel(LEI_A, LEI_X, "IS_ULTIMATELY_CONSOLIDATED_BY",
                          "ACTIVE")])
    adjudicate(tmp_path / "dataset", store)
    a = next(r for r in _sec_rows(tmp_path) if r["isin"] == ISIN_A)
    ctx = json.loads(a["conflict_context_json"])
    assert ctx["kind"] == "direct_gleif_relation"
    rel = ctx["relationships"][0]
    assert rel["start_lei"] == LEI_A and rel["end_lei"] == LEI_X
    assert rel["direction"] == "gleif_to_firds"
    assert rel["relationship_status"] == "ACTIVE"


def test_conflict_context_raw_pass_finds_b_to_a(artifact, tmp_path):
    """The G7-B wanted-set never loaded B->A (B is a FIRDS-only LEI) —
    the bounded raw pass over the SAME stored RR-CDF must find it."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    _firds(store, tmp_path, [_refdata(ISIN_A, LEI_SUB, "XMAD")])
    # RR-CDF contains LEI_SUB --IS_SUBFUND_OF--> LEI_A but the loaded
    # table only holds start=LEI_A records (LEI_SUB was never wanted)
    _golden(store, tmp_path,
            lei_recs={LEI_A: "UMBRELLA FUND", LEI_SUB: "SUBFUND ETF"},
            rr_recs=[_rel(LEI_SUB, LEI_A, "IS_SUBFUND_OF", "ACTIVE")])
    adjudicate(tmp_path / "dataset", store)
    a = next(r for r in _sec_rows(tmp_path) if r["isin"] == ISIN_A)
    ctx = json.loads(a["conflict_context_json"])
    assert ctx["kind"] == "direct_gleif_relation"
    rel = ctx["relationships"][0]
    assert rel["start_lei"] == LEI_SUB and rel["end_lei"] == LEI_A
    assert rel["direction"] == "firds_to_gleif"
    assert rel["relationship_type"] == "IS_SUBFUND_OF"
    assert rel["source"] == "raw_artifact"
    # entity metadata pulled from the same raw artifact pass
    assert ctx["entity_b"]["legal_name"] == "SUBFUND ETF"
    assert ctx["entity_b"]["source"] == "raw_artifact"
    # resolved_lei STILL null — context is information, not adjudication
    assert a["resolved_lei"] is None


def test_no_authoritative_match(artifact, tmp_path):
    """No candidate from either provider -> no_authoritative_match."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])     # B, C absent
    adjudicate(tmp_path / "dataset", store)
    by_isin = {r["isin"]: r for r in _sec_rows(tmp_path)}
    assert by_isin[ISIN_B]["state"] == "no_authoritative_match"
    assert by_isin[ISIN_C]["state"] == "no_authoritative_match"
    assert by_isin[ISIN_B]["resolved_lei"] is None


def test_openfigi_never_decides_issuer(artifact, tmp_path):
    """OpenFIGI evidence present must not enter issuer adjudication."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _openfigi(tmp_path, {ISIN_A: {"data": [ROW_SINGLE]}})
    adjudicate(tmp_path / "dataset", store)
    rows = _sec_rows(tmp_path)
    assert all(r["state"] == "no_authoritative_match" for r in rows)
    assert all(r["resolved_lei"] is None for r in rows)


def test_family_states(artifact, tmp_path):
    """shareClassFIGI convergence: distinct NON-NULL values decide."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    row2 = dict(ROW_VENUE2)
    row2["shareClassFIGI"] = "BBG00DIFFERENT"
    _openfigi(tmp_path, {
        ISIN_A: {"data": [ROW_VENUE1, ROW_VENUE2]},   # same sc -> single
        ISIN_B: {"data": [ROW_VENUE1, row2]},          # 2 sc -> multiple
        ISIN_C: {"data": [ROW_SINGLE]},                # no sc -> none
    })
    adjudicate(tmp_path / "dataset", store)
    fams = {r["isin"]: r for r in _fam_rows(tmp_path)}
    assert fams[ISIN_A]["state"] == "single_share_class_figi"
    assert fams[ISIN_A]["share_class_figi"] == "BBG001SS3JK8"
    assert fams[ISIN_A]["venue_figi_count"] == 2
    assert fams[ISIN_B]["state"] == "multiple_share_class_figi"
    assert fams[ISIN_B]["share_class_figi"] is None     # no pick-first
    assert fams[ISIN_C]["state"] == "no_share_class_figi"


def test_null_vs_value_mix_is_single_family(artifact, tmp_path):
    """A null shareClassFIGI beside a value is a provider quirk — the
    distinct non-null set is still one family, not two."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    row_null = dict(ROW_VENUE2)
    row_null.pop("shareClassFIGI")
    _openfigi(tmp_path, {ISIN_A: {"data": [ROW_VENUE1, row_null]}})
    adjudicate(tmp_path / "dataset", store)
    fam = next(r for r in _fam_rows(tmp_path) if r["isin"] == ISIN_A)
    assert fam["state"] == "single_share_class_figi"
    assert fam["share_class_figi"] == "BBG001SS3JK8"


def test_idempotent_same_bundle(artifact, tmp_path):
    """Same evidence + same version -> no-op, identical fingerprint."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    r1 = adjudicate(tmp_path / "dataset", store,
                    adjudicated_at="2026-10-01T00:00:00Z")
    r2 = adjudicate(tmp_path / "dataset", store,
                    adjudicated_at="2026-12-31T00:00:00Z")
    assert r1.exported and not r2.exported
    assert r1.adjudication_fingerprint == r2.adjudication_fingerprint


def test_adjudicated_at_not_in_fingerprint(artifact, tmp_path):
    """Volatile timestamp never enters the deterministic fingerprint —
    deleting the manifest and re-deriving yields the same hash."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    r1 = adjudicate(tmp_path / "dataset", store,
                    adjudicated_at="2026-10-01T00:00:00Z")
    mname = (tmp_path / "dataset" / "manifests"
             / f"adjudication_v1_{r1.bundle_fingerprint[:16]}.json")
    mname.unlink()
    r2 = adjudicate(tmp_path / "dataset", store,
                    adjudicated_at="2030-01-01T00:00:00Z")
    assert r2.adjudication_fingerprint == r1.adjudication_fingerprint


def test_new_evidence_new_bundle_partition(artifact, tmp_path):
    """A new provider snapshot -> new bundle fingerprint -> new
    resolution partition; the old one is preserved untouched."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    r1 = adjudicate(tmp_path / "dataset", store)
    # a second GLEIF snapshot changes the bundle
    zp = tmp_path / "gleif2.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A)], date="20261201"))
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    r2 = adjudicate(tmp_path / "dataset", store)
    assert r2.bundle_fingerprint != r1.bundle_fingerprint
    bundles = {p.parent.name for p in (
        tmp_path / "dataset" / "security_resolution").rglob("*.parquet")}
    assert len(bundles) == 2                        # append-only


def test_bundle_requires_evidence(tmp_path):
    with pytest.raises(NotFoundError):
        discover_bundle(tmp_path / "dataset")


def test_query_accessors(artifact, tmp_path):
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _gleif(store, tmp_path, [(LEI_A, ISIN_A)])
    _firds(store, tmp_path, [_refdata(ISIN_A, LEI_SUB, "XMAD")])
    adjudicate(tmp_path / "dataset", store)
    res = security_resolution(tmp_path / "dataset", ISIN_A)
    assert res["security"]["state"] == "conflict"
    assert res["security"]["resolved_lei"] is None
    assert res["security"]["conflict_context"]["kind"] in (
        "direct_gleif_relation", "entity_metadata_difference",
        "no_direct_gleif_relation", "unknown")
    cov = resolution_coverage(tmp_path / "dataset")
    assert sum(s["n"] for s in cov["security_states"]) == 3
    conf = resolution_conflicts(tmp_path / "dataset")
    assert conf["conflicts"] == 1
    assert conf["rows"][0]["isin"] == ISIN_A


def _sec_rows(tmp_path) -> list[dict]:
    import duckdb

    glob = str(tmp_path / "dataset" / "security_resolution"
               / "version=*" / "bundle=*" / "*.parquet")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=true)",
            [glob]).fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _fam_rows(tmp_path) -> list[dict]:
    import duckdb

    glob = str(tmp_path / "dataset" / "instrument_family_resolution"
               / "version=*" / "bundle=*" / "*.parquet")
    con = duckdb.connect(database=":memory:")
    try:
        rows = con.execute(
            "SELECT * FROM read_parquet(?, hive_partitioning=true)",
            [glob]).fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()
    return [dict(zip(cols, r, strict=True)) for r in rows]
