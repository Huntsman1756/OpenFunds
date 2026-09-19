"""G10-B — public API surface (cnmv_iic.api.Dataset) smoke tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from cnmv_iic.api import Dataset, open_dataset, versions_contract
from cnmv_iic.domain import (
    FundIdentity,
)
from cnmv_iic.errors import NotFoundError
from cnmv_iic.storage import write_period
from cnmv_iic.versions import LIFECYCLE_ENGINE_VERSION
from tests.conftest import FONDREGISTRO_XML
from tests.test_identity import _records, _snap


@pytest.fixture()
def dataset(tmp_path: Path, artifact) -> Path:
    root = tmp_path / "dataset"
    write_period(
        root, [_snap(FundIdentity("FI", "9", "0"), Decimal("10.00"))],
        period="2025-12", artifact_id="aid",
        records=_records(artifact, FONDREGISTRO_XML))
    return root


def test_versions_contract():
    c = versions_contract()
    assert c["dataset_schema_version"] == "1"
    assert c["lifecycle_engine_version"] == LIFECYCLE_ENGINE_VERSION
    assert c["lifecycle_engine_version"] == "g9e-v1"
    for k in ("dataset_schema_version", "canonical_model_version",
              "lifecycle_engine_version", "lifecycle_parser_version",
              "lifecycle_rule_version", "parser_version"):
        assert c[k], k


def test_dataset_fund_and_holdings(dataset):
    d = Dataset(dataset)
    f = d.fund("ES0138841038")
    assert f["record"]["fund"]["denominacion"] == "FONMARCH, FI"
    h = d.holdings("ES0138841038")
    assert len(h["positions"]) == 1
    assert h["resolution"]["resolved_as"]


def test_dataset_info_compatibility(dataset):
    info = Dataset(dataset).info()
    assert info["compatibility"]["lifecycle_engine_version"] == "g9e-v1"


def test_dataset_not_found(dataset):
    with pytest.raises(NotFoundError):
        Dataset(dataset).fund("ES0138841039")


def test_open_dataset_explicit(tmp_path):
    d = open_dataset(tmp_path / "ds")
    assert d.root == tmp_path / "ds"
