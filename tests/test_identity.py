"""G2 — FONDREGISTRO adapter, identity resolution, mechanical diff, joins."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondregistro import parse_fondregistro
from cnmv_iic.domain import (
    FundIdentity,
    IsinState,
    PortfolioSnapshot,
    Position,
    PositionKind,
    Provenance,
    ResolutionKind,
)
from cnmv_iic.errors import NotFoundError
from cnmv_iic.identity import ShareClassRow, diff_registry, resolve
from cnmv_iic.query import (
    fund_info,
    funds_by_institution,
    funds_holding,
    holdings,
    identity_events,
    share_class_info,
)
from cnmv_iic.storage import write_period
from tests.conftest import FONDREGISTRO_XML


def _records(artifact, xml=FONDREGISTRO_XML):
    return parse_fondregistro(
        xml, artifact=artifact, member_name="FONDREGISTRO_202512.xml",
        member_sha256="r" * 64,
    )


def _srows(records):
    """Flatten records to ShareClassRows (mirrors the parquet view)."""
    out = []
    for r in records:
        for j, c in enumerate(r.compartments, start=1):
            ck = f"{r.key}:{c.numero_compartimento}"
            for k, cl in enumerate(c.classes, start=1):
                out.append(ShareClassRow(
                    share_class_key=f"{ck}:{cl.numero_clase}",
                    fund_key=r.key,
                    compartment_key=ck,
                    isin_raw=cl.isin_raw,
                    isin_state=cl.isin_state.value,
                    denominacion_clase=cl.denominacion,
                    xml_locator=(f"{r.provenance.xml_locator}"
                                 f"/Compartimento[{j}]/Clase[{k}]"),
                    source_artifact_id=r.provenance.source_artifact_id,
                ))
    return out


def _funds_map(records):
    return {r.key: tuple(r.portfolio_owners()) for r in records}


# ---------------------------------------------------------------------------
# adapter
# ---------------------------------------------------------------------------


def test_parse_fondregistro(artifact):
    recs = _records(artifact)
    assert len(recs) == 1
    r = recs[0]
    assert r.key == "FI:9"
    assert r.denominacion == "FONMARCH, FI"
    assert r.etf == "NO"
    assert r.period == "2025-12"
    assert r.gestora.numero_registro == "190"
    assert r.gestora.grupo_numero == "1"
    assert r.depositario.numero_registro == "211"
    assert r.depositario.grupo_numero == "7"
    assert [c.numero_compartimento for c in r.compartments] == ["0", "1"]
    assert r.portfolio_owners() == ["FI:9:0", "FI:9:1"]
    c0, c1 = r.compartments
    assert len(c0.classes) == 2 and len(c1.classes) == 1
    assert c0.classes[0].isin_raw == "ES0138841038"
    assert c0.classes[0].isin_state is IsinState.VALID
    assert c0.classes[0].denominacion == "CLASE A"
    assert r.provenance.xml_locator == "FondRegistro/Entidad[1]"


def test_parse_fondregistro_invalid_isin_preserved(artifact):
    xml = FONDREGISTRO_XML.replace(
        b"<ISIN>ES0138841012</ISIN>", b"<ISIN>ES0138841013</ISIN>", 1)
    recs = _records(artifact, xml)
    cl = recs[0].compartments[1].classes[0]
    assert cl.isin_raw == "ES0138841013"          # verbatim, never corrected
    assert cl.isin_state is IsinState.INVALID


def test_parse_fondregistro_absent_isin(artifact):
    xml = FONDREGISTRO_XML.replace(
        b"<ISIN>ES0138841012</ISIN>", b"", 1)
    recs = _records(artifact, xml)
    assert recs[0].compartments[1].classes[0].isin_state is IsinState.ABSENT


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


@pytest.fixture()
def resolved(artifact):
    recs = _records(artifact)
    return _srows(recs), _funds_map(recs)


def test_resolve_isin_to_compartment(resolved):
    srows, funds = resolved
    r = resolve("ES0138841038", srows, funds)
    assert r.kind is ResolutionKind.EXACT_SHARE_CLASS
    assert r.portfolio_owners == ("FI:9:0",)
    assert r.share_class_key == "FI:9:0:1"
    assert r.fund_key == "FI:9"
    assert r.registry_locator == ("FondRegistro/Entidad[1]"
                                  "/Compartimento[1]/Clase[1]")


def test_sibling_classes_share_one_portfolio(resolved):
    srows, funds = resolved
    r1 = resolve("ES0138841038", srows, funds)
    r2 = resolve("ES0138841004", srows, funds)
    assert r1.portfolio_owners == r2.portfolio_owners == ("FI:9:0",)
    assert r1.share_class_key != r2.share_class_key


def test_resolve_other_compartment(resolved):
    srows, funds = resolved
    r = resolve("ES0138841012", srows, funds)
    assert r.portfolio_owners == ("FI:9:1",)


def test_resolve_keys(resolved):
    srows, funds = resolved
    assert resolve("FI:9", srows, funds).kind is ResolutionKind.EXACT_FUND
    assert resolve("FI:9", srows, funds).portfolio_owners == ("FI:9:0", "FI:9:1")
    r = resolve("FI:9:0", srows, funds)
    assert r.kind is ResolutionKind.EXACT_COMPARTMENT
    assert r.portfolio_owners == ("FI:9:0",)
    r = resolve("FI:9:0:2", srows, funds)
    assert r.kind is ResolutionKind.EXACT_SHARE_CLASS
    assert r.share_class_isin == "ES0138841004"
    assert resolve("9", srows, funds).kind is ResolutionKind.EXACT_FUND


def test_resolve_not_found(resolved):
    srows, funds = resolved
    for ident in ("FI:999", "FI:9:9", "FI:9:0:9", "garbage", ""):
        r = resolve(ident, srows, funds)
        assert r.kind is ResolutionKind.NOT_FOUND, ident
        assert r.portfolio_owners == ()


def test_resolve_invalid_identifier(resolved):
    srows, funds = resolved
    # bad check digit — identifier itself is invalid, NOT ambiguous;
    # ambiguity is reserved for >1 plausible resolutions.
    for ident in ("ES0138841039", "ES0138841013", "XXXXXXXXXXXX"):
        r = resolve(ident, srows, funds)
        assert r.kind is ResolutionKind.INVALID_IDENTIFIER, ident
        assert r.portfolio_owners == ()


def test_resolve_ambiguous_only_for_multi_hit(resolved):
    srows, funds = resolved
    # same ISIN on two classes -> genuinely ambiguous
    dup = ShareClassRow(
        share_class_key="FI:9:0:9", fund_key="FI:9",
        compartment_key="FI:9:0", isin_raw="ES0138841038",
        isin_state=IsinState.VALID.value,
        denominacion_clase="DUP", xml_locator="x",
        source_artifact_id="a")
    r = resolve("ES0138841038", srows + [dup], funds)
    assert r.kind is ResolutionKind.AMBIGUOUS
    assert r.portfolio_owners == ()


def test_holdings_by_isin(dataset):
    period, res, rows = holdings(dataset, "ES0138841038", None)
    assert period == "2025-12"
    assert res["resolved_as"] == "exact_share_class"
    assert res["share_class_key"] == "FI:9:0:1"
    assert res["portfolio_owners"] == ["FI:9:0"]
    assert res["registry_artifact_id"]
    assert res["registry_locator"].endswith("Clase[1]")
    assert res["resolution_mode"] == "latest_available_before_or_on"
    assert res["stale"] is False
    assert len(rows) == 1
    assert rows[0]["fund_key"] == "FI:9:0"
    assert rows[0]["reported_market_value"] == Decimal("10.00")


# ---------------------------------------------------------------------------
# mechanical diff
# ---------------------------------------------------------------------------


def _without_compartment_1() -> bytes:
    i = FONDREGISTRO_XML.find(
        b"<Compartimento>\n      <NumeroCompartimento>1")
    j = FONDREGISTRO_XML.find(b"</Compartimento>", i) + len(b"</Compartimento>")
    return FONDREGISTRO_XML[:i] + FONDREGISTRO_XML[j:]


def test_diff_registry_events(artifact):
    old = _records(artifact)
    new_xml = (
        FONDREGISTRO_XML
        .replace(b"FONMARCH, FI", b"FONMARCH RENOMBRADO, FI", 1)
        .replace(b"<ISIN>ES0138841004</ISIN>", b"<ISIN>ES0113900J37</ISIN>", 1)
        .replace(b"<DenominacionGestora>MARCH ASSET MANAGEMENT, S.G.I.I.C., S.A.U.",
                 b"<DenominacionGestora>OTRA GESTORA", 1)
        .replace(b"<NumeroRegistroGestora>190</NumeroRegistroGestora>",
                 b"<NumeroRegistroGestora>191</NumeroRegistroGestora>", 1)
        .replace(b"<DenominacionDepositario>BANCO DEPOSITARIO, S.A.",
                 b"<DenominacionDepositario>OTRO DEPOSITARIO", 1)
    )
    events = diff_registry(old, _records(artifact, new_xml))
    kinds = {e.kind.value for e in events}
    assert kinds >= {"name_changed", "manager_changed", "depositary_changed",
                     "isin_changed"}
    mgr = next(e for e in events if e.kind.value == "manager_changed")
    assert mgr.fund_key == "FI:9"
    assert "191" in mgr.new
    assert all(e.from_period == "2025-12" and e.to_period == "2025-12"
               for e in events)


def test_diff_registry_class_and_compartment_events(artifact):
    old = _records(artifact)
    # old without compartment 1 -> new full: COMPARTMENT_ADDED + SHARE_CLASS_ADDED
    smaller = _records(artifact, _without_compartment_1())
    kinds = {e.kind.value for e in diff_registry(smaller, old)}
    assert {"compartment_added", "share_class_added"} <= kinds
    # reverse: removals
    kinds = {e.kind.value for e in diff_registry(old, smaller)}
    assert {"compartment_removed", "share_class_removed"} <= kinds


def test_diff_registry_whole_fund_add_remove_out_of_scope(artifact):
    old = _records(artifact)
    # diffing a populated snapshot against an empty one yields no events —
    # whole-fund addition/removal is intentionally out of gate scope.
    assert diff_registry(old, []) == []
    assert diff_registry([], old) == []


# ---------------------------------------------------------------------------
# end-to-end: dataset + query layer
# ---------------------------------------------------------------------------


def _snap(fund_identity: FundIdentity, mv=Decimal("10.00")) -> PortfolioSnapshot:
    prov = Provenance("aid", "s", "m", "ms", "FondCart/Entidad[1]", "p", "v")
    pos = Position(
        kind=PositionKind.SECURITY, clase_if="INTERIOR",
        descripcion_if="X", descripcion_valor="A|B", divisa="EUR",
        reported_market_value=mv, isin_raw="US0378331005",
        isin_state=IsinState.VALID, provenance=prov,
        derived_weight=Decimal("0.1"),
    )
    return PortfolioSnapshot(fund_identity, "2025-12", (pos,))


@pytest.fixture()
def dataset(tmp_path, artifact):
    root = tmp_path / "dataset"
    recs = _records(artifact)
    snaps = [_snap(FundIdentity("FI", "9", "0"), Decimal("10.00")),
             _snap(FundIdentity("FI", "9", "1"), Decimal("20.00"))]
    write_period(root, snaps, period="2025-12",
                 artifact_id="aid", records=recs)
    return root


def test_holdings_classes_not_duplicated(dataset):
    _, res1, rows1 = holdings(dataset, "ES0138841038", None)
    _, res2, rows2 = holdings(dataset, "ES0138841004", None)
    assert rows1 == rows2                       # same snapshot, no dup
    assert res1["portfolio_owners"] == res2["portfolio_owners"]
    assert len(rows1) == 1


def test_holdings_by_key_unchanged(dataset):
    period, res, rows = holdings(dataset, "FI:9:0", None)
    assert res["resolved_as"] == "exact_compartment"
    assert [r["position_seq"] for r in rows] == [1]
    _, res_f, rows_f = holdings(dataset, "FI:9", None)
    assert res_f["resolved_as"] == "exact_fund"
    assert res_f["portfolio_owners"] == ["FI:9:0", "FI:9:1"]
    assert {r["fund_key"] for r in rows_f} == {"FI:9:0", "FI:9:1"}


def test_holdings_not_found(dataset):
    with pytest.raises(NotFoundError):
        holdings(dataset, "ES0138841039", None)


def test_fund_info(dataset):
    period, res, rec = fund_info(dataset, "ES0138841038", None)
    assert rec["fund"]["denominacion"] == "FONMARCH, FI"
    assert rec["fund"]["gestora_numero_registro"] == "190"
    assert len(rec["compartments"]) == 2
    assert len(rec["share_classes"]) == 3
    period, res, rec = fund_info(dataset, "FI:9", None)
    assert res["resolved_as"] == "exact_fund"


def test_share_class_info(dataset):
    period, res, rec = share_class_info(dataset, "ES0138841004", None)
    assert rec["share_class"]["share_class_key"] == "FI:9:0:2"
    assert rec["share_class"]["compartment_key"] == "FI:9:0"
    assert rec["fund"]["fund_key"] == "FI:9"
    # a compartment key is not a share class — fail closed
    with pytest.raises(NotFoundError):
        share_class_info(dataset, "FI:9:0", None)


def test_funds_by_institution(dataset):
    period, inst, rows = funds_by_institution(dataset, "gestora", "190", None)
    assert inst["denominacion"].startswith("MARCH")
    assert [r["fund_key"] for r in rows] == ["FI:9"]
    period, inst, rows = funds_by_institution(
        dataset, "depositario", "211", None)
    assert len(rows) == 1
    _, inst, rows = funds_by_institution(dataset, "gestora", "999", None)
    assert inst is None and rows == []


def test_funds_holding_enriched(dataset):
    period, meta, rows = funds_holding(dataset, "US0378331005", None)
    assert len(rows) == 2
    assert rows[0]["denominacion"] == "FONMARCH, FI"
    assert meta["portfolio_period"] == "2025-12"
    assert meta["stale"] is False


def test_holdings_stale_metadata(dataset):
    # as-of after the only snapshot -> stale, honestly labelled
    _, res, rows = holdings(dataset, "FI:9:0", "2026-03-31")
    assert res["requested_as_of"] == "2026-03-31"
    assert res["portfolio_period"] == "2025-12"
    assert res["resolution_mode"] == "latest_available_before_or_on"
    assert res["stale"] is True
    assert len(rows) == 1


def test_holdings_exact(dataset):
    # --exact: snapshot exists at the as-of month -> works
    _, res, rows = holdings(dataset, "FI:9:0", "2025-12-15", exact=True)
    assert res["portfolio_period"] == "2025-12"
    assert res["resolution_mode"] == "exact"
    assert res["stale"] is False
    assert len(rows) == 1
    # --exact: no snapshot at the as-of month -> fail, no fallback
    with pytest.raises(NotFoundError, match="exactly at 2026-01"):
        holdings(dataset, "FI:9:0", "2026-01-31", exact=True)


def test_holdings_invalid_identifier_fails(dataset):
    with pytest.raises(NotFoundError, match="invalid_identifier"):
        holdings(dataset, "ES0138841039", None)  # bad check digit


def test_identity_events(dataset, tmp_path, artifact):
    # second period with a name change + removed class
    xml2 = (FONDREGISTRO_XML
            .replace(b"<FechaDatos>202512</FechaDatos>",
                     b"<FechaDatos>202601</FechaDatos>")
            .replace(b"FONMARCH, FI", b"FONMARCH NUEVO, FI", 1))
    recs2 = _records(artifact, xml2)
    write_period(dataset, [_snap(FundIdentity("FI", "9", "0"))],
                 period="2026-01", artifact_id="aid2", records=recs2)
    events = identity_events(dataset, "2025-12", "2026-01")
    kinds = {e["kind"] for e in events}
    assert "name_changed" in kinds
    assert all(e["from_period"] == "2025-12" for e in events)
    assert all(e["to_period"] == "2026-01" for e in events)
    # filter to one fund
    events_f = identity_events(dataset, "2025-12", "2026-01", fund="FI:9")
    assert all(e["fund_key"] == "FI:9" for e in events_f)


def test_registry_fingerprint_deterministic(dataset, tmp_path, artifact):
    recs = _records(artifact)
    m1 = write_period(tmp_path / "d1", [_snap(FundIdentity("FI", "9", "0"))],
                      period="2025-12", artifact_id="a", records=recs)
    m2 = write_period(tmp_path / "d2", [_snap(FundIdentity("FI", "9", "0"))],
                      period="2025-12", artifact_id="a", records=recs)
    assert m1["registry_fingerprint"] == m2["registry_fingerprint"]
    assert m1["dataset_fingerprint"] == m2["dataset_fingerprint"]
    assert m1["funds"] == 1 and m1["share_classes"] == 3
    assert m1["compartments"] == 2
