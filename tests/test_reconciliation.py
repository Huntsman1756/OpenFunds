"""G4-C — patrimony reconciliation: derived, currency-checked comparisons."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.errors import NotFoundError
from cnmv_iic.query import patrimony_reconciliation
from cnmv_iic.storage import write_period
from tests.test_fondmens import _parse as _parse_mens
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


def _dataset(tmp_path, artifact, *, trim_xml=None, pdv_xml=None,
             trim_keys=None):
    """Dataset where FI:9:0's classes hold 1000.00/500.00 in MENS."""
    daily = _parse_mens(artifact)                    # MENS fixture, 2025-12
    quarterly = (_parse_trim(artifact, trim_xml,
                             registry_keys=trim_keys)
                 if trim_xml else None)
    patrimony = _parse_pdv(artifact, pdv_xml) if pdv_xml else None
    write_period(tmp_path / "dataset", [], period="2025-12",
                 artifact_id="a", daily=daily,
                 quarterly=quarterly, patrimony=patrimony)
    return tmp_path / "dataset"


def test_class_level_match(tmp_path, artifact):
    # TRIM patrimonio 1000.00 = MENS month-end aum 1000.00 (EUR both)
    root = _dataset(tmp_path, artifact, trim_xml=_trim("202512", [
        ("9", "0", "Renta Fija Euro", [_clase("1", **_FULL_BLOCKS)]),
    ]))
    out = patrimony_reconciliation(root, "2025-12")
    row = [r for r in out["comparisons"]
           if r["subject_key"] == "FI:9:0:1"][0]
    assert row["state"] == "match"
    assert row["rel_diff"] == 0
    assert row["left_source"] == "fondtrim.patrimonio"
    assert row["right_source"] == "fondmens.aum@month_end"


def test_compartment_sum_match(tmp_path, artifact):
    # PDV tp=2000 = TRIM class sum (1000+1000) = MENS sum (1000+1000)
    trim = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS), _clase("2", **_FULL_BLOCKS)])])
    pdv = _pdv("202512", [("9", _comp("0").replace(
        "<TotalPatrimonio>87336084.00</TotalPatrimonio>",
        "<TotalPatrimonio>2000.00</TotalPatrimonio>"))])
    root = _dataset(tmp_path, artifact, trim_xml=trim, pdv_xml=pdv)
    out = patrimony_reconciliation(root, "2025-12")
    rows = {r["metric"]: r for r in out["comparisons"]
            if r["subject_key"] == "FI:9:0"}
    assert rows["total_vs_trim_class_sum"]["state"] == "match"
    assert rows["total_vs_trim_class_sum"]["rel_diff"] == 0
    # MENS side: only FI:9:0:1 has daily rows in the fixture (1000)
    assert rows["total_vs_mens_aum_sum"]["state"] == "diff"


def test_currency_skip(artifact, tmp_path):
    # USD class: not comparable with EUR MENS — skipped, not compared
    trim = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<CodigoDivisa>EUR</CodigoDivisa>",
            "<CodigoDivisa>USD</CodigoDivisa>"),
    ])])
    root = _dataset(tmp_path, artifact, trim_xml=trim)
    out = patrimony_reconciliation(root, "2025-12")
    row = [r for r in out["comparisons"]
           if r["subject_key"] == "FI:9:0:1"][0]
    assert row["state"] == "skipped_currency"
    assert row["rel_diff"] is None            # no comparison performed


def test_missing_side_skip(artifact, tmp_path):
    # class in TRIM but never observed in MENS -> skipped_missing
    # (FI:9:0:3 is absent from the MENS fixture entirely)
    trim = _trim("202512", [("9", "0", None, [
        _clase("3", **_FULL_BLOCKS)])])
    root = _dataset(tmp_path, artifact, trim_xml=trim,
                    trim_keys=frozenset({"FI:9:0:3"}))
    out = patrimony_reconciliation(root, "2025-12")
    row = [r for r in out["comparisons"]
           if r["subject_key"] == "FI:9:0:3"
           and r["metric"] == "patrimonio_vs_mens_aum"][0]
    assert row["state"] == "skipped_missing"


def test_diff_state_not_error(tmp_path, artifact):
    # real source disagreement is reported, never hidden or fatal
    trim = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS).replace(
            "<Patrimonio>1000.00</Patrimonio>",
            "<Patrimonio>2000.00</Patrimonio>"),
    ])])
    root = _dataset(tmp_path, artifact, trim_xml=trim)
    out = patrimony_reconciliation(root, "2025-12")
    row = [r for r in out["comparisons"]
           if r["subject_key"] == "FI:9:0:1"][0]
    assert row["state"] == "diff"
    assert row["rel_diff"] == Decimal("1")    # 100% divergence, verbatim
    assert out["note"].startswith("derived comparison")


def test_summary_counts(tmp_path, artifact):
    trim = _trim("202512", [("9", "0", None, [
        _clase("1", **_FULL_BLOCKS)])])
    root = _dataset(tmp_path, artifact, trim_xml=trim)
    out = patrimony_reconciliation(root, "2025-12")
    assert out["period"] == "2025-12"
    assert sum(out["summary"].values()) == len(out["comparisons"])


def test_no_quarterly_data_fails_closed(tmp_path, artifact):
    # neither family present -> fail closed, no fabricated comparisons
    root = _dataset(tmp_path, artifact)
    with pytest.raises(NotFoundError):
        patrimony_reconciliation(root, "2025-12")
