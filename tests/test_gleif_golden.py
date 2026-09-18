"""G7-B — GLEIF Golden Copy evidence: Level-1 entities, RR-CDF
relationships, Reporting Exceptions. Evidence only: verbatim types,
one-hop closure, exceptions as rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.provider_ingest import (
    ingest_gleif_golden,
    ingest_gleif_isin_lei,
)
from cnmv_iic.query import lei_evidence
from tests.conftest import make_zip
from tests.test_resolution_gleif import (
    ISIN_A,
    ISIN_B,
    LEI_A,
    _gleif_zip,
    _positions,
)

LEI_B = "54930037JLX5M6M3VT03"       # well-formed 20-char (test ISIN->LEI)
LEI_END = "213800ENDN0DE0000000"     # one-hop closure node
LEI_FAR = "213800FARAWAY0000000"     # second hop — must never appear
LEI_X = "213800UNWANTED000000"       # unrelated entity — excluded
LEI_MGMT = "213800MANAGEMENT0000"    # second closure node


def _lei_zip(leis: dict[str, str], date: str = "20260918") -> Path:
    """{lei: legal_name} -> LEI-CDF 3.1 zip."""
    recs = "".join(
        f'<lei:LEIRecord><lei:LEI>{lei}</lei:LEI>'
        f'<lei:Entity><lei:LegalName xml:lang="en">{name}</lei:LegalName>'
        f'<lei:LegalAddress xml:lang="en">'
        f'<lei:FirstAddressLine>1 MAIN ST</lei:FirstAddressLine>'
        f'<lei:City>MADRID</lei:City><lei:Country>ES</lei:Country>'
        f'</lei:LegalAddress>'
        f'<lei:HeadquartersAddress xml:lang="en">'
        f'<lei:City>MADRID</lei:City><lei:Country>ES</lei:Country>'
        f'</lei:HeadquartersAddress>'
        f'<lei:LegalJurisdiction>ES</lei:LegalJurisdiction>'
        f'<lei:EntityCategory>GENERAL</lei:EntityCategory>'
        f'<lei:LegalForm><lei:EntityLegalFormCode>9999'
        f'</lei:EntityLegalFormCode></lei:LegalForm>'
        f'<lei:EntityStatus>ACTIVE</lei:EntityStatus></lei:Entity>'
        f'<lei:Registration>'
        f'<lei:InitialRegistrationDate>2020-01-01T00:00:00Z'
        f'</lei:InitialRegistrationDate>'
        f'<lei:LastUpdateDate>2026-01-01T00:00:00Z</lei:LastUpdateDate>'
        f'<lei:RegistrationStatus>ISSUED</lei:RegistrationStatus>'
        f'<lei:NextRenewalDate>2027-01-01T00:00:00Z</lei:NextRenewalDate>'
        f'<lei:ManagingLOU>EVK05KS7XY1DELOVB065</lei:ManagingLOU>'
        f'<lei:ValidationSources>FULLY_CORROBORATED'
        f'</lei:ValidationSources></lei:Registration></lei:LEIRecord>'
        for lei, name in leis.items())
    xml = ('<lei:LEIData xmlns:lei='
           '"http://www.gleif.org/data/schema/leidata/2016">'
           f'<lei:LEIRecords>{recs}</lei:LEIRecords></lei:LEIData>')
    return make_zip(
        {f"{date}-gleif-concatenated-file-lei2.xml": xml.encode()})


def _rel(start: str, end: str, rtype: str, status: str | None,
         n_periods: int = 1) -> str:
    periods = "".join(
        f'<rr:RelationshipPeriod>'
        f'<rr:StartDate>2020-0{i + 1}-01T00:00:00Z</rr:StartDate>'
        f'<rr:PeriodType>RELATIONSHIP_PERIOD</rr:PeriodType>'
        f'</rr:RelationshipPeriod>' for i in range(n_periods))
    st = (f'<rr:RelationshipStatus>{status}</rr:RelationshipStatus>'
          if status else "")
    return (
        f'<rr:RelationshipRecord><rr:Relationship>'
        f'<rr:StartNode><rr:NodeID>{start}</rr:NodeID>'
        f'<rr:NodeIDType>LEI</rr:NodeIDType></rr:StartNode>'
        f'<rr:EndNode><rr:NodeID>{end}</rr:NodeID>'
        f'<rr:NodeIDType>LEI</rr:NodeIDType></rr:EndNode>'
        f'<rr:RelationshipType>{rtype}</rr:RelationshipType>'
        f'<rr:RelationshipPeriods>{periods}</rr:RelationshipPeriods>'
        f'{st}</rr:Relationship>'
        f'<rr:Registration>'
        f'<rr:RegistrationStatus>PUBLISHED</rr:RegistrationStatus>'
        f'<rr:ValidationSources>ENTITY_SUPPLIED_ONLY'
        f'</rr:ValidationSources></rr:Registration>'
        f'</rr:RelationshipRecord>')


def _rr_zip(rels: list[str], date: str = "20260918") -> Path:
    xml = ('<rr:RRData xmlns:rr='
           '"http://www.gleif.org/data/schema/rr/2016">'
           f'<rr:RelationshipRecords>{"".join(rels)}'
           '</rr:RelationshipRecords></rr:RRData>')
    return make_zip(
        {f"{date}-gleif-concatenated-file-rr.xml": xml.encode()})


def _repex_zip(rows: list[tuple[str, str, str]],
               date: str = "20260918") -> Path:
    exc = "".join(
        f'<repex:Exception><repex:LEI>{lei}</repex:LEI>'
        f'<repex:ExceptionCategory>{cat}</repex:ExceptionCategory>'
        f'<repex:ExceptionReason>{reason}</repex:ExceptionReason>'
        f'</repex:Exception>' for lei, cat, reason in rows)
    xml = ('<repex:ReportingExceptions xmlns:repex='
           '"http://www.gleif.org/data/schema/repex/2016">'
           f'{exc}</repex:ReportingExceptions>')
    return make_zip(
        {f"{date}-gleif-concatenated-file-repex.xml": xml.encode()})


def _bundle(tmp_path, date: str = "20260918",
            lei_date: str | None = None,
            rr_date: str | None = None,
            repex_date: str | None = None):
    """Full synthetic GLEIF bundle; returns (lei, rr, repex) zip paths."""
    zlei = _lei_zip({
        LEI_A: "BANCO SANTANDER SA",
        LEI_B: "BBVA ASSET MANAGEMENT",
        LEI_END: "SANTANDER HOLDING",
        LEI_MGMT: "GESTORA SA SGIIC",
        LEI_X: "UNRELATED CORP",
    }, date=lei_date or date)
    zrr = _rr_zip([
        _rel(LEI_A, LEI_END, "IS_DIRECTLY_CONSOLIDATED_BY", "ACTIVE"),
        _rel(LEI_A, LEI_END, "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE",
             n_periods=2),
        _rel(LEI_A, LEI_END, "IS_SUBFUND_OF", None),        # NULL status
        _rel(LEI_B, LEI_MGMT, "IS_FUND-MANAGED_BY", "INACTIVE"),
        _rel(LEI_END, LEI_FAR, "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"),
        _rel(LEI_X, LEI_A, "IS_ULTIMATELY_CONSOLIDATED_BY", "ACTIVE"),
    ], date=rr_date or date)
    zrepex = _repex_zip([
        (LEI_B, "ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT",
         "NON_CONSOLIDATING"),
        (LEI_X, "DIRECT_ACCOUNTING_CONSOLIDATION_PARENT", "NO_LEI"),
    ], date=repex_date or date)
    paths = []
    for name, data in (("lei", zlei), ("rr", zrr), ("repex", zrepex)):
        dst = tmp_path / f"{name}-{date}.zip"
        dst.write_bytes(data)
        paths.append(dst)
    return tuple(paths)


def _setup(artifact, tmp_path):
    """Corpus + G7-A candidates {LEI_A, LEI_B}, then bundle paths."""
    _positions(artifact, tmp_path)
    zp = tmp_path / "gleif.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A), (LEI_B, ISIN_B)]))
    store = ArtifactStore(tmp_path / "artifacts")
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    return store


def _ingest(store, tmp_path, bundle):
    return ingest_gleif_golden(
        store, tmp_path / "dataset", *bundle)


def test_same_snapshot_date_required(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    bundle = _bundle(tmp_path, lei_date="20260918", rr_date="20260917")
    with pytest.raises(ParseError, match="snapshot_date_mismatch"):
        _ingest(store, tmp_path, bundle)


def test_entities_filtered_and_roles(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    res = _ingest(store, tmp_path, _bundle(tmp_path))
    assert res.wanted_lei_count == 2
    # closure = end nodes of wanted-start records not already wanted
    assert res.closure_lei_count == 2            # LEI_END + LEI_MGMT
    assert res.legal_entities == 4               # LEI_X never pulled
    assert res.entities_resolved_role == 2
    assert res.entities_closure_role == 2
    ev = lei_evidence(tmp_path / "dataset", LEI_A)
    ent = ev["entities"][0]
    assert ent["legal_name"] == "BANCO SANTANDER SA"
    assert ent["legal_jurisdiction"] == "ES"
    assert ent["managing_lou"] == "EVK05KS7XY1DELOVB065"
    assert ent["registration_status"] == "ISSUED"
    assert json.loads(ent["legal_address_json"])["city"] == "MADRID"
    end = lei_evidence(tmp_path / "dataset", LEI_END)
    assert end["entities"][0]["evidence_role"] == "closure_end_node"


def test_relationship_types_verbatim(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    _ingest(store, tmp_path, _bundle(tmp_path))
    import duckdb
    con = duckdb.connect(database=":memory:")
    glob = str(tmp_path / "dataset" / "relationships"
               / "provider=*" / "snapshot=*" / "*.parquet")
    rows = con.execute(
        "SELECT start_lei, end_lei, relationship_type,"
        " relationship_status FROM read_parquet(?,"
        " hive_partitioning=true)", [glob]).fetchall()
    types = {r[2] for r in rows}
    assert types == {"IS_DIRECTLY_CONSOLIDATED_BY",
                     "IS_ULTIMATELY_CONSOLIDATED_BY",
                     "IS_FUND-MANAGED_BY",
                     "IS_SUBFUND_OF"}                 # never "parent"
    # start/end preserved even though ends are outside the CNMV universe
    ends = {r[1] for r in rows}
    assert ends == {LEI_END, LEI_MGMT}
    # all extracted relationships start at a resolved LEI
    assert {r[0] for r in rows} == {LEI_A, LEI_B}


def test_one_hop_bound(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    _ingest(store, tmp_path, _bundle(tmp_path))
    import duckdb
    con = duckdb.connect(database=":memory:")
    rglob = str(tmp_path / "dataset" / "relationships"
                / "provider=*" / "snapshot=*" / "*.parquet")
    starts = {r[0] for r in con.execute(
        "SELECT DISTINCT start_lei FROM read_parquet(?,"
        " hive_partitioning=true)", [rglob]).fetchall()}
    assert LEI_END not in starts      # closure node does NOT expand
    eglob = str(tmp_path / "dataset" / "legal_entities"
                / "provider=*" / "snapshot=*" / "*.parquet")
    leis = {r[0] for r in con.execute(
        "SELECT DISTINCT lei FROM read_parquet(?,"
        " hive_partitioning=true)", [eglob]).fetchall()}
    assert LEI_FAR not in leis        # second hop unreachable
    assert LEI_X not in leis          # unrelated entity filtered out


def test_status_and_periods_verbatim(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    _ingest(store, tmp_path, _bundle(tmp_path))
    ev = lei_evidence(tmp_path / "dataset", LEI_A)
    rels = ev["relationships_as_start"]
    statuses = {r["relationship_type"]: r["relationship_status"]
                for r in rels}
    assert statuses["IS_DIRECTLY_CONSOLIDATED_BY"] == "ACTIVE"
    assert statuses["IS_SUBFUND_OF"] is None          # NULL preserved
    ult = next(r for r in rels
               if r["relationship_type"] == "IS_ULTIMATELY_CONSOLIDATED_BY")
    periods = json.loads(ult["relationship_periods_json"])
    assert len(periods) == 2                          # never reduced
    assert all(p["period_type"] == "RELATIONSHIP_PERIOD" for p in periods)


def test_exceptions_are_rows_not_nulls(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    res = _ingest(store, tmp_path, _bundle(tmp_path))
    assert res.relationship_exceptions == 1           # LEI_X excluded
    ev = lei_evidence(tmp_path / "dataset", LEI_B)
    exc = ev["exceptions"][0]
    assert exc["exception_category"] == (
        "ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT")   # verbatim
    assert exc["exception_reason"] == "NON_CONSOLIDATING"
    # machine-visible distinction: LEI_B reports IS_FUND-MANAGED_BY
    # plus an exception for ULTIMATE — not "no parent", an official
    # declared reason the consolidation parent cannot be provided
    assert {r["relationship_type"] for r in ev["relationships_as_start"]
            } == {"IS_FUND-MANAGED_BY"}
    # LEI_X had an exception row in the file but is not in the universe
    evx = lei_evidence(tmp_path / "dataset", LEI_X)
    assert evx["exceptions"] == []


def test_idempotent_reingest(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    bundle = _bundle(tmp_path)
    r1 = _ingest(store, tmp_path, bundle)
    r2 = _ingest(store, tmp_path, bundle)
    assert r1.exported and r1.artifacts_new == 3
    assert not r2.exported and r2.artifacts_new == 0
    assert r1.evidence_fingerprint == r2.evidence_fingerprint


def test_new_snapshot_appends_evidence(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    _ingest(store, tmp_path, _bundle(tmp_path))
    r2 = _ingest(store, tmp_path, _bundle(tmp_path, date="20261201"))
    assert r2.exported
    ev = lei_evidence(tmp_path / "dataset", LEI_A)
    snaps = {e["provider_snapshot_date"] for e in ev["entities"]}
    assert snaps == {"2026-09-18", "2026-12-01"}      # append-only


def test_requires_candidates(artifact, tmp_path):
    _positions(artifact, tmp_path)                    # no G7-A ingest
    store = ArtifactStore(tmp_path / "artifacts")
    bundle = _bundle(tmp_path)
    with pytest.raises(NotFoundError, match="resolution candidates"):
        _ingest(store, tmp_path, bundle)


def test_lei_evidence_fail_closed(artifact, tmp_path):
    store = _setup(artifact, tmp_path)
    _ingest(store, tmp_path, _bundle(tmp_path))
    with pytest.raises(NotFoundError, match="not a well-formed LEI"):
        lei_evidence(tmp_path / "dataset", "GARBAGE")
    with pytest.raises(NotFoundError, match="not a well-formed LEI"):
        lei_evidence(tmp_path / "dataset", "XXXXXXXXXXXX")


def test_prior_evidence_intact(artifact, tmp_path):
    _positions(artifact, tmp_path)
    zp = tmp_path / "gleif.zip"
    zp.write_bytes(_gleif_zip([(LEI_A, ISIN_A), (LEI_B, ISIN_B)]))
    store = ArtifactStore(tmp_path / "artifacts")
    ingest_gleif_isin_lei(store, tmp_path / "dataset", zp)
    dataset = tmp_path / "dataset"
    g7a = (dataset / "manifests"
           / "resolution_gleif_anna_isin_lei_2026-01-01.json")
    g1g6 = dataset / "manifests" / "2025-12.json"
    before_a, before_p = g7a.read_text(), g1g6.read_text()
    _ingest(store, tmp_path, _bundle(tmp_path))
    assert g7a.read_text() == before_a               # G7-A intact
    assert g1g6.read_text() == before_p              # G1-G6 intact
