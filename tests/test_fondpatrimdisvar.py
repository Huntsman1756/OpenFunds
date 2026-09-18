"""G4-B — FONDPATRIMDISVAR adapter: compartment patrimony, mixed units."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondpatrimdisvar import parse_fondpatrimdisvar
from cnmv_iic.domain import PDV_UNIT_BASIS, RegistryJoinState
from cnmv_iic.errors import ParseError, UnsupportedSchemaError
from cnmv_iic.storage import write_period

_REG_COMP_KEYS = frozenset({"FI:9:0", "FI:9:1"})


def _comp(ncomp: str, extra: str = "", irc_ant: str | None = "0.42") -> str:
    irc_el = (f"<IndiceRotacionCarteraAnterior>{irc_ant}"
              f"</IndiceRotacionCarteraAnterior>") if irc_ant else ""
    return (
        f"<Compartimento><NumeroCompartimento>{ncomp}</NumeroCompartimento>"
        f"<IndiceRotacionCarteraActual>0.01</IndiceRotacionCarteraActual>"
        f"{irc_el}"
        f"<DPInversionesFinancieras>86776674.00</DPInversionesFinancieras>"
        f"<CarteraInterior>23942487.00</CarteraInterior>"
        f"<CarteraExterior>61040524.00</CarteraExterior>"
        f"<InteresesCartera>1793663.00</InteresesCartera>"
        f"<InversionesDudosas>0.00</InversionesDudosas>"
        f"<Liquidez>474720.00</Liquidez>"
        f"<Resto>84690.00</Resto>"
        f"<TotalPatrimonio>87336084.00</TotalPatrimonio>"
        f"<PatrimonioFinPeriodoAnterior>89734787.00"
        f"</PatrimonioFinPeriodoAnterior>"
        f"<Suscripciones_Reembolsos_Netos>-4.88"
        f"</Suscripciones_Reembolsos_Netos>"
        f"<BeneficiosBrutosDistribuidos>0.00</BeneficiosBrutosDistribuidos>"
        f"<RendimientosNetos>2.15</RendimientosNetos>"
        f"<RendimientosGestion>3.15</RendimientosGestion>"
        f"<Intereses>2.73</Intereses>"
        f"<Dividendos>0.00</Dividendos>"
        f"<ResultadosRentaFija>0.00</ResultadosRentaFija>"
        f"<ResultadosRentaVariable>0.00</ResultadosRentaVariable>"
        f"<ResultadosDepositos>0.00</ResultadosDepositos>"
        f"<ResultadosDerivados>-0.07</ResultadosDerivados>"
        f"<ResultadosIIC>0.49</ResultadosIIC>"
        f"<OtrosResultados>0.00</OtrosResultados>"
        f"<OtrosRendimientos>0.00</OtrosRendimientos>"
        f"<GastosRepercutidos>-1.00</GastosRepercutidos>"
        f"<ComisionGestion>-0.95</ComisionGestion>"
        f"<ComisionDepositario>-0.03</ComisionDepositario>"
        f"<GastosServiciosExteriores>-0.01</GastosServiciosExteriores>"
        f"<OtrosGastosGestion>-0.01</OtrosGastosGestion>"
        f"<OtrosGastosRepercutidos>-0.01</OtrosGastosRepercutidos>"
        f"<Ingresos>0.00</Ingresos>"
        f"<ComisionesDescuento>0.00</ComisionesDescuento>"
        f"<ComisionesRetrocedidas>0.00</ComisionesRetrocedidas>"
        f"<OtrosIngresos>0.00</OtrosIngresos>"
        f"<PatrimonioFinPeriodoActual>87336084.00"
        f"</PatrimonioFinPeriodoActual>"
        f"{extra}</Compartimento>"
    )


def _pdv(period: str, comps: list[tuple[str, str]],
         divisa_iic: str | None = "EUR") -> bytes:
    """comps: (numero_registro, compartimento xml)."""
    body = "".join(
        f"<Entidad><Tipo>FI</Tipo><NumeroRegistro>{nr}</NumeroRegistro>"
        + (f"<CodigoDivisaIIC>{divisa_iic}</CodigoDivisaIIC>"
           if divisa_iic else "")
        + f"{comp}</Entidad>"
        for nr, comp in comps
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f"<FondPatrimDisVar><FechaDatos>{period}</FechaDatos>{body}"
        f"</FondPatrimDisVar>"
    ).encode()


PDV = _pdv("202512", [
    ("9", _comp("0")),
    ("9", _comp("1")),
    ("77", _comp("0")),
])


def _parse(artifact, xml=PDV, keys=_REG_COMP_KEYS):
    return parse_fondpatrimdisvar(
        xml, artifact=artifact, member_name="FONDPATRIMDISVAR_202512.xml",
        member_sha256="m" * 64, registry_compartment_keys=keys)


def _by_key(rows, key):
    return [r for r in rows if r.compartment_key == key][0]


def test_parse_fully_populated(artifact):
    r = _by_key(_parse(artifact), "FI:9:0")
    assert r.period == "2025-12"
    assert r.compartment_key == "FI:9:0"
    assert r.fund_key == "FI:9"
    # stock — monetary, IIC currency
    assert r.total_patrimonio == Decimal("87336084.00")
    assert r.dp_inversiones_financieras == Decimal("86776674.00")
    assert r.cartera_interior == Decimal("23942487.00")
    assert r.liquidez == Decimal("474720.00")
    assert r.resto == Decimal("84690.00")
    assert r.patrimonio_fin_periodo_anterior == Decimal("89734787.00")
    assert r.patrimonio_fin_periodo_actual == Decimal("87336084.00")
    # flow — SIGNED % over avg daily patrimonio (NOT money)
    assert r.suscripciones_reembolsos_netos == Decimal("-4.88")
    assert r.rendimientos_netos == Decimal("2.15")
    assert r.comision_gestion == Decimal("-0.95")
    assert r.comision_depositario == Decimal("-0.03")
    assert r.resultados_derivados == Decimal("-0.07")
    # ratios
    assert r.indice_rotacion_cartera_actual == Decimal("0.01")
    assert r.indice_rotacion_cartera_anterior == Decimal("0.42")
    assert r.codigo_divisa_iic == "EUR"
    assert r.registry_state is RegistryJoinState.RESOLVED
    assert r.provenance.xml_locator.endswith("Compartimento[1]")


def test_stock_identity_holds(artifact):
    # TP = IF + L + R — the source's own accounting identity
    r = _by_key(_parse(artifact), "FI:9:0")
    invested = (r.cartera_interior + r.cartera_exterior
                + r.intereses_cartera + r.inversiones_dudosas)
    assert r.dp_inversiones_financieras == invested
    assert r.total_patrimonio == invested + r.liquidez + r.resto


def test_zero_is_observed_value(artifact):
    r = _by_key(_parse(artifact), "FI:9:0")
    assert r.inversiones_dudosas == Decimal("0.00")
    assert r.dividendos == Decimal("0.00")


def test_irc_anterior_absent_for_new_compartment(artifact):
    xml = _pdv("202512", [("9", _comp("0", irc_ant=None))])
    r = _by_key(_parse(artifact, xml), "FI:9:0")
    assert r.indice_rotacion_cartera_anterior is None   # no prior period
    assert r.indice_rotacion_cartera_actual == Decimal("0.01")


def test_absent_codigo_divisa_iic(artifact):
    xml = _pdv("202512", [("9", _comp("0"))], divisa_iic=None)
    r = _by_key(_parse(artifact, xml), "FI:9:0")
    assert r.codigo_divisa_iic is None
    assert r.total_patrimonio == Decimal("87336084.00")


def test_malformed_decimal_fails_closed(artifact):
    xml = _pdv("202512", [("9", _comp("0").replace(
        "<TotalPatrimonio>87336084.00</TotalPatrimonio>",
        "<TotalPatrimonio>abc</TotalPatrimonio>"))])
    with pytest.raises(ParseError, match="non-decimal TotalPatrimonio"):
        _parse(artifact, xml)


def test_missing_numero_compartimento_fails_closed(artifact):
    xml = _pdv("202512", [("9", _comp("0").replace(
        "<NumeroCompartimento>0</NumeroCompartimento>", ""))])
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, xml)


def test_duplicate_compartment_fails_closed(artifact):
    xml = _pdv("202512", [("9", _comp("0")), ("9", _comp("0"))])
    with pytest.raises(ParseError, match="duplicate compartment key"):
        _parse(artifact, xml)


def test_unknown_element_fails_closed(artifact):
    xml = _pdv("202512", [("9", _comp("0", extra="<Foo>1</Foo>"))])
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, xml)


def test_unresolved_and_no_registry(artifact):
    r = _by_key(_parse(artifact), "FI:77:0")
    assert r.registry_state is RegistryJoinState.UNRESOLVED
    rows = _parse(artifact, keys=None)
    assert all(r.registry_state is RegistryJoinState.UNRESOLVED
               for r in rows)


def test_compartment_grain_no_class_rows(artifact):
    # measured: zero Clase elements — record count = compartment count
    rows = _parse(artifact)
    assert len(rows) == 3
    assert {r.compartment_key for r in rows} == {
        "FI:9:0", "FI:9:1", "FI:77:0"}


def test_unit_basis_map_covers_every_field(artifact):
    # every metric field of the dataclass has a declared unit basis
    from dataclasses import fields

    from cnmv_iic.domain import CompartmentPatrimonySnapshot
    metric = {f.name for f in fields(CompartmentPatrimonySnapshot)} - {
        "entity_type", "numero_registro", "numero_compartimento",
        "codigo_divisa_iic", "registry_state", "period", "provenance"}
    assert metric == set(PDV_UNIT_BASIS)


def test_flow_fields_signed_pct_not_money(artifact):
    # the central unit trap: flow fields are %, stock fields monetary
    assert PDV_UNIT_BASIS["suscripciones_reembolsos_netos"] == \
        "pct_over_avg_daily_patrimonio"
    assert PDV_UNIT_BASIS["comision_gestion"] == \
        "pct_over_avg_daily_patrimonio"
    assert PDV_UNIT_BASIS["total_patrimonio"] == "monetary_iic_currency"
    r = _by_key(_parse(artifact), "FI:9:0")
    assert r.suscripciones_reembolsos_netos < 0   # signed, not an amount


def test_patrimony_export_and_fingerprint(tmp_path, artifact):
    rows = _parse(artifact)
    m1 = write_period(tmp_path / "d1", [], period="2025-12",
                      artifact_id="a", patrimony=rows)
    m2 = write_period(tmp_path / "d2", [], period="2025-12",
                      artifact_id="a", patrimony=rows)
    assert m1["patrimony_records"] == 3
    assert m1["fondpatrimdisvar_present"] is True
    assert m1["patrimony_fingerprint"] == m2["patrimony_fingerprint"]
    assert m1["dataset_fingerprint"]


def test_patrimony_parquet_roundtrip(tmp_path, artifact):
    import duckdb
    rows = _parse(artifact)
    write_period(tmp_path / "d", [], period="2025-12",
                 artifact_id="a", patrimony=rows)
    got = duckdb.execute(
        "SELECT compartment_key, total_patrimonio,"
        "       suscripciones_reembolsos_netos, codigo_divisa_iic,"
        "       registry_state FROM read_parquet(?)"
        " ORDER BY compartment_key",
        [str(tmp_path / "d/patrimony/period=2025-12/part-0.parquet")],
    ).fetchall()
    assert got[0] == ("FI:77:0", Decimal("87336084.00"), Decimal("-4.88"),
                      "EUR", "unresolved_registry_reference")
    assert got[1][0] == "FI:9:0"
