"""G4-A — FONDTRIM adapter: quarterly share-class metrics, verbatim semantics."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondtrim import parse_fondtrim
from cnmv_iic.domain import IsinState, RegistryJoinState
from cnmv_iic.errors import ParseError, UnsupportedSchemaError
from cnmv_iic.storage import write_period

_REG_KEYS = frozenset({"FI:9:0:1", "FI:9:0:2"})


def _block(name: str, cells: dict[str, str] | None) -> str:
    if cells is None:
        return ""
    body = "".join(f"<{t}>{v}</{t}>" for t, v in cells.items())
    return f"<{name}>{body}</{name}>"


def _clase(nclase: str, isin: str | None = "ES0138841038",
           extra: str = "", rent=None, gastos=None, vol=None) -> str:
    isin_el = f"<ISIN>{isin}</ISIN>" if isin else ""
    return (
        f"<Clase><NumeroClase>{nclase}</NumeroClase>{isin_el}"
        f"<CodigoDivisa>EUR</CodigoDivisa>"
        f"<Patrimonio>1000.00</Patrimonio>"
        f"<ValorLiquidativo>10.5000</ValorLiquidativo>"
        f"<NumeroParticipaciones>95.24</NumeroParticipaciones>"
        f"<NumeroParticipes>7</NumeroParticipes>"
        f"<ComisionGestion>0.50</ComisionGestion>"
        f"<ComisionDepositario>0.02</ComisionDepositario>"
        f"<ComisionSuscripcionMinima>0.00</ComisionSuscripcionMinima>"
        f"<ComisionSuscripcionMaxima>2.00</ComisionSuscripcionMaxima>"
        f"<ComisionReembolsoMinima>0.00</ComisionReembolsoMinima>"
        f"<ComisionReembolsoMaxima>1.00</ComisionReembolsoMaxima>"
        f"<ComisionDescuentoFavorFondoMinima>0.00"
        f"</ComisionDescuentoFavorFondoMinima>"
        f"<ComisionDescuentoFavorFondoMaxima>0.00"
        f"</ComisionDescuentoFavorFondoMaxima>"
        f"<BaseCalculo_ComisionGestion>Patrimonio"
        f"</BaseCalculo_ComisionGestion>"
        f"<PeriodicidadCalculoVL>Diaria</PeriodicidadCalculoVL>"
        f"{_block('Rentabilidad', rent)}"
        f"{_block('RatioTotalGastos', gastos)}"
        f"{_block('Volatilidad_VL', vol)}"
        f"{extra}</Clase>"
    )


def _trim(period: str, comps: list[tuple[str, str, str, list[str]]],
          divisa_iic: str | None = "EUR") -> bytes:
    """comps: (numero_registro, numero_compartimento, vocacion, [clase xml])."""
    body = "".join(
        f"<Entidad><Tipo>FI</Tipo><NumeroRegistro>{nr}</NumeroRegistro>"
        + (f"<CodigoDivisaIIC>{divisa_iic}</CodigoDivisaIIC>"
           if divisa_iic else "")
        + f"<Compartimento><NumeroCompartimento>{nc}</NumeroCompartimento>"
        + (f"<VocacionInversora>{voc}</VocacionInversora>" if voc else "")
        + f"{''.join(clases)}</Compartimento></Entidad>"
        for nr, nc, voc, clases in comps
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f"<FondTrim><FechaDatos>{period}</FechaDatos>{body}</FondTrim>"
    ).encode()


_FULL_BLOCKS = dict(
    rent={"Rentabilidad_TrimestreActual": "0.19",
          "Rentabilidad_T_1": "0.47",
          "Rentabilidad_T_2": "1.19",
          "Rentabilidad_T_3": "0.30"},
    gastos={"RatioTotalGastos_TrimestreActual": "0.26",
            "RatioTotalGastos_T_1": "0.26",
            "RatioTotalGastos_T_2": "0.26",
            "RatioTotalGastos_T_3": "0.26"},
    vol={"Volatilidad_TrimestreActual": "0.96",
         "Volatilidad_T_1": "1.16",
         "Volatilidad_T_2": "1.51",
         "Volatilidad_T_3": "2.27"},
)

TRIM = _trim("202512", [
    ("9", "0", "Renta Fija Euro", [
        _clase("1", **_FULL_BLOCKS),
        _clase("2", "ES0138841004", **_FULL_BLOCKS),
    ]),
    ("77", "0", "Renta Variable", [
        _clase("0", "ES0100000005", **_FULL_BLOCKS),   # clase 0, unresolved
    ]),
])


def _parse(artifact, xml=TRIM, registry_keys=_REG_KEYS):
    return parse_fondtrim(
        xml, artifact=artifact, member_name="FONDTRIM_202512.xml",
        member_sha256="m" * 64, registry_keys=registry_keys)


def _by_key(rows, key):
    return [r for r in rows if r.share_class_key == key][0]


# ---------------------------------------------------------------------------
# adapter — fields, blocks, grain
# ---------------------------------------------------------------------------


def test_parse_fully_populated(artifact):
    r = _by_key(_parse(artifact), "FI:9:0:1")
    assert r.period == "2025-12"
    assert r.patrimonio == Decimal("1000.00")
    assert r.valor_liquidativo == Decimal("10.5000")
    assert r.numero_participaciones == Decimal("95.24")
    assert r.numero_participes == 7
    assert r.comision_gestion == Decimal("0.50")
    assert r.comision_suscripcion_maxima == Decimal("2.00")
    assert r.base_calculo_comision_gestion == "Patrimonio"
    assert r.periodicidad_calculo_vl == "Diaria"
    assert r.official_return_t == Decimal("0.19")
    assert r.official_return_t_3 == Decimal("0.30")
    assert r.ratio_total_gastos_t == Decimal("0.26")
    assert r.volatilidad_vl_t_3 == Decimal("2.27")
    # compartment/entity attrs denormalized onto the class record
    assert r.vocacion_inversora == "Renta Fija Euro"
    assert r.codigo_divisa_iic == "EUR"
    assert r.codigo_divisa == "EUR"
    assert r.registry_state is RegistryJoinState.RESOLVED
    assert r.isin_state is IsinState.VALID
    assert r.fund_key == "FI:9"
    assert r.compartment_key == "FI:9:0"
    assert r.provenance.xml_locator.endswith("Clase[1]")


def test_zero_is_observed_not_sentinel(artifact):
    # 0.00 fees are real observed values (contrast with FONDMENS '0')
    r = _by_key(_parse(artifact), "FI:9:0:1")
    assert r.comision_suscripcion_minima == Decimal("0.00")
    assert r.comision_descuento_favor_fondo_minima == Decimal("0.00")


def test_clase_zero_fund_level(artifact):
    r = _by_key(_parse(artifact), "FI:77:0:0")
    assert r.numero_clase == "0"
    assert r.registry_state is RegistryJoinState.UNRESOLVED


def test_negative_fee_preserved(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<ComisionGestion>0.50</ComisionGestion>",
            "<ComisionGestion>-1.02</ComisionGestion>"),
    ])])
    r = _by_key(_parse(artifact, xml), "FI:9:0:1")
    assert r.comision_gestion == Decimal("-1.02")


def test_empty_rolling_container_is_missing(artifact):
    # <Rentabilidad/> present but empty — measured in 2025-12 (243 cases)
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", rent={}, gastos=_FULL_BLOCKS["gastos"],
               vol=_FULL_BLOCKS["vol"]),
    ])])
    r = _by_key(_parse(artifact, xml), "FI:9:0:1")
    assert r.official_return_t is None
    assert r.official_return_t_1 is None
    assert r.official_return_t_2 is None
    assert r.official_return_t_3 is None
    assert r.ratio_total_gastos_t == Decimal("0.26")  # sibling block intact


def test_partial_rolling_history(artifact):
    # T_2/T_3 absent — insufficient history, missing not zero
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", rent={"Rentabilidad_TrimestreActual": "0.19",
                          "Rentabilidad_T_1": "0.47"},
               gastos=_FULL_BLOCKS["gastos"], vol=_FULL_BLOCKS["vol"]),
    ])])
    r = _by_key(_parse(artifact, xml), "FI:9:0:1")
    assert r.official_return_t == Decimal("0.19")
    assert r.official_return_t_1 == Decimal("0.47")
    assert r.official_return_t_2 is None
    assert r.official_return_t_3 is None


def test_absent_optional_elements(artifact):
    r = _by_key(_parse(artifact), "FI:9:0:1")
    assert r.sistema_imputacion_comisiones is None   # not in fixture
    assert r.beneficio_dividendo_bruto is None
    assert r.clase_fondo is None


def test_absent_codigo_divisa_iic(artifact):
    xml = _trim("202512", [("9", "0", None, [_clase("1", **_FULL_BLOCKS)])],
                divisa_iic=None)
    r = _by_key(_parse(artifact, xml), "FI:9:0:1")
    assert r.codigo_divisa_iic is None
    assert r.codigo_divisa == "EUR"              # class currency intact


def test_non_eur_class_currency_preserved(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<CodigoDivisa>EUR</CodigoDivisa>",
            "<CodigoDivisa>USD</CodigoDivisa>"),
    ])])
    r = _by_key(_parse(artifact, xml), "FI:9:0:1")
    assert r.codigo_divisa == "USD"              # unit evidence, verbatim


def test_malformed_decimal_fails_closed(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<ComisionGestion>0.50</ComisionGestion>",
            "<ComisionGestion>abc</ComisionGestion>"),
    ])])
    with pytest.raises(ParseError, match="non-decimal ComisionGestion"):
        _parse(artifact, xml)


def test_missing_numero_clase_fails_closed(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<NumeroClase>1</NumeroClase>", ""),
    ])])
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, xml)


def test_duplicate_class_fails_closed(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS), _clase("1", **_FULL_BLOCKS),
    ])])
    with pytest.raises(ParseError, match="duplicate class key"):
        _parse(artifact, xml)


def test_unknown_element_fails_closed(artifact):
    xml = _trim("202512", [("9", "0", None, [
        _clase("1", extra="<TER>0.26</TER>", **_FULL_BLOCKS),
    ])])
    with pytest.raises(UnsupportedSchemaError):
        _parse(artifact, xml)


def test_no_registry_means_unresolved(artifact):
    rows = _parse(artifact, registry_keys=None)
    assert all(r.registry_state is RegistryJoinState.UNRESOLVED
               for r in rows)


def test_distinct_classes_not_deduplicated(artifact):
    # grain contract: sibling classes keep their own metric rows
    rows = _parse(artifact)
    assert len(rows) == 3
    keys = {r.share_class_key for r in rows}
    assert keys == {"FI:9:0:1", "FI:9:0:2", "FI:77:0:0"}


# ---------------------------------------------------------------------------
# storage
# ---------------------------------------------------------------------------


def test_quarterly_export_and_fingerprint(tmp_path, artifact):
    rows = _parse(artifact)
    m1 = write_period(tmp_path / "d1", [], period="2025-12",
                      artifact_id="a", quarterly=rows)
    m2 = write_period(tmp_path / "d2", [], period="2025-12",
                      artifact_id="a", quarterly=rows)
    assert m1["quarterly_metrics"] == 3
    assert m1["fondtrim_present"] is True
    assert m1["quarterly_fingerprint"] == m2["quarterly_fingerprint"]
    assert m1["dataset_fingerprint"]  # G1 fingerprint still emitted


def test_quarterly_parquet_roundtrip(tmp_path, artifact):
    import duckdb
    rows = _parse(artifact)
    write_period(tmp_path / "d", [], period="2025-12",
                 artifact_id="a", quarterly=rows)
    got = duckdb.execute(
        "SELECT share_class_key, comision_gestion, official_return_t,"
        "       codigo_divisa, registry_state"
        " FROM read_parquet(?) ORDER BY share_class_key",
        [str(tmp_path / "d/quarterly/period=2025-12/part-0.parquet")],
    ).fetchall()
    assert got[0] == ("FI:77:0:0", Decimal("0.50"), Decimal("0.19"),
                      "EUR", "unresolved_registry_reference")
    assert got[1][0] == "FI:9:0:1"
