"""G10-B — cnmv-iic verify: offline fingerprint re-derivation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.ingest import export_artifact
from cnmv_iic.verify import verify_dataset
from tests.conftest import (
    FONDCART_XML,
    FONDREGISTRO_XML,
    PDV_XML,
    make_zip,
)


@pytest.fixture()
def live(tmp_path: Path) -> dict:
    # artifact WITHOUT xsd members — the schema gate keys off
    # artifact.xsd_sha256, absent here
    store = ArtifactStore(tmp_path / "artifacts")
    art, _ = store.put(
        period="2025-12", source_page="t", source_url="t",
        content_type="application/zip",
        data=make_zip({
            "FONDCART_202512.xml": FONDCART_XML,
            "FONDPATRIMDISVAR_202512.xml": PDV_XML,
            "FONDREGISTRO_202512.xml": FONDREGISTRO_XML,
        }))
    ds = tmp_path / "dataset"
    export_artifact(store, ds, art)     # the real write path
    return {"data": tmp_path, "dataset": ds, "artifact": art}


def test_verify_ok(live):
    rep = verify_dataset(live["dataset"], live["data"] / "artifacts")
    assert rep["ok"], rep["problems"]
    assert rep["checks"]                          # non-empty
    names = {c["name"] for c in rep["checks"]}
    assert any("dataset_fingerprint" in n for n in names)
    assert any("registry_fingerprint" in n for n in names)


def test_verify_detects_manifest_tamper(live):
    mpath = live["dataset"] / "manifests" / "2025-12.json"
    m = json.loads(mpath.read_text())
    m["dataset_fingerprint"] = "0" * 64
    mpath.write_text(json.dumps(m))
    rep = verify_dataset(live["dataset"], live["data"] / "artifacts")
    assert not rep["ok"]
    assert "2025-12.json:dataset_fingerprint" in rep["problems"]


def test_verify_missing_artifact_skips(live, tmp_path):
    # point at an empty artifacts dir — period fingerprints are
    # reported as skipped, not silently passed
    rep = verify_dataset(
        live["dataset"], tmp_path / "empty-artifacts")
    assert any("dataset_fingerprint" in s for s in rep["skipped"])
    # registry (string tables) is still checked from parquet
    assert any("registry_fingerprint" in c["name"]
               for c in rep["checks"])


def test_verify_no_manifests(tmp_path):
    rep = verify_dataset(tmp_path / "ds")
    assert not rep["ok"]
