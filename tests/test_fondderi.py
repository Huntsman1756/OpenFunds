"""G5 — FONDDERI adapter, enums, verbatim text, coverage, storage."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondderi import parse_fondderi
from cnmv_iic.domain import (
    DerivativeObjective,
    DerivativeRepresentation,
    DerivativeSide,
    RegistryJoinState,
    UnderlierClass,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.storage import write_period
from tests.test_identity import _records

_REG_KEYS = frozenset({"FI:9:0", "FI:9:1"})


def _op(desc="Obligaciones en renta fija", suby="BO. NOCIONAL 6% 5YR",
        instr="C/ FUTURO BOBL MAR 26", imp="14594930.00",
        obj="Inversión") -> str:
    o = f"<Objetivo>{obj}</Objetivo>" if obj is not None else ""
    return (f"<OperativaDerivados><Descripcion>{desc}</Descripcion>"
            f"<Subyacente>{suby}</Subyacente>"
            f"<Instrumento>{instr}</Instrumento>"
            f"<Importe>{imp}</Importe>{o}</OperativaDerivados>")


def _deri(period="202512", entities=None) -> bytes:
    """entities: [(tipo, nreg, divisa_or_None, [(ncomp, [ops])])]."""
    if entities is None:
        entities = [("FI", "9", "EUR", [("0", [_op()])])]
    body = ""
    for tipo, nreg, divisa, comps in entities:
        d = f"<CodigoDivisaIIC>{divisa}</CodigoDivisaIIC>" if divisa else ""
        cb = "".join(
            f"<Compartimento><NumeroCompartimento>{nc}</NumeroCompartimento>"
            f"{''.join(ops)}</Compartimento>"
            for nc, ops in comps)
        body += (f"<Entidad><Tipo>{tipo}</Tipo>"
                 f"<NumeroRegistro>{nreg}</NumeroRegistro>{d}{cb}</Entidad>")
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f"<FondDeri><FechaDatos>{period}</FechaDatos>{body}</FondDeri>"
            ).encode()


def _parse(artifact, xml=None, keys=_REG_KEYS):
    return parse_fondderi(
        xml if xml is not None else _deri(), artifact=artifact,
        member_name="FONDDERI_202512.xml", member_sha256="m" * 64,
        registry_compartment_keys=keys)


def test_parse_one_operation(artifact):
    ops, cov = _parse(artifact)
    assert len(ops) == 1 and len(cov) == 1
    o = ops[0]
    assert o.compartment_key == "FI:9:0"
    assert o.fund_key == "FI:9"
    assert o.operation_index == 1
    assert o.descripcion == "Obligaciones en renta fija"
    assert o.side is DerivativeSide.OBLIGACION
    assert o.underlier_class is UnderlierClass.RENTA_FIJA
    assert o.subyacente == "BO. NOCIONAL 6% 5YR"          # verbatim
    assert o.instrumento == "C/ FUTURO BOBL MAR 26"     # verbatim
    assert o.importe == Decimal("14594930.00")
    assert o.objetivo is DerivativeObjective.INVERSION
    assert o.representation is (
        DerivativeRepresentation.PARTIALLY_STRUCTURED)
    assert o.registry_state is RegistryJoinState.RESOLVED
    assert o.period == "2025-12"
    assert "OperativaDerivados[1]" in o.provenance.xml_locator


def test_all_descripcion_values_decompose(artifact):
    descs = [
        ("Obligaciones en renta fija",
         DerivativeSide.OBLIGACION, UnderlierClass.RENTA_FIJA),
        ("Obligaciones en renta variable",
         DerivativeSide.OBLIGACION, UnderlierClass.RENTA_VARIABLE),
        ("Obligaciones en tipos de cambio",
         DerivativeSide.OBLIGACION, UnderlierClass.TIPO_DE_CAMBIO),
        ("Otras Obligaciones",
         DerivativeSide.OBLIGACION, UnderlierClass.OTROS),
        ("Derechos en renta fija",
         DerivativeSide.DERECHO, UnderlierClass.RENTA_FIJA),
        ("Derechos en renta variable",
         DerivativeSide.DERECHO, UnderlierClass.RENTA_VARIABLE),
        ("Derechos en tipos de cambio",
         DerivativeSide.DERECHO, UnderlierClass.TIPO_DE_CAMBIO),
        ("Otros Derechos",
         DerivativeSide.DERECHO, UnderlierClass.OTROS),
    ]
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", [_op(desc=d) for d, _, _ in descs])])])
    ops, _ = _parse(artifact, xml)
    for o, (_, side, uc) in zip(ops, descs, strict=True):
        assert o.side is side and o.underlier_class is uc


def test_unknown_descripcion_fails_closed(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", [_op(desc="FUTURO SOBRE IBEX")])])])
    with pytest.raises(ParseError, match="closed enum"):
        _parse(artifact, xml)


def test_unknown_objetivo_fails_closed(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", [_op(obj="Especulación")])])])
    with pytest.raises(ParseError, match="closed enum"):
        _parse(artifact, xml)


def test_absent_objetivo_is_none(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [("0", [_op(obj=None)])])])
    ops, _ = _parse(artifact, xml)
    assert ops[0].objetivo is None            # missing, never inferred


def test_free_text_never_parsed(artifact):
    # pipe-delimited text stays verbatim — no underlier/expiry extraction
    xml = _deri(entities=[("FI", "9", "EUR", [("0", [
        _op(instr="FUTURO|EUR/USD|125000|FÍSICA",
            suby="EU3M         FUTURO|LIFFE      LC EURIBOR-M2  |")])])])
    ops, _ = _parse(artifact, xml)
    assert ops[0].instrumento == "FUTURO|EUR/USD|125000|FÍSICA"
    assert ops[0].subyacente == \
        "EU3M         FUTURO|LIFFE      LC EURIBOR-M2  |"
    assert not hasattr(ops[0], "underlier")
    assert not hasattr(ops[0], "expiry")


def test_negative_importe_signed(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", [_op(imp="-1234.56")])])])
    ops, _ = _parse(artifact, xml)
    assert ops[0].importe == Decimal("-1234.56")


def test_bad_importe_fails_closed(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", [_op(imp="abc")])])])
    with pytest.raises(ParseError, match="non-decimal"):
        _parse(artifact, xml)


def test_zero_operations_coverage(artifact):
    # compartment present with zero ops -> explicit coverage row, no ops
    xml = _deri(entities=[("FI", "9", "EUR", [
        ("0", []), ("1", [_op()])])])
    ops, cov = _parse(artifact, xml)
    assert len(ops) == 1
    c0 = [c for c in cov if c.compartment_key == "FI:9:0"][0]
    assert c0.n_operations == 0               # explicitly reported none
    c1 = [c for c in cov if c.compartment_key == "FI:9:1"][0]
    assert c1.n_operations == 1


def test_duplicate_compartment_fails(artifact):
    xml = (b'<?xml version="1.0"?><FondDeri><FechaDatos>202512</FechaDatos>'
           b"<Entidad><Tipo>FI</Tipo><NumeroRegistro>9</NumeroRegistro>"
           b"<Compartimento><NumeroCompartimento>0</NumeroCompartimento>"
           b"</Compartimento>"
           b"<Compartimento><NumeroCompartimento>0</NumeroCompartimento>"
           b"</Compartimento></Entidad></FondDeri>")
    with pytest.raises(ParseError, match="duplicate"):
        _parse(artifact, xml)


def test_unresolved_registry_state(artifact):
    xml = _deri(entities=[("FI", "77", "EUR", [("0", [_op()])])])
    ops, cov = _parse(artifact, xml)
    assert ops[0].registry_state is RegistryJoinState.UNRESOLVED
    assert cov[0].registry_state is RegistryJoinState.UNRESOLVED


def test_operation_order_preserved(artifact):
    xml = _deri(entities=[("FI", "9", "EUR", [("0", [
        _op(instr="A"), _op(instr="B"), _op(instr="C")])])])
    ops, _ = _parse(artifact, xml)
    assert [o.operation_index for o in ops] == [1, 2, 3]
    assert [o.instrumento for o in ops] == ["A", "B", "C"]


def test_parquet_roundtrip(tmp_path, artifact):
    ops, cov = _parse(artifact)
    write_period(tmp_path / "dataset", [], period="2025-12",
                 artifact_id="a", records=_records(artifact),
                 derivatives=ops, derivative_coverage=cov)
    import duckdb
    con = duckdb.connect()
    con.execute(
        "SELECT * FROM read_parquet(?)",
        [str(tmp_path / "dataset" / "derivatives" / "period=2025-12"
             / "part-0.parquet")])
    row = con.fetchone()
    cols = [c[0] for c in con.description]
    d = dict(zip(cols, row, strict=True))
    assert d["descripcion"] == "Obligaciones en renta fija"
    assert d["side"] == "obligacion"
    assert d["importe"] == Decimal("14594930.00")
    assert d["representation"] == "partially_structured"
    con.execute(
        "SELECT n_operations FROM read_parquet(?)",
        [str(tmp_path / "dataset" / "derivative_coverage"
             / "period=2025-12" / "part-0.parquet")])
    assert con.fetchone() == (1,)
