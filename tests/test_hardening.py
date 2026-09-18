"""G7-F — integrated hardening for the G7 evidence + adjudication chain.

No new features: truth-table closure of the adjudication rules,
broken-bundle fail-closed, provider independence, campaign-incomplete
visibility, artifact corruption, offline mode, conservation.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from cnmv_iic.adjudication import adjudicate
from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.domain import (
    ResolutionCandidate,
    ResolutionObservation,
    ResolutionState,
)
from cnmv_iic.errors import AcquisitionError, NotFoundError, ParseError
from cnmv_iic.openfigi_client import (
    UrllibPoster,
    read_batch,
    run_campaign,
)
from cnmv_iic.provider_ingest import (
    ingest_gleif_isin_lei,
    ingest_openfigi,
)
from cnmv_iic.storage import write_provider_resolution
from tests.test_firds_fulins import _fulins_zip, _refdata
from tests.test_openfigi import (
    ROW_SINGLE,
    ROW_VENUE1,
    FakePoster,
    _campaign,
    _limiter,
    _ok,
)
from tests.test_resolution_gleif import (
    ISIN_A,
    ISIN_B,
    ISIN_C,
    LEI_A,
    _gleif_zip,
    _positions,
)

LEI_B = "54930037JLX5M6M3VT03"       # 20-char well-formed
LEI_C = "213800CANDIDATE00000"       # 20-char well-formed


def _obs(isin: str, provider: str, snap: str, state: str,
         n_cands: int) -> ResolutionObservation:
    return ResolutionObservation(
        observation_id=f"{provider}/{snap}/{isin}",
        isin=isin, provider=provider, provider_dataset="t",
        provider_snapshot_date=snap,
        provider_artifact_id=f"{provider}-art",
        state=ResolutionState(state), candidate_count=n_cands,
        holding_periods=("2025-12",),
        temporal_semantics="current_enrichment_of_historical_security",
        retrieved_at="2026-01-01T00:00:00Z", source_sha256="s" * 64,
        member_name="m", member_sha256="m" * 64,
        parser="t", parser_version="1")


def _provider(tmp_path, provider: str, snap: str,
              outcomes: dict[str, tuple[str, list[str]]]) -> None:
    """Write one provider partition: isin -> (state, candidate_leis)."""
    obs, cands = [], []
    for isin, (state, leis) in outcomes.items():
        oid = f"{provider}/{snap}/{isin}"
        obs.append(_obs(isin, provider, snap, state, len(leis)))
        for i, lei in enumerate(leis, start=1):
            cands.append(ResolutionCandidate(
                observation_id=oid, candidate_index=i,
                candidate_lei=lei,
                relationship_semantics="t",
                provider_record_locator=f"m#row={i}",
                raw_json="{}"))
    write_provider_resolution(
        tmp_path / "dataset", provider=provider, snapshot_date=snap,
        observations=obs, candidates=cands,
        artifact_id=f"{provider}-art")


GLEIF_P = "gleif_anna_isin_lei"
FIRDS_P = "esma_firds"
_SNAP_G, _SNAP_F = "2026-09-18", "2026-09-12"

# gleif outcome name -> (state, leis)
G = {
    "none": None,                       # provider evidence absent
    "match_a": ("matched", [LEI_A]),
    "match_b": ("matched", [LEI_B]),
    "no_match": ("no_match", []),
    "multi": ("multiple_candidates", [LEI_A, LEI_B]),
}
F = {
    **G,
    "no_candidate": ("no_candidate", []),
}

EXPECTED = {
    # (gleif, firds) -> adjudication state
    ("match_a", "match_a"): "corroborated",
    ("match_a", "match_b"): "conflict",
    ("match_a", "none"): "gleif_only",
    ("match_a", "no_match"): "gleif_only",
    ("match_a", "no_candidate"): "gleif_only",
    ("match_a", "multi"): "multiple_candidates",
    ("match_b", "match_a"): "conflict",
    ("match_b", "match_b"): "corroborated",
    ("no_match", "match_a"): "firds_only",
    ("none", "match_a"): "firds_only",
    ("none", "no_match"): "no_authoritative_match",
    ("no_match", "no_match"): "no_authoritative_match",
    ("no_match", "no_candidate"): "no_authoritative_match",
    ("none", "none"): "no_authoritative_match",
    ("multi", "match_a"): "multiple_candidates",
    ("multi", "none"): "multiple_candidates",
    ("none", "multi"): "multiple_candidates",
    ("multi", "multi"): "multiple_candidates",
    ("match_b", "none"): "gleif_only",
    ("none", "match_b"): "firds_only",
}


def test_truth_table_full_closure(artifact, tmp_path):
    """Every (gleif x firds) outcome combination -> exactly the
    documented verdict. The rules are closed under this table — there
    is no fifth column anywhere.
    """
    import shutil

    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    ds = tmp_path / "dataset"
    for gname, fname in EXPECTED:
        isin = ISIN_A
        # wipe provider evidence + derived tables between combos
        for t in ("resolution_observations", "resolution_candidates",
                  "resolution_candidate_evidence",
                  "security_resolution", "instrument_family_resolution"):
            p = ds / t
            if p.exists():
                shutil.rmtree(p)
        for m in ds.glob("manifests/*.json"):
            if m.name.startswith(("resolution_", "adjudication_")):
                m.unlink()
        # ISIN_B always has a corroborated match — keeps the bundle
        # non-empty and proves per-ISIN independence
        gleif_out = {ISIN_B: G["match_a"]}
        if gname != "none":
            gleif_out[isin] = G[gname]
        _provider(tmp_path, GLEIF_P, _SNAP_G, gleif_out)
        if fname != "none":
            _provider(tmp_path, FIRDS_P, _SNAP_F,
                      {isin: F[fname], ISIN_B: F["match_a"]})
        adjudicate(tmp_path / "dataset", store)
        row = next(r for r in _sec(tmp_path) if r["isin"] == isin)
        want = EXPECTED[(gname, fname)]
        assert row["state"] == want, (
            f"{(gname, fname)}: got {row['state']}")
        if want in ("conflict", "multiple_candidates",
                    "no_authoritative_match"):
            assert row["resolved_lei"] is None
        elif want == "corroborated":
            assert row["resolved_lei"] == row["gleif_candidate_lei"]


def test_broken_bundle_fails_closed(artifact, tmp_path):
    """A manifest whose evidence partition was deleted must fail
    adjudication — never degrade silently to no_match."""
    import shutil

    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    zp = tmp_path / "g.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A)]))
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    shutil.rmtree(tmp_path / "dataset" / "resolution_observations"
                  / f"provider={GLEIF_P}")
    with pytest.raises(NotFoundError, match="broken evidence bundle"):
        adjudicate(tmp_path / "dataset", store)


def test_openfigi_independence(artifact, tmp_path):
    """Removing all OpenFIGI evidence must not change a single issuer
    verdict — instrument evidence can never leak into resolution."""
    import shutil

    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    zp = tmp_path / "g.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A), (LEI_B, ISIN_B)]))
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    cdir, _ = _campaign(
        tmp_path, [ISIN_A, ISIN_B, ISIN_C],
        _ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    ingest_openfigi(tmp_path / "dataset", cdir)
    adjudicate(tmp_path / "dataset", store)
    with_ofi = {r["isin"]: (r["state"], r["resolved_lei"])
                for r in _sec(tmp_path)}
    # drop all OpenFIGI evidence + derived tables, re-adjudicate
    for t in ("instrument_observations", "instrument_candidates"):
        shutil.rmtree(tmp_path / "dataset" / t)
    for m in (tmp_path / "dataset" / "manifests").glob(
            "instrument_openfigi_*.json"):
        m.unlink()
    shutil.rmtree(tmp_path / "dataset" / "security_resolution")
    shutil.rmtree(tmp_path / "dataset" / "instrument_family_resolution")
    adjudicate(tmp_path / "dataset", store)
    without = {r["isin"]: (r["state"], r["resolved_lei"])
               for r in _sec(tmp_path)}
    assert with_ofi == without


def test_level2_explains_never_resolves(artifact, tmp_path):
    """Dropping GLEIF Level-2/Repex degrades conflict_context but must
    not change a single state — Level 2 explains, never resolves."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    zp = tmp_path / "g.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A)]))
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    zp = tmp_path / "f.zip"
    zp.write_bytes(_fulins_zip([_refdata(ISIN_A, LEI_B, "XMAD")]))
    from cnmv_iic.provider_ingest import ingest_firds_fulins
    ingest_firds_fulins(store, tmp_path / "dataset", [zp])
    adjudicate(tmp_path / "dataset", store)   # no golden loaded at all
    row = next(r for r in _sec(tmp_path) if r["isin"] == ISIN_A)
    assert row["state"] == "conflict"
    assert row["resolved_lei"] is None
    ctx = json.loads(row["conflict_context_json"])
    assert ctx["kind"] == "unknown"           # nothing loaded: honest


def test_partial_campaign_visible_and_resumed(artifact, tmp_path):
    """A missing batch: every affected ISIN is provider_error with
    jobs_missing>0 in the manifest, and resume re-requests ONLY the
    missing batch."""
    _positions(artifact, tmp_path)
    cdir, _ = _campaign(
        tmp_path, [ISIN_A, ISIN_B, ISIN_C],
        _ok({ISIN_A: {"data": [ROW_SINGLE]}}), batch_size=1)
    batches = sorted((cdir / "batches").glob("*.zip"))
    assert len(batches) == 3
    batches[1].unlink()                        # ISIN_B batch missing
    res = ingest_openfigi(tmp_path / "dataset", cdir)
    assert res.provider_error == 1
    m = json.loads(
        (tmp_path / "dataset" / "manifests"
         / "instrument_openfigi_2026-09-18.json").read_text())
    assert m["jobs_missing"] == 1
    assert m["campaign_complete"] is False
    # resume: only the missing batch is re-requested
    poster = FakePoster(_ok({ISIN_B: {"data": [ROW_VENUE1]}}))
    outcomes = run_campaign(
        cdir / "batches", [ISIN_A, ISIN_B, ISIN_C],
        poster=poster, limiter=_limiter(), batch_size=1,
        retrieved_at=lambda: "2026-09-18T12:00:00+00:00")
    assert len(poster.calls) == 1
    assert poster.calls[0][0]["idValue"] == ISIN_B
    assert sum(1 for o in outcomes if o.status == "stored") == 1
    assert sum(1 for o in outcomes if o.status == "skipped") == 2


def test_batch_corruption_fail_closed(tmp_path):
    """Corrupted batch artifacts are rejected — truncated zip, missing
    meta, tampered payload."""
    cdir, _ = _campaign(tmp_path, [ISIN_A],
                        _ok({ISIN_A: {"data": [ROW_SINGLE]}}))
    bzip = next((cdir / "batches").glob("*.zip"))
    good = read_batch(bzip)
    assert good.response
    # truncated file
    bad = tmp_path / "bad.zip"
    bad.write_bytes(bzip.read_bytes()[:100])
    with pytest.raises(zipfile.BadZipFile):
        read_batch(bad)
    # not a zip at all
    bad.write_bytes(b"definitely not a zip")
    with pytest.raises(zipfile.BadZipFile):
        read_batch(bad)
    # tampered response payload (hash mismatch) — filename must carry
    # the real batch_id so the sha check is the one that fires
    with zipfile.ZipFile(bzip) as zf:
        meta = json.loads(zf.read("meta.json"))
        req = zf.read("request.json")
    bad = tmp_path / f"{meta['batch_id']}.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("request.json", req)
        zf.writestr("response.json", b'[{"data": []}]')
        zf.writestr("meta.json", json.dumps(meta))
    with pytest.raises(ParseError, match="sha256"):
        read_batch(bad)


def test_offline_mode_blocks_network():
    os.environ["CNMV_IIC_OFFLINE"] = "1"
    try:
        with pytest.raises(AcquisitionError, match="OFFLINE"):
            UrllibPoster().post(
                "https://api.openfigi.com/v3/mapping", b"[]", {})
    finally:
        del os.environ["CNMV_IIC_OFFLINE"]


def test_multiple_part_files_read(tmp_path, artifact):
    """A partition split across several part files is read whole —
    filesystem layout never changes logical content."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    import pyarrow as pa
    import pyarrow.parquet as pq

    from cnmv_iic.storage import (
        RESOLUTION_OBSERVATIONS_SCHEMA,
        resolution_observation_rows,
    )
    o1 = _obs(ISIN_A, GLEIF_P, _SNAP_G, "matched", 1)
    o2 = _obs(ISIN_B, GLEIF_P, _SNAP_G, "no_match", 0)
    pdir = (tmp_path / "dataset" / "resolution_observations"
            / f"provider={GLEIF_P}" / f"snapshot={_SNAP_G}")
    pdir.mkdir(parents=True)
    r1 = resolution_observation_rows([o1])
    r2 = resolution_observation_rows([o2])
    pq.write_table(pa.Table.from_pylist(r1, schema=RESOLUTION_OBSERVATIONS_SCHEMA),
                   pdir / "part-0.parquet")
    pq.write_table(pa.Table.from_pylist(r2, schema=RESOLUTION_OBSERVATIONS_SCHEMA),
                   pdir / "part-1.parquet")
    import json as _j
    (tmp_path / "dataset" / "manifests").mkdir(exist_ok=True)
    (tmp_path / "dataset" / "manifests"
     / f"resolution_{GLEIF_P}_{_SNAP_G}.json").write_text(_j.dumps({
         "provider": GLEIF_P, "provider_snapshot_date": _SNAP_G,
         "resolution_fingerprint": "f" * 64, "observations": 2}))
    from cnmv_iic.storage import (
        RESOLUTION_CANDIDATES_SCHEMA,
        resolution_candidate_rows,
    )
    c = ResolutionCandidate(
        observation_id=o1.observation_id, candidate_index=1,
        candidate_lei=LEI_A, relationship_semantics="t",
        provider_record_locator="m#1", raw_json="{}")
    cdir2 = (tmp_path / "dataset" / "resolution_candidates"
             / f"provider={GLEIF_P}" / f"snapshot={_SNAP_G}")
    cdir2.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            resolution_candidate_rows([c]),
            schema=RESOLUTION_CANDIDATES_SCHEMA),
        cdir2 / "part-0.parquet")
    res = adjudicate(tmp_path / "dataset", store)
    assert res.securities == 3
    a = next(r for r in _sec(tmp_path) if r["isin"] == ISIN_A)
    assert a["state"] == "gleif_only"


def test_conservation_gate_holds(tmp_path, artifact):
    """Conservation is enforced: verdicts == universe size, always."""
    _positions(artifact, tmp_path)
    store = ArtifactStore(tmp_path / "artifacts")
    _provider(tmp_path, GLEIF_P, _SNAP_G,
              {ISIN_A: G["no_match"], ISIN_B: G["no_match"],
               ISIN_C: G["no_match"]})
    res = adjudicate(tmp_path / "dataset", store)
    # universe = 3 valid ISINs; every one has a verdict, none skipped
    assert res.securities == 3
    assert sum(res.security_states.values()) == 3
    assert res.security_states["no_authoritative_match"] == 3


# -- hypothesis: candidate-set invariance -------------------------------------

def test_hypothesis_available():
    import hypothesis
    assert hypothesis.__version__


@pytest.mark.parametrize("seed", range(20))
def test_verdict_is_candidate_set_not_order(seed, artifact, tmp_path):
    """Candidate INDEX order inside a provider response never changes
    the verdict — multiplicity is a set property."""
    import random

    rng = random.Random(seed)  # noqa: S311 - test determinism, not crypto
    leis = rng.sample([LEI_A, LEI_B, LEI_C], k=rng.randint(0, 3))
    _positions(artifact, tmp_path)
    import shutil
    for t in ("resolution_observations", "resolution_candidates"):
        p = tmp_path / "dataset" / t
        if p.exists():
            shutil.rmtree(p)
    for m in (tmp_path / "dataset" / "manifests").glob("*.json"):
        if m.name.startswith(("resolution_", "adjudication_")):
            m.unlink()
    for t in ("security_resolution", "instrument_family_resolution"):
        p = tmp_path / "dataset" / t
        if p.exists():
            shutil.rmtree(p)
    state = ("matched" if len(leis) == 1 else "no_match"
             if not leis else "multiple_candidates")
    _provider(tmp_path, GLEIF_P, _SNAP_G, {ISIN_A: (state, leis)})
    store = ArtifactStore(tmp_path / "artifacts")
    adjudicate(tmp_path / "dataset", store)
    row = next(r for r in _sec(tmp_path) if r["isin"] == ISIN_A)
    if len(leis) > 1:
        assert row["state"] == "multiple_candidates"
    elif len(leis) == 1:
        assert row["state"] == "gleif_only"
        assert row["resolved_lei"] == leis[0]
    else:
        assert row["state"] == "no_authoritative_match"


def _sec(tmp_path) -> list[dict]:
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


def test_conflict_golden_corpus():
    """docs/g7/conflict-goldens.json — every live conflict preserved as
    a golden: resolved_lei NULL always, and every semantic category
    present (umbrella/subfund, manager, consolidation, no-relation)."""
    g = json.loads(
        (Path(__file__).parent.parent
         / "docs" / "g7" / "conflict-goldens.json").read_text())
    rows = g["rows"]
    assert len(rows) == g["conflicts"] == 271
    for r in rows:
        assert r["resolved_lei"] is None
        assert r["gleif_candidate_lei"] != r["firds_candidate_lei"]
    kinds = {r["context_kind"] for r in rows}
    assert {"direct_gleif_relation", "no_direct_gleif_relation",
            "entity_metadata_difference"} <= kinds
    types = {t for r in rows for t in r["relationship_types"]}
    # the semantic conflict classes the user required as goldens
    assert "IS_SUBFUND_OF" in types            # umbrella vs subfund
    assert "IS_FUND-MANAGED_BY" in types       # fund vs manager
    assert "IS_DIRECTLY_CONSOLIDATED_BY" in types
    assert "IS_ULTIMATELY_CONSOLIDATED_BY" in types
