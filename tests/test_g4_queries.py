"""G4-D — quarterly metrics/fees/official-returns/allocation accessors."""

from __future__ import annotations

import pytest

from cnmv_iic.errors import NotFoundError
from cnmv_iic.query import (
    official_returns,
    patrimony_allocation,
    quarterly_fees,
    quarterly_metrics,
)
from cnmv_iic.storage import write_period
from tests.test_fondpatrimdisvar import _comp, _pdv
from tests.test_fondpatrimdisvar import _parse as _parse_pdv
from tests.test_fondtrim import (
    _FULL_BLOCKS,
    _clase,
    _trim,
)
from tests.test_fondtrim import (
    _parse as _parse_trim,
)
from tests.test_identity import _records

_TR = _trim("202512", [("9", "0", "Renta Fija Euro", [
    _clase("1", **_FULL_BLOCKS), _clase("2", **_FULL_BLOCKS)])])


def _root(tmp_path, artifact, trim=None, pdv=None):
    write_period(
        tmp_path / "dataset", [], period="2025-12", artifact_id="a",
        records=_records(artifact),
        quarterly=_parse_trim(artifact, trim) if trim else None,
        patrimony=_parse_pdv(artifact, pdv) if pdv else None)
    return tmp_path / "dataset"


def test_metrics_groups_by_unit_basis(tmp_path, artifact):
    out = quarterly_metrics(
        _root(tmp_path, artifact, trim=_TR), "ES0138841038", "2025-12")
    i = out["identity"]
    assert i["share_class_key"] == "FI:9:0:1"
    assert i["codigo_divisa"] == "EUR"
    s = out["stock_in_class_currency"]
    assert s["patrimonio"] is not None
    assert out["fees_pct"]["comision_gestion"] is not None
    # provenance + semantics present, values verbatim
    assert out["provenance"]["source_artifact_id"]
    assert "codigo_divisa" in out["semantics"]["stock_fields"]


def test_metrics_fund_key_fails_closed(tmp_path, artifact):
    # FONDTRIM is class-grained: FI:9 can never return a class row
    with pytest.raises(NotFoundError):
        quarterly_metrics(
            _root(tmp_path, artifact, trim=_TR), "FI:9", "2025-12")


def test_fees_subset(tmp_path, artifact):
    out = quarterly_fees(
        _root(tmp_path, artifact, trim=_TR), "FI:9:0:1", "2025-12")
    assert set(out["fees_pct"]) == {
        "comision_gestion", "comision_depositario",
        "comision_suscripcion_minima", "comision_suscripcion_maxima",
        "comision_reembolso_minima", "comision_reembolso_maxima",
        "comision_descuento_favor_fondo_minima",
        "comision_descuento_favor_fondo_maxima"}
    assert "patrimonio" not in out["fees_pct"]


def test_official_returns_series(tmp_path, artifact):
    meta, rows = official_returns(
        _root(tmp_path, artifact, trim=_TR), "FI:9:0:1", None, None)
    assert meta["periods"] == 1
    assert rows[0]["period"] == "2025-12"
    assert rows[0]["official_return_pct"] is not None
    assert "never recomputed" in meta["semantics"]


def test_allocation_splits_units(tmp_path, artifact):
    root = _root(
        tmp_path, artifact,
        pdv=_pdv("202512", [("9", _comp("0"))]))
    meta, rows = patrimony_allocation(root, "FI:9:0", "2025-12")
    assert meta["compartments"] == 1
    r = rows[0]
    assert r["compartment_key"] == "FI:9:0"
    m, p = r["monetary_in_iic_currency"], r["pct_of_avg_daily_patrimonio"]
    assert m["total_patrimonio"] is not None
    assert "total_patrimonio" not in p          # stock is never a %
    assert "suscripciones_reembolsos_netos" in p  # flow is never monetary
    assert "comisiones_descuento" in p            # all pct fields present


def test_allocation_isin_and_fund(tmp_path, artifact):
    # ISIN -> share class -> compartment owner; fund -> all compartments
    root = _root(
        tmp_path, artifact,
        pdv=_pdv("202512", [("9", _comp("0")), ("9", _comp("1"))]))
    _, by_isin = patrimony_allocation(root, "ES0138841038", "2025-12")
    assert [r["compartment_key"] for r in by_isin] == ["FI:9:0"]
    _, by_fund = patrimony_allocation(root, "FI:9", "2025-12")
    assert [r["compartment_key"] for r in by_fund] == ["FI:9:0", "FI:9:1"]


def test_allocation_no_table_fails_closed(tmp_path, artifact):
    with pytest.raises(NotFoundError):
        patrimony_allocation(
            _root(tmp_path, artifact, trim=_TR), "FI:9:0", "2025-12")
