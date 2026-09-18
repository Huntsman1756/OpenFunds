"""Artifact-store idempotency/versioning + deterministic export."""

from __future__ import annotations

import json
from decimal import Decimal

from cnmv_iic.adapters.fondcart import parse_fondcart, reconcile
from cnmv_iic.domain import (
    FundIdentity,
    IsinState,
    PortfolioSnapshot,
    Position,
    PositionKind,
    Provenance,
)
from cnmv_iic.storage import canonical_fingerprint, position_rows, write_period
from tests.conftest import FONDCART_XML, PDV_XML


def test_put_idempotent_same_bytes(store, fondcart_zip):
    a1, new1 = store.put(period="2025-12", source_page="t", source_url="u",
                         content_type=None, data=fondcart_zip)
    a2, new2 = store.put(period="2025-12", source_page="t", source_url="u",
                         content_type=None, data=fondcart_zip)
    assert new1 and not new2
    assert a1.source_id == a2.source_id
    assert len(store.load()) == 1


def test_changed_bytes_versioned_not_overwritten(store, fondcart_zip):
    a1, _ = store.put(period="2025-12", source_page="t", source_url="u",
                      content_type=None, data=fondcart_zip)
    modified = fondcart_zip + b" "  # different bytes, same period
    a2, new2 = store.put(period="2025-12", source_page="t", source_url="u2",
                         content_type=None, data=modified)
    assert new2
    assert a2.source_id != a1.source_id
    assert a2.supersedes == a1.source_id
    assert len(store.load()) == 2
    # original raw artifact untouched
    assert store.verify_integrity(a1)


def _snap(period="2025-12", mv=Decimal("10.00")) -> PortfolioSnapshot:
    prov = Provenance("id", "s", "m", "ms", "FondCart/Entidad[1]", "p", "v")
    pos = Position(
        kind=PositionKind.SECURITY, clase_if="INTERIOR",
        descripcion_if="X", descripcion_valor="A|B", divisa="EUR",
        reported_market_value=mv, isin_raw="US0378331005",
        isin_state=IsinState.VALID, provenance=prov,
        derived_weight=Decimal("0.1"),
    )
    return PortfolioSnapshot(FundIdentity("FI", "1", "0"), period, (pos,))


def test_canonical_fingerprint_stable():
    s1 = position_rows([_snap()])
    s2 = position_rows([_snap()])
    assert canonical_fingerprint(s1) == canonical_fingerprint(s2)
    # different value -> different fingerprint
    s3 = position_rows([_snap(mv=Decimal("11.00"))])
    assert canonical_fingerprint(s1) != canonical_fingerprint(s3)


def test_write_period_deterministic(tmp_path, artifact):
    snaps = parse_fondcart(
        FONDCART_XML, artifact=artifact,
        member_name="FONDCART_202512.xml", member_sha256="x" * 64,
    )
    reconcile(snaps, PDV_XML)
    m1 = write_period(tmp_path / "a", snaps, period="2025-12",
                      artifact_id=artifact.source_id)
    m2 = write_period(tmp_path / "b", snaps, period="2025-12",
                      artifact_id=artifact.source_id)
    assert m1["dataset_fingerprint"] == m2["dataset_fingerprint"]
    assert m1["positions"] == 3
    manifest = json.loads(
        (tmp_path / "a" / "manifests" / "2025-12.json").read_text()
    )
    assert manifest["source_artifact_id"] == artifact.source_id


def test_row_sort_order(tmp_path, artifact):
    # two entities out of document order must emit canonical order
    prov = Provenance("id", "s", "m", "ms", "l", "p", "v")

    def pos(mv):
        return Position(
            kind=PositionKind.SECURITY, clase_if="I", descripcion_if="d",
            descripcion_valor="v", divisa="EUR", reported_market_value=mv,
            isin_raw=None, isin_state=IsinState.ABSENT, provenance=prov,
        )

    snaps = [
        PortfolioSnapshot(FundIdentity("FI", "99", "0"), "2025-12",
                          (pos(Decimal("2")),)),
        PortfolioSnapshot(FundIdentity("FI", "7", "0"), "2025-12",
                          (pos(Decimal("1")),)),
    ]
    rows = position_rows(snaps)
    assert [r["numero_registro"] for r in rows] == ["7", "99"]  # numeric order
