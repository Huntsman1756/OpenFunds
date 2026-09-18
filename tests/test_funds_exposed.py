"""G8-1 — funds-exposed-to: issuer LEI -> ISINs -> position rows ->
reporting portfolio owners. known_lower_bound semantics: conflicts
never enter totals, issuer completeness is always null.
"""

from __future__ import annotations

import pytest

from cnmv_iic.adapters.fondregistro import parse_fondregistro
from cnmv_iic.adjudication import adjudicate
from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.domain import IsinState, classify_isin
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.query import funds_exposed_to
from cnmv_iic.storage import write_period
from tests.conftest import FONDREGISTRO_XML
from tests.test_hardening import FIRDS_P, GLEIF_P, _provider
from tests.test_portfolio_diff import _pos
from tests.test_resolution_gleif import ISIN_A, ISIN_B, ISIN_C, LEI_A, LEI_B

_SNAP_G, _SNAP_F = "2026-09-18", "2026-09-12"
LEI_OTHER = "213800FIRDSONLY00000"           # 20-char, != LEI_A
LEI_EMPTY = "213800NOHOLDINGS0000"           # valid format, no positions


def _mk_isin(n: int) -> str:
    """Deterministic valid ISIN via the project's own validator."""
    base = f"XS{n:09d}"
    for d in range(10):
        cand = base + str(d)
        if classify_isin(cand) is IsinState.VALID:
            return cand
    raise AssertionError(f"no check digit for {base}")


ISIN_D = _mk_isin(42)
ISIN_E = _mk_isin(43)


def _cart2(period: str, e1: list[str], e2: list[str]) -> bytes:
    """Two entities -> two portfolio owners FI:9:0 and FI:10:0."""
    return (
        f'<?xml version="1.0" encoding="utf-8"?><FondCart>'
        f"<FechaDatos>{period.replace('-', '')}</FechaDatos>"
        f"<Entidad><Tipo>FI</Tipo><NumeroRegistro>9</NumeroRegistro>"
        f"<Compartimento><NumeroCompartimento>0</NumeroCompartimento>"
        f"{''.join(e1)}</Compartimento></Entidad>"
        f"<Entidad><Tipo>FI</Tipo><NumeroRegistro>10</NumeroRegistro>"
        f"<Compartimento><NumeroCompartimento>0</NumeroCompartimento>"
        f"{''.join(e2)}</Compartimento></Entidad></FondCart>"
    ).encode()


def _setup(artifact, tmp_path, rows_e1, rows_e2,
           gleif_out: dict, firds_out: dict | None = None,
           period: str = "2025-12"):
    """Positions (2 owners) + FONDREGISTRO identity + providers +
    adjudication."""
    from cnmv_iic.adapters.fondcart import parse_fondcart

    snaps = parse_fondcart(
        _cart2(period, rows_e1, rows_e2), artifact=artifact,
        member_name=f"FONDCART_{period.replace('-', '')}.xml",
        member_sha256="m" * 64)
    records = parse_fondregistro(
        FONDREGISTRO_XML, artifact=artifact,
        member_name="FONDREGISTRO_202512.xml", member_sha256="r" * 64)
    write_period(tmp_path / "dataset", snaps, period=period,
                 artifact_id=f"art-{period}", records=records)
    _provider(tmp_path, GLEIF_P, _SNAP_G, gleif_out)
    if firds_out is not None:
        _provider(tmp_path, FIRDS_P, _SNAP_F, firds_out)
    store = ArtifactStore(tmp_path / "artifacts")
    adjudicate(tmp_path / "dataset", store)
    return tmp_path / "dataset"


M = ("matched",)
NM = ("no_match", [])


def _m(lei: str):
    return ("matched", [lei])


def _multi(*leis: str):
    return ("multiple_candidates", list(leis))


def test_issuer_fully_corroborated(artifact, tmp_path):
    """Golden 1: every attributed row corroborated — single_source=0."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100")],
                [_pos("I", "Renta Variable", ISIN_B, "A|B", "EUR", "40")],
                {ISIN_A: _m(LEI_A), ISIN_B: _m(LEI_B), ISIN_C: NM},
                {ISIN_A: _m(LEI_A), ISIN_B: _m(LEI_B)})
    out = funds_exposed_to(ds, LEI_A, "2025-12")
    t = out["totals"]
    assert str(t["known_resolved_value"]) == "100.00"
    assert str(t["corroborated_value"]) == "100.00"
    assert str(t["single_source_value"]) == "0"
    assert t["portfolio_owners"] == 1
    o = out["owners"][0]
    assert o["owner_key"] == "FI:9:0"
    assert o["fund_name"] == "FONMARCH, FI"          # period identity
    assert o["compartment_name"] == "COMPARTIMENTO PRINCIPAL"
    assert o["position_rows"] == 1 and o["unique_isins"] == 1
    # coverage disclosure — honest lower bound, never a ratio
    c = out["coverage"]
    assert c["issuer_specific_completeness"] is None
    assert c["issuer_exposure_semantics"] == "known_lower_bound"
    assert c["scope"] == "period_security_universe"
    assert c["resolution_ratio"] is not None
    assert out["fingerprint"]


def test_issuer_mixed_evidence(artifact, tmp_path):
    """Golden 2: corroborated + gleif_only + firds_only -> LEI_A.
    Decomposition is exact; --evidence filters never mix silently."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_B, "A|B", "EUR", "50"),
                 _pos("I", "Renta Variable", ISIN_C, "A|C", "EUR", "30")],
                [_pos("I", "Renta Variable", ISIN_D, "A|D", "EUR", "20")],
                {ISIN_A: _m(LEI_A), ISIN_B: _m(LEI_A),
                 ISIN_C: NM, ISIN_D: _m(LEI_B)},
                {ISIN_A: _m(LEI_A), ISIN_C: _m(LEI_A), ISIN_D: _m(LEI_B)})
    out = funds_exposed_to(ds, LEI_A, "2025-12")
    t = out["totals"]
    assert str(t["known_resolved_value"]) == "180.00"
    assert str(t["corroborated_value"]) == "100.00"
    assert str(t["gleif_only_value"]) == "50.00"
    assert str(t["firds_only_value"]) == "30.00"
    assert str(t["single_source_value"]) == "80.00"
    # evidence filters
    only_c = funds_exposed_to(ds, LEI_A, "2025-12",
                              evidence="corroborated")
    assert str(only_c["totals"]["known_resolved_value"]) == "100.00"
    only_s = funds_exposed_to(ds, LEI_A, "2025-12",
                              evidence="single-source")
    assert str(only_s["totals"]["known_resolved_value"]) == "80.00"
    assert str(only_s["totals"]["gleif_only_value"]) == "50.00"
    assert str(only_s["totals"]["firds_only_value"]) == "30.00"


def test_issuer_in_conflict(artifact, tmp_path):
    """Golden 3: conflict naming LEI_A as a candidate is EXCLUDED from
    totals but reported separately — visible, never adjudicated."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_C, "A|C", "EUR", "30")],
                [_pos("I", "Renta Variable", ISIN_B, "A|B", "EUR", "40")],
                {ISIN_A: _m(LEI_A), ISIN_C: _m(LEI_A), ISIN_B: _m(LEI_B)},
                {ISIN_A: _m(LEI_A), ISIN_C: _m(LEI_OTHER),
                 ISIN_B: _m(LEI_B)})
    out = funds_exposed_to(ds, LEI_A, "2025-12")
    t = out["totals"]
    assert str(t["known_resolved_value"]) == "100.00"   # C excluded
    assert str(t["conflict_candidate_value_excluded"]) == "30.00"
    assert t["conflict_candidate_rows_excluded"] == 1
    # the other candidate sees the same excluded row
    out2 = funds_exposed_to(ds, LEI_OTHER, "2025-12")
    assert str(out2["totals"]["conflict_candidate_value_excluded"]) \
        == "30.00"
    assert str(out2["totals"]["known_resolved_value"]) == "0"


def test_valid_lei_without_holdings(artifact, tmp_path):
    """Golden 4: well-formed LEI with no attributed positions -> honest
    empty result, not an error."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100")],
                [], {ISIN_A: _m(LEI_A)})
    out = funds_exposed_to(ds, LEI_EMPTY, "2025-12")
    assert out["owners"] == []
    assert str(out["totals"]["known_resolved_value"]) == "0"
    assert "note" in out
    assert out["coverage"]["issuer_specific_completeness"] is None


def test_malformed_lei_fails_closed(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "1")],
                [], {ISIN_A: _m(LEI_A)})
    with pytest.raises(NotFoundError, match="well-formed LEI"):
        funds_exposed_to(ds, "NOT-A-LEI", "2025-12")
    with pytest.raises(NotFoundError):
        funds_exposed_to(ds, "SHORT", "2025-12")


def test_invalid_evidence_fails_closed(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "1")],
                [], {ISIN_A: _m(LEI_A)})
    with pytest.raises(ParseError, match="evidence"):
        funds_exposed_to(ds, LEI_A, "2025-12", evidence="bogus")


def test_period_not_loaded_fails(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "1")],
                [], {ISIN_A: _m(LEI_A)})
    with pytest.raises(NotFoundError, match="not loaded"):
        funds_exposed_to(ds, LEI_A, "1999-01")


def test_duplicate_isin_rows_aggregate_at_row_grain(artifact, tmp_path):
    """Two structural rows with the same ISIN both contribute — never
    collapsed to unique-ISIN grain."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A1", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_A, "A|A2", "EUR", "40")],
                [], {ISIN_A: _m(LEI_A)})
    out = funds_exposed_to(ds, LEI_A, "2025-12")
    o = out["owners"][0]
    assert o["position_rows"] == 2
    assert o["unique_isins"] == 1
    assert str(o["absolute_value"]) == "140.00"


def test_multiple_candidates_excluded(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_C, "A|C", "EUR", "30")],
                [], {ISIN_A: _m(LEI_A), ISIN_C: _multi(LEI_A, LEI_B)})
    out = funds_exposed_to(ds, LEI_A, "2025-12")
    assert str(out["totals"]["known_resolved_value"]) == "100.00"
    assert out["totals"]["conflict_candidate_rows_excluded"] == 1


def test_deterministic_fingerprint(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100")],
                [], {ISIN_A: _m(LEI_A)})
    a = funds_exposed_to(ds, LEI_A, "2025-12")
    b = funds_exposed_to(ds, LEI_A, "2025-12")
    assert a["fingerprint"] == b["fingerprint"]


def test_positions_detail(artifact, tmp_path):
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_B, "A|B", "EUR", "50")],
                [], {ISIN_A: _m(LEI_A), ISIN_B: _m(LEI_A)})
    out = funds_exposed_to(ds, LEI_A, "2025-12", include_positions=True)
    assert len(out["positions"]) == 2
    p = out["positions"][0]
    assert p["resolution_state"] == "gleif_only"
    assert p["evidence_strength"] == "single_source"
    assert p["resolved_lei"] == LEI_A
    assert p["xml_locator"]


def test_signed_vs_absolute(artifact, tmp_path):
    """A negative position contributes signed and absolute totals —
    cancellation can never hide gross exposure."""
    ds = _setup(artifact, tmp_path,
                [_pos("I", "Renta Variable", ISIN_A, "A|A", "EUR", "100"),
                 _pos("I", "Renta Variable", ISIN_B, "A|B", "EUR", "-20")],
                [], {ISIN_A: _m(LEI_A), ISIN_B: _m(LEI_A)})
    t = funds_exposed_to(ds, LEI_A, "2025-12")["totals"]
    assert str(t["signed_market_value"]) == "80.00"
    assert str(t["absolute_market_value"]) == "120.00"
    assert str(t["known_resolved_value"]) == "120.00"
