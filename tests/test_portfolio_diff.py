"""G6 — portfolio change semantics: matching, vocabulary, conservation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondcart import parse_fondcart
from cnmv_iic.errors import NotFoundError
from cnmv_iic.query import (
    portfolio_diff,
    portfolio_history,
    position_history,
)
from cnmv_iic.storage import write_period
from tests.test_identity import _records


def _pos(clase, desc_if, isin, desc_val, divisa, vm) -> str:
    i = f"<CodigoISIN>{isin}</CodigoISIN>" if isin is not None else ""
    return (f"<InversionesFinancieras><ClaseIF>{clase}</ClaseIF>"
            f"<DescripcionIF>{desc_if}</DescripcionIF>{i}"
            f"<DescripcionValor>{desc_val}</DescripcionValor>"
            f"<Divisa>{divisa}</Divisa>"
            f"<ValorMercado>{vm}</ValorMercado>"
            f"</InversionesFinancieras>")


def _cart(period: str, positions: list[str], ncomp: str = "0") -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?><FondCart>'
            f"<FechaDatos>{period}</FechaDatos><Entidad><Tipo>FI</Tipo>"
            f"<NumeroRegistro>9</NumeroRegistro><Compartimento>"
            f"<NumeroCompartimento>{ncomp}</NumeroCompartimento>"
            f"{''.join(positions)}</Compartimento></Entidad></FondCart>"
            ).encode()


def _load(artifact, xml, root, period, artifact_id=None):
    snaps = parse_fondcart(
        xml, artifact=artifact, member_name=f"FONDCART_{period}.xml",
        member_sha256="m" * 64)
    write_period(root / "dataset", snaps, period=period,
                 artifact_id=artifact_id or f"art-{period}",
                 records=_records(artifact))


def _dataset(artifact, tmp_path, old_xml, new_xml,
             old="2025-06", new="2025-12"):
    _load(artifact, old_xml, tmp_path, old, "art-old")
    _load(artifact, new_xml, tmp_path, new, "art-new")
    return tmp_path / "dataset"


def _by_id(changes):
    return {c["identifier"]: c for c in changes if c["identifier"]}


def test_exact_match_classification(artifact, tmp_path):
    # totals stay 6000 on both sides so weight shifts are isolated
    old = _cart("202506", [
        _pos("INTERIOR", "Renta Variable Cotizada", "US0378331005",
             "ACCIONES|APPLE INC", "USD", "1000.00"),
        _pos("INTERIOR", "Renta Variable Cotizada", "ES0113900J37",
             "ACCIONES|INDITEX", "EUR", "2000.00"),
        _pos("INTERIOR", "Renta Variable Cotizada", "FR0000120271",
             "ACCIONES|TOTAL", "EUR", "3000.00"),
    ])
    new = _cart("202512", [
        _pos("INTERIOR", "Renta Variable Cotizada", "US0378331005",
             "ACCIONES|APPLE INC", "USD", "1100.00"),          # vm chg
        _pos("INTERIOR", "Renta Variable Cotizada", "ES0113900J37",
             "ACCIONES|INDITEX SA C", "EUR", "2000.00"),       # meta only
        _pos("INTERIOR", "Renta Variable Cotizada", "FR0000120271",
             "ACCIONES|TOTAL", "EUR", "2900.00"),              # vm chg
    ])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    r = rows[0]
    ch = _by_id(r["changes"])
    assert ch["US0378331005"]["change"] == (
        "market_value_and_weight_changed")
    assert ch["US0378331005"]["market_value"]["delta"] == (
        Decimal("100.00"))
    assert ch["US0378331005"]["weight"]["state"] == (
        "derived_from_derived")
    # descriptor drift on identical identity -> metadata, not economics
    assert ch["ES0113900J37"]["change"] == "source_metadata_changed"
    assert ch["ES0113900J37"]["metadata_changed"] == [
        "descripcion_valor"]
    assert ch["ES0113900J37"]["market_value"]["delta"] == Decimal(0)
    assert ch["FR0000120271"]["change"] == (
        "market_value_and_weight_changed")
    # both sides' provenance preserved (row-level artifact + locator)
    assert (ch["US0378331005"]["before"]["provenance"]
            ["source_artifact_id"] == artifact.source_id)
    assert (ch["US0378331005"]["after"]["provenance"]
            ["source_artifact_id"] == artifact.source_id)
    assert "InversionesFinancieras[1]" in (
        ch["US0378331005"]["before"]["provenance"]["xml_locator"])
    assert r["summary"]["conservation"]["old"]["holds"] is True
    assert r["summary"]["conservation"]["new"]["holds"] is True


def test_added_removed_and_authority(artifact, tmp_path):
    old = _cart("202506", [
        _pos("INTERIOR", "Renta Variable Cotizada", "US0378331005",
             "A", "USD", "1000.00"),
        _pos("EXTERIOR", "IIC", None, "FONDO|NOISIN", "EUR", "500.00"),
    ])
    new = _cart("202512", [
        _pos("INTERIOR", "Renta Variable Cotizada", "FR0000120271",
             "B", "EUR", "1500.00"),
        _pos("EXTERIOR", "IIC", "XXXXXXXXXXXX", "FONDO|MASKED",
             "EUR", "700.00"),
    ])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    ch = rows[0]["changes"]
    added = {c["identifier"]: c for c in ch
             if c["change"] == "added_position"}
    assert added["FR0000120271"]["identifier_authority"] == (
        "authoritative_identifier")
    # absent/masked rows also added/removed — but authority=none
    no_auth = [c for c in ch if c["identifier_authority"] == "none"]
    assert len(no_auth) == 2
    assert {c["change"] for c in no_auth} == {
        "added_position", "removed_position"}
    assert "BOUGHT" not in str(ch) and "SOLD" not in str(ch)


def test_ambiguous_isin_group_unresolved(artifact, tmp_path):
    # same valid ISIN twice in each snapshot (repo leg + bond) —
    # never paired, never summed
    dup = [
        _pos("INTERIOR", "Deuda Publica Cotizada Mas 1 Anio",
             "ES0000012098", "R.|ESTADO|4,75|2014-07-30", "EUR",
             "100.00"),
        _pos("INTERIOR", "Adquisicion Temporal Activos",
             "ES0000012098", "R.|ESTADO|4,75|2012-04-26", "EUR",
             "200.00"),
    ]
    old = _cart("202506", dup)
    new = _cart("202512", [
        dup[0], dup[1].replace("200.00", "250.00")])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    r = rows[0]
    assert len(r["unresolved"]) == 1
    u = r["unresolved"][0]
    assert u["match_state"] == "unresolved"
    assert u["match_basis"] == "ambiguous_identifier"
    assert u["identifier"] == "ES0000012098"
    assert u["rows_before"] == 2 and u["rows_after"] == 2
    # rows preserved unpaired — evidence, not a fabricated match
    assert len(u["before_rows"]) == 2
    cons = r["summary"]["conservation"]
    assert cons["old"]["unresolved_rows"] == 2
    assert cons["old"]["holds"] is True
    assert cons["new"]["holds"] is True


def test_dup_isin_absent_one_side_is_plain_added(artifact, tmp_path):
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00"),
        _pos("I", "R", "ES0000012098", "D1", "EUR", "10.00"),
        _pos("I", "R", "ES0000012098", "D2", "EUR", "20.00"),
    ])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    r = rows[0]
    added = [c for c in r["changes"]
             if c["change"] == "added_position"]
    assert len(added) == 2                    # whole group, no pairing
    assert r["unresolved"] == []
    assert r["summary"]["conservation"]["new"]["holds"] is True


def test_verbatim_signature_match_authority_none(artifact, tmp_path):
    sig = _pos("EXTERIOR", "IIC", None, "FONDO|X", "EUR", "500.00")
    old = _cart("202506", [sig])
    new = _cart("202512", [sig.replace("500.00", "550.00")])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    c = rows[0]["changes"][0]
    assert c["match_state"] == "exact_source_signature"
    assert c["identifier_authority"] == "none"
    assert c["identifier"] is None
    assert c["market_value"]["delta"] == Decimal("50.00")


def test_same_snapshot_zero_changes(artifact, tmp_path):
    xml = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "1000.00")])
    root = _dataset(artifact, tmp_path, xml, xml,
                    old="2025-12", new="2025-12")
    # same period twice needs two partitions — use two artifacts
    _, rows = portfolio_diff(root, "FI:9:0", "2025-12", "2025-12")
    c = rows[0]["changes"][0]
    assert c["change"] == "unchanged_position"
    assert c["market_value"]["delta"] == Decimal(0)


def test_symmetry_reversed_diff(artifact, tmp_path):
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00"),
        _pos("I", "R", "ES0113900J37", "B", "EUR", "200.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00"),
        _pos("I", "R", "FR0000120271", "C", "EUR", "200.00")])
    root = _dataset(artifact, tmp_path, old, new)
    _, fwd = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    _, rev = portfolio_diff(root, "FI:9:0", "2025-12", "2025-06")
    f, rv = fwd[0]["summary"]["counts"], rev[0]["summary"]["counts"]
    assert f["added_position"] == rv["removed_position"] == 1
    assert f["removed_position"] == rv["added_position"] == 1
    assert f["unchanged_position"] == rv["unchanged_position"] == 1


def test_deterministic_fingerprint(artifact, tmp_path):
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    root = _dataset(artifact, tmp_path, old, new)
    m1, _ = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    m2, _ = portfolio_diff(root, "FI:9:0", "2025-06", "2025-12")
    assert m1["diff_fingerprint"] == m2["diff_fingerprint"]
    assert len(m1["diff_fingerprint"]) == 64


def test_previous_selects_owner_snapshot(artifact, tmp_path):
    mid = _cart("202509", [
        _pos("I", "R", "US0378331005", "A", "USD", "105.00")])
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    _load(artifact, old, tmp_path, "2025-06")
    _load(artifact, mid, tmp_path, "2025-09")
    _load(artifact, new, tmp_path, "2025-12")
    meta, rows = portfolio_diff(
        tmp_path / "dataset", "FI:9:0", None, "2025-12",
        previous=True)
    r = rows[0]
    assert r["from_period"] == "2025-09"       # latest available, not
    assert r["to_period"] == "2025-12"         #   a quarter
    assert r["publication_cadence"] == "adjacent_available_snapshots"
    assert r["elapsed_days"] == 92             # Sep30 -> Dec31
    assert meta["publication_cadence"] == (
        "adjacent_available_snapshots")


def test_non_fondcart_period_fails_closed(artifact, tmp_path):
    xml = _cart("202512", [_pos("I", "R", "US0378331005", "A", "USD",
                                "100.00")])
    root = _dataset(artifact, tmp_path, xml, xml,
                    old="2025-12", new="2025-12")
    with pytest.raises(NotFoundError, match="not a published snapshot"):
        portfolio_diff(root, "FI:9:0", "2025-03", "2025-12")
    with pytest.raises(NotFoundError, match="not a published snapshot"):
        portfolio_diff(root, "FI:9:0", "2025-12", "2025-03")


def test_owner_absent_from_snapshot(artifact, tmp_path):
    # owner has no rows in the earlier published snapshot — honest
    # all-added, not an error
    only_new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    other = _cart("202506", [
        _pos("I", "R", "FR0000120271", "X", "EUR", "50.00")])
    _load(artifact, other.replace(b"9</NumeroRegistro>",
                                  b"77</NumeroRegistro>"),
          tmp_path, "2025-06")
    _load(artifact, only_new, tmp_path, "2025-12")
    _, rows = portfolio_diff(
        tmp_path / "dataset", "FI:9:0", "2025-06", "2025-12")
    r = rows[0]
    assert r["snapshot_presence"]["from"] == "owner_absent"
    assert r["positions"] == {"old": 0, "new": 1}
    assert r["changes"][0]["change"] == "added_position"
    assert r["summary"]["conservation"]["new"]["holds"] is True


def test_isin_resolves_owner(artifact, tmp_path):
    old = _cart("202506", [_pos("I", "R", "US0378331005", "A", "USD",
                                "100.00")])
    new = _cart("202512", [_pos("I", "R", "US0378331005", "A", "USD",
                                "110.00")])
    root = _dataset(artifact, tmp_path, old, new)
    meta, rows = portfolio_diff(
        root, "ES0138841038", "2025-06", "2025-12")
    assert meta["resolved_as"] == "exact_share_class"
    assert [r["portfolio_owner"] for r in rows] == ["FI:9:0"]


def test_derivatives_section_declares_unavailable(artifact, tmp_path):
    xml = _cart("202512", [_pos("I", "R", "US0378331005", "A", "USD",
                                "100.00")])
    root = _dataset(artifact, tmp_path, xml, xml,
                    old="2025-12", new="2025-12")
    _, rows = portfolio_diff(root, "FI:9:0", "2025-12", "2025-12")
    d = rows[0]["derivatives"]
    assert d["individual_position_diff"] == "unavailable"
    assert "no_authoritative_cross_snapshot_identity" in d["reason"]


def test_position_history_reported_values(artifact, tmp_path):
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00"),
        _pos("I", "R", "US0378331005", "A-dup", "USD", "200.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = position_history(root, "FI:9:0", "US0378331005")
    obs = rows[0]["observations"]
    assert [o["period"] for o in obs] == [
        "2025-06", "2025-06", "2025-12"]
    # duplicated identifier kept as rows, flagged — never collapsed
    assert obs[0]["note"].startswith("duplicated identifier")
    assert obs[2]["note"] is None
    assert obs[0]["weight_state"] == "derived"


def test_portfolio_history_counts(artifact, tmp_path):
    old = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00"),
        _pos("E", "Depositos", None, "DEP|X", "EUR", "50.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "150.00")])
    root = _dataset(artifact, tmp_path, old, new)
    _, rows = portfolio_history(root, "FI:9:0")
    snaps = {s["period"]: s for s in rows[0]["snapshots"]}
    assert snaps["2025-06"]["n_positions"] == 2
    assert snaps["2025-06"]["cash"] == 1
    assert snaps["2025-06"]["securities"] == 1
    assert snaps["2025-06"]["total_reported_value"] == (
        Decimal("150.00"))
    assert snaps["2025-12"]["n_positions"] == 1
    # stored artifact id is the row-level provenance artifact
    assert snaps["2025-12"]["source_artifact_id"] == (
        artifact.source_id)


def test_previous_fails_when_published_snapshot_missing(artifact,
                                                        tmp_path):
    # measured cadence: post-2023 FONDCART publishes June+December.
    # to=2025-12 -> expected previous 2025-06; not loaded -> fail
    # naming it, never silently jumping backward.
    mar = _cart("202503", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    _load(artifact, mar, tmp_path, "2025-03")
    _load(artifact, new, tmp_path, "2025-12")
    with pytest.raises(
            NotFoundError,
            match="previous_published_snapshot_not_loaded=2025-06"):
        portfolio_diff(tmp_path / "dataset", "FI:9:0", None,
                       "2025-12", previous=True)


def test_previous_uses_expected_when_loaded(artifact, tmp_path):
    jun = _cart("202506", [
        _pos("I", "R", "US0378331005", "A", "USD", "105.00")])
    new = _cart("202512", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    _load(artifact, jun, tmp_path, "2025-06")
    _load(artifact, new, tmp_path, "2025-12")
    _, rows = portfolio_diff(tmp_path / "dataset", "FI:9:0", None,
                             "2025-12", previous=True)
    assert rows[0]["from_period"] == "2025-06"   # published previous


def test_previous_pre2023_dataset_local(artifact, tmp_path):
    # outside the measured window no missing snapshot is claimed —
    # dataset-local previous is the honest resolution
    old = _cart("201803", [
        _pos("I", "R", "US0378331005", "A", "USD", "100.00")])
    new = _cart("202003", [
        _pos("I", "R", "US0378331005", "A", "USD", "110.00")])
    _load(artifact, old, tmp_path, "2018-03")
    _load(artifact, new, tmp_path, "2020-03")
    _, rows = portfolio_diff(tmp_path / "dataset", "FI:9:0", None,
                             "2020-03", previous=True)
    assert rows[0]["from_period"] == "2018-03"
