"""G9-A2 — backfill_periods orchestration: resume semantics, per-period
failure isolation, no-network paths for stored artifacts."""

from __future__ import annotations

from cnmv_iic.acquisition.client import DownloadedPayload
from cnmv_iic.errors import AcquisitionError
from cnmv_iic.ingest import _month_range, backfill_periods, update_period
from tests.conftest import FONDREGISTRO_XML, make_zip
from tests.test_portfolio_diff import _cart, _pos


def _period_zip(yyyymm: str) -> bytes:
    reg = FONDREGISTRO_XML.replace(b"202512", yyyymm.encode())
    cart = _cart(yyyymm, [
        _pos("I", "Renta Variable", "US0378331005", "A|A", "EUR", "1.00")])
    return make_zip({
        f"FONDCART_{yyyymm}.xml": cart,
        f"FONDREGISTRO_{yyyymm}.xml": reg,
    })


class _StubClient:
    """Duck-typed stand-in for CnmvClient (index + zip by period)."""

    def __init__(self, periods: list[str], fail: set[str] | None = None):
        self.periods = periods
        self.fail = fail or set()
        self.request_delay = 0.0
        self.index_calls: list[int] = []
        self.downloads: list[str] = []

    def list_months(self, year: int) -> dict[int, str]:
        self.index_calls.append(year)
        return {
            int(p[5:]): (f"https://www.cnmv.es/webservices/"
                         f"verdocumento/ver?e={p}")
            for p in self.periods if p.startswith(str(year))
        }

    def download_zip(self, url: str) -> DownloadedPayload:
        period = url.rsplit("=", 1)[-1]
        self.downloads.append(period)
        if period in self.fail:
            raise AcquisitionError(f"boom {period}")
        return DownloadedPayload(
            url=url, content_type="application/zip",
            data=_period_zip(period.replace("-", "")))


def test_month_range():
    assert _month_range("2025-11", "2026-02") == [
        "2025-11", "2025-12", "2026-01", "2026-02"]
    assert _month_range("2025-01", "2025-01") == ["2025-01"]


def test_backfill_downloads_only_missing(store, tmp_path):
    ds = tmp_path / "dataset"
    stub = _StubClient(["2025-01", "2025-02", "2025-03"])
    out = backfill_periods(store, ds, "2025-01", "2025-03", client=stub)
    assert [r["status"] for r in out["periods"]] == ["downloaded"] * 3
    assert stub.downloads == ["2025-01", "2025-02", "2025-03"]
    assert all(
        r["registry_fingerprint"] for r in out["periods"])
    # resume: everything already_complete, zero network
    stub2 = _StubClient(["2025-01", "2025-02", "2025-03"])
    out2 = backfill_periods(store, ds, "2025-01", "2025-03", client=stub2)
    assert [r["status"] for r in out2["periods"]] == [
        "already_complete"] * 3
    assert stub2.downloads == [] and stub2.index_calls == []


def test_backfill_failure_isolated(store, tmp_path):
    ds = tmp_path / "dataset"
    stub = _StubClient(["2025-01", "2025-02", "2025-03"],
                       fail={"2025-02"})
    out = backfill_periods(store, ds, "2025-01", "2025-03", client=stub)
    statuses = {r["period"]: r["status"] for r in out["periods"]}
    assert statuses == {"2025-01": "downloaded", "2025-02": "failed",
                        "2025-03": "downloaded"}
    assert out["failed"][0]["period"] == "2025-02"
    assert "boom" in out["failed"][0]["error"]
    # resume retries ONLY the failed period
    stub2 = _StubClient(["2025-01", "2025-02", "2025-03"])
    out2 = backfill_periods(store, ds, "2025-01", "2025-03", client=stub2)
    assert stub2.downloads == ["2025-02"]
    assert [r["status"] for r in out2["periods"]] == [
        "already_complete", "downloaded", "already_complete"]


def test_backfill_exported_from_local(store, tmp_path):
    """Artifact stored but manifest absent -> export with NO download."""
    ds = tmp_path / "dataset"
    stub = _StubClient(["2025-01"])
    update_period(store, ds, "2025-01", client=stub)
    (ds / "manifests" / "2025-01.json").unlink()  # lost manifest
    stub2 = _StubClient(["2025-01"])
    out = backfill_periods(store, ds, "2025-01", "2025-01", client=stub2)
    assert out["periods"][0]["status"] == "exported_from_local"
    assert stub2.downloads == []          # zero network
    assert out["periods"][0]["registry_fingerprint"]


def test_backfill_index_cached_per_year(store, tmp_path):
    ds = tmp_path / "dataset"
    periods = [f"2025-{m:02d}" for m in (1, 2, 3)] + ["2026-01"]
    stub = _StubClient(periods)
    backfill_periods(store, ds, periods[0], periods[-1], client=stub)
    assert stub.index_calls == [2025, 2026]   # once per year, not per month
