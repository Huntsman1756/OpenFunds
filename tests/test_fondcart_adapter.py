"""FONDCART adapter: parsing, deviations, adversarial inputs."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondcart import parse_fondcart, reconcile
from cnmv_iic.domain import IsinState, PositionKind
from cnmv_iic.errors import ParseError, UnsupportedSchemaError
from tests.conftest import FONDCART_XML, PDV_XML


def _parse(artifact, xml=FONDCART_XML):
    return parse_fondcart(
        xml, artifact=artifact, member_name="FONDCART_202512.xml",
        member_sha256="x" * 64,
    )


def test_parse_positions(artifact):
    snaps = _parse(artifact)
    assert len(snaps) == 1
    snap = snaps[0]
    assert snap.identity.key == "FI:42:0"
    assert snap.period == "2025-12"
    assert len(snap.positions) == 3

    p0, p1, p2 = snap.positions
    assert p0.kind is PositionKind.SECURITY
    assert p0.isin_state is IsinState.VALID
    assert p0.reported_market_value == Decimal("1000.50")
    assert p1.kind is PositionKind.CASH           # Depositos
    assert p1.isin_state is IsinState.ABSENT      # registered deviation
    assert p2.isin_state is IsinState.MASKED      # XXXXXXXXXXXX
    assert p2.isin_raw == "X" * 12


def test_decimal_exactness(artifact):
    snap = _parse(artifact)[0]
    assert snap.reported_total == Decimal("2000.00")
    # Decimal, not float: 1000.50/2000.00 has an exact decimal representation
    assert snap.positions[0].derived_weight == Decimal("0.50025")


def test_provenance_and_locator(artifact):
    p = _parse(artifact)[0].positions[1]
    assert p.provenance.source_artifact_id == artifact.source_id
    assert p.provenance.source_sha256 == artifact.sha256
    assert p.provenance.xml_locator == (
        "FondCart/Entidad[1]/Compartimento[1]/InversionesFinancieras[2]"
    )
    assert p.provenance.parser == "cnmv_iic.adapters.fondcart"


def test_descripcion_valor_verbatim(artifact):
    p = _parse(artifact)[0].positions[0]
    assert p.descripcion_valor == "ACCIONES|APPLE INC"  # never split


def test_doctype_rejected(artifact):
    evil = FONDCART_XML.replace(
        b"<FondCart>",
        b'<!DOCTYPE x [<!ENTITY e SYSTEM "file:///c:/windows/win.ini">]><FondCart>',
    )
    with pytest.raises(ParseError):
        _parse(artifact, evil)


def test_unknown_element_rejected(artifact):
    evil = FONDCART_XML.replace(
        b"<DescripcionIF>Renta Variable Cotizada</DescripcionIF>",
        b"<DescripcionIF>Renta Variable Cotizada</DescripcionIF><Backdoor>x</Backdoor>",
    )
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, evil)


def test_missing_required_element_rejected(artifact):
    broken = FONDCART_XML.replace(
        b"<ValorMercado>1000.50</ValorMercado>", b"", 1
    )
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, broken)


def test_missing_divisa_allowed_as_registered_deviation(artifact):
    xml = FONDCART_XML.replace(b"<Divisa>USD</Divisa>", b"", 1)
    snap = _parse(artifact, xml)[0]
    assert snap.positions[0].divisa is None


def test_bad_fechadatos_rejected(artifact):
    xml = FONDCART_XML.replace(b"<FechaDatos>202512</FechaDatos>",
                               b"<FechaDatos>202513</FechaDatos>")
    with pytest.raises(ParseError):
        _parse(artifact, xml)


def test_non_decimal_valormercado_rejected(artifact):
    xml = FONDCART_XML.replace(b"<ValorMercado>1000.50</ValorMercado>",
                               b"<ValorMercado>abc</ValorMercado>")
    with pytest.raises(ParseError):
        _parse(artifact, xml)


def test_reconcile_exact(artifact):
    snaps = _parse(artifact)
    reconcile(snaps, PDV_XML)
    q = snaps[0].quality[0]
    assert q.state == "exact"
    assert q.abs_diff == Decimal("0.00")
    assert q.rel_diff == Decimal("0")


def test_reconcile_divergent_kept(artifact):
    snaps = _parse(artifact)
    divergent_pdv = PDV_XML.replace(b"<TotalPatrimonio>2000.00</TotalPatrimonio>",
                                  b"<TotalPatrimonio>5000.00</TotalPatrimonio>")
    divergent_pdv = divergent_pdv.replace(b"<CarteraInterior>1000.50</CarteraInterior>",
                                        b"<CarteraInterior>4000.50</CarteraInterior>")
    reconcile(snaps, divergent_pdv)
    q = snaps[0].quality[0]
    assert q.state == "divergent"
    assert q.abs_diff == Decimal("3000.00")
    assert len(snaps[0].positions) == 3  # divergent entity NOT dropped
