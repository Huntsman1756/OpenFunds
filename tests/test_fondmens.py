"""G3 — FONDMENS adapter, observation states, storage, query layer."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cnmv_iic.adapters.fondmens import parse_fondmens
from cnmv_iic.domain import (
    FundIdentity,
    IsinState,
    ObservationState,
    RegistryJoinState,
)
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.query import (
    class_observation_summary,
    daily_series,
)
from cnmv_iic.storage import write_period
from tests.test_identity import _records, _snap

_REG_KEYS = frozenset({"FI:9:0:1", "FI:9:0:2", "FI:9:1:1"})


def _block(name: str, prefix: str, values: dict[int, str] | None) -> str:
    if values is None:
        return ""
    cells = "".join(
        f"<{prefix}{d}>{v}</{prefix}{d}>" for d, v in values.items())
    return f"<{name}>{cells}</{name}>"


def _clase(nclase: str, isin: str | None,
           vl: dict[int, str] | None,
           pat: dict[int, str] | None,
           par: dict[int, str] | None) -> str:
    isin_el = f"<ISIN>{isin}</ISIN>" if isin else ""
    return (
        f"<Clase><NumeroClase>{nclase}</NumeroClase>{isin_el}"
        f"{_block('VLDiario', 'VL_Dia', vl)}"
        f"{_block('PatrimonioDiario', 'Patrimonio_Dia', pat)}"
        f"{_block('ParticipesDiario', 'Participes_Dia', par)}"
        f"</Clase>"
    )


def _mens(period: str, comps: list[tuple[str, str, list[str]]]) -> bytes:
    """comps: (numero_registro, numero_compartimento, [clase xml])."""
    body = "".join(
        f"<Entidad><Tipo>FI</Tipo><NumeroRegistro>{nr}</NumeroRegistro>"
        f"<Compartimento><NumeroCompartimento>{nc}</NumeroCompartimento>"
        f"{''.join(clases)}</Compartimento></Entidad>"
        for nr, nc, clases in comps
    )
    return (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f"<FondMens><FechaDatos>{period}</FechaDatos>{body}</FondMens>"
    ).encode()


def _fill(n: int, v: str) -> dict[int, str]:
    return {d: v for d in range(1, n + 1)}


# FI:9:0:1 — fully observed class (matches FONDREGISTRO fixture)
# FI:9:0:2 — leading zero sentinels, per-metric independence on day 1
# FI:9:1:1 — all-zero class
# FI:77:0:0 — clase 0 (fund-level grain), absent from the registry
MENS_DEC = _mens("202512", [
    ("9", "0", [
        _clase("1", "ES0138841038",
               _fill(31, "10.5000"), _fill(31, "1000.00"), _fill(31, "7")),
        _clase("2", "ES0138841004",
               {**_fill(31, "0"), 3: "20.0000", 4: "20.5000"},
               _fill(31, "500.00"),
               {**_fill(31, "9"), 1: "0"}),
    ]),
    ("9", "1", [
        _clase("1", "ES0138841012",
               _fill(31, "0"), _fill(31, "0"), _fill(31, "0")),
    ]),
    ("77", "0", [
        _clase("0", "ES0100000005",
               _fill(31, "5.0000"), _fill(31, "250.00"), _fill(31, "3")),
    ]),
])

MENS_APR = _mens("202504", [
    ("9", "0", [
        _clase("1", "ES0138841038",
               {**_fill(30, "10.5000"), 31: "0"},
               {**_fill(30, "1000.00"), 31: "0"},
               {**_fill(30, "7"), 31: "0"}),
    ]),
])


def _parse(artifact, xml=MENS_DEC, registry_keys=_REG_KEYS):
    return parse_fondmens(
        xml, artifact=artifact, member_name="FONDMENS_202512.xml",
        member_sha256="m" * 64, registry_keys=registry_keys)


def _by_key(rows, key):
    return sorted(
        (r for r in rows if r.share_class_key == key),
        key=lambda r: r.day_index)


# ---------------------------------------------------------------------------
# adapter — calendar, states, keys
# ---------------------------------------------------------------------------


def test_parse_observed_class(artifact):
    rows = _by_key(_parse(artifact), "FI:9:0:1")
    assert len(rows) == 31
    assert rows[0].observation_date == "2025-12-01"
    assert rows[-1].observation_date == "2025-12-31"
    r = rows[14]
    assert r.day_index == 15
    assert r.nav.value == Decimal("10.5000")
    assert r.nav.raw == "10.5000"
    assert r.nav.state is ObservationState.OBSERVED
    assert r.aum.value == Decimal("1000.00")
    assert r.investors.value == 7
    assert r.registry_state is RegistryJoinState.RESOLVED
    assert r.period == "2025-12"
    assert r.fund_key == "FI:9"
    assert r.compartment_key == "FI:9:0"
    assert r.isin_state is IsinState.VALID
    assert r.provenance.xml_locator.endswith("Clase[1]")


def test_impossible_days_rejected(artifact):
    rows = _parse(artifact, MENS_APR)
    assert len(rows) == 30                       # never 31
    assert max(r.day_index for r in rows) == 30
    assert rows[-1].observation_date == "2025-04-30"
    # the '0' serialized at Dia31 is padding, not an observation
    assert all(r.observation_date != "2025-04-31" for r in rows)


def test_all_zero_class_is_sentinel(artifact):
    rows = _by_key(_parse(artifact), "FI:9:1:1")
    assert len(rows) == 31
    for r in rows:
        for m in (r.nav, r.aum, r.investors):
            assert m.state is ObservationState.SOURCE_ZERO_SENTINEL
            assert m.value is None               # no fabricated observation
            assert m.raw == "0"                  # verbatim preserved


def test_leading_zeros_then_observed(artifact):
    rows = _by_key(_parse(artifact), "FI:9:0:2")
    assert rows[0].nav.state is ObservationState.SOURCE_ZERO_SENTINEL
    assert rows[1].nav.state is ObservationState.SOURCE_ZERO_SENTINEL
    assert rows[2].nav.state is ObservationState.OBSERVED
    assert rows[2].nav.value == Decimal("20.0000")
    # per-metric independence: day 1 nav is sentinel while investors observed
    assert rows[0].investors.state is ObservationState.SOURCE_ZERO_SENTINEL
    assert rows[1].investors.value == 9
    assert rows[1].investors.state is ObservationState.OBSERVED


def test_missing_block(artifact):
    xml = _mens("202512", [("9", "0", [
        _clase("1", "ES0138841038", None, _fill(31, "100.00"), _fill(31, "2")),
    ])])
    rows = _parse(artifact, xml)
    assert all(r.nav.state is ObservationState.MISSING for r in rows)
    assert all(r.nav.value is None and r.nav.raw is None for r in rows)
    assert all(r.aum.state is ObservationState.OBSERVED for r in rows)


def test_invalid_numeric_preserved(artifact):
    xml = _mens("202512", [("9", "0", [
        _clase("1", "ES0138841038",
               {**_fill(31, "10.5000"), 5: "abc"},
               _fill(31, "100.00"), _fill(31, "2")),
    ])])
    rows = _parse(artifact, xml)
    bad = rows[4]
    assert bad.nav.state is ObservationState.INVALID
    assert bad.nav.raw == "abc"                  # verbatim, never dropped
    assert bad.nav.value is None


def test_negative_patrimonio_is_observed(artifact):
    xml = _mens("202512", [("9", "0", [
        _clase("1", "ES0138841038",
               _fill(31, "10.5000"),
               {**_fill(31, "100.00"), 10: "-1.50"},
               _fill(31, "2")),
    ])])
    rows = _parse(artifact, xml)
    assert rows[9].aum.state is ObservationState.OBSERVED
    assert rows[9].aum.value == Decimal("-1.50")


def test_duplicate_class_fails_closed(artifact):
    xml = _mens("202512", [("9", "0", [
        _clase("1", "ES0138841038", _fill(31, "1"), _fill(31, "1"), _fill(31, "1")),
        _clase("1", "ES0138841038", _fill(31, "2"), _fill(31, "2"), _fill(31, "2")),
    ])])
    with pytest.raises(ParseError, match="duplicate class key"):
        _parse(artifact, xml)


def test_unresolved_registry_reference(artifact):
    rows = _by_key(_parse(artifact), "FI:77:0:0")
    assert all(r.registry_state is RegistryJoinState.UNRESOLVED for r in rows)


def test_no_registry_means_unresolved(artifact):
    rows = _parse(artifact, registry_keys=None)
    assert all(r.registry_state is RegistryJoinState.UNRESOLVED
               for r in rows)


def test_clase_zero_is_first_class_key(artifact):
    rows = _by_key(_parse(artifact), "FI:77:0:0")
    assert len(rows) == 31
    assert rows[0].numero_clase == "0"           # fund-level grain, not absent


def test_isin_absent_preserved(artifact):
    xml = _mens("202512", [("9", "0", [
        _clase("1", None, _fill(31, "1"), _fill(31, "1"), _fill(31, "1")),
    ])])
    rows = _parse(artifact, xml)
    assert rows[0].isin_state is IsinState.ABSENT
    assert rows[0].isin_raw is None


# ---------------------------------------------------------------------------
# storage + query layer
# ---------------------------------------------------------------------------


@pytest.fixture()
def dataset(tmp_path, artifact):
    root = tmp_path / "dataset"
    recs = _records(artifact)
    snaps = [_snap(FundIdentity("FI", "9", "0")),
             _snap(FundIdentity("FI", "9", "1"))]
    daily = _parse(artifact)
    return write_period(
        root, snaps, period="2025-12", artifact_id="aid",
        records=recs, daily=daily), root


def test_daily_export(dataset):
    manifest, _ = dataset
    assert manifest["daily_observations"] == 31 * 4
    assert manifest["fondmens_present"] is True
    assert manifest["daily_fingerprint"]
    # G1/G2 fingerprints untouched by the new table
    assert manifest["dataset_fingerprint"]
    assert manifest["registry_fingerprint"]


def test_daily_fingerprint_deterministic(tmp_path, artifact):
    daily = _parse(artifact)
    m1 = write_period(tmp_path / "d1", [], period="2025-12",
                      artifact_id="a", daily=daily)
    m2 = write_period(tmp_path / "d2", [], period="2025-12",
                      artifact_id="a", daily=daily)
    assert m1["daily_fingerprint"] == m2["daily_fingerprint"]


def test_daily_series_by_isin(dataset):
    _, root = dataset
    meta, rows = daily_series(root, "ES0138841038", "nav", None, None)
    assert meta["share_class_key"] == "FI:9:0:1"
    assert meta["observations"] == 31
    assert meta["observed"] == 31
    assert rows[0]["observation_date"].isoformat() == "2025-12-01"
    assert rows[0]["value"] == Decimal("10.5000")
    assert rows[0]["state"] == "observed"


def test_daily_series_states_and_range(dataset):
    _, root = dataset
    meta, rows = daily_series(
        root, "FI:9:0:2", "nav", "2025-12-01", "2025-12-04")
    assert len(rows) == 4
    assert rows[0]["state"] == "source_zero_sentinel"
    assert rows[0]["value"] is None
    assert rows[0]["raw"] == "0"
    assert rows[2]["value"] == Decimal("20.0000")


def test_daily_series_all_metrics(dataset):
    _, root = dataset
    _, aum = daily_series(root, "FI:9:0:1", "aum", None, None)
    _, inv = daily_series(root, "FI:9:0:1", "investors", None, None)
    assert aum[0]["value"] == Decimal("1000.00")
    assert inv[0]["value"] == 7


def test_daily_series_fund_identifier_fails(dataset):
    _, root = dataset
    # grain contract: a fund/compartment can never be a class-level series
    with pytest.raises(NotFoundError):
        daily_series(root, "FI:9", "nav", None, None)
    with pytest.raises(NotFoundError):
        daily_series(root, "FI:9:0", "nav", None, None)


def test_daily_series_invalid_identifier_fails(dataset):
    _, root = dataset
    with pytest.raises(NotFoundError):
        daily_series(root, "ES0138841039", "nav", None, None)


def test_class_observation_summary(dataset):
    _, root = dataset
    info, summary = class_observation_summary(root, "ES0138841038", None)
    assert info["share_class_key"] == "FI:9:0:1"
    assert summary["rows"] == 31
    assert summary["nav_observed"] == 31
    assert summary["nav_sentinel"] == 0
    assert summary["first_observed"].isoformat() == "2025-12-01"
    assert summary["observed_periods"] == ["2025-12"]
    info2, s2 = class_observation_summary(root, "FI:9:1:1", None)
    assert s2["nav_observed"] == 0
    assert s2["nav_sentinel"] == 31
