"""G9-B — acquisition hardening, offline rebuild, holdout visibility."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from cnmv_iic.acquisition.hr import (
    HrPage,
    HrSearchResult,
)
from cnmv_iic.acquisition.weekly import (
    DownloadedPayload,
    WeekOption,
    WeekSelection,
)
from cnmv_iic.artifacts.store import ArtifactStore
from cnmv_iic.lifecycle_ingest import (
    acquire_hr,
    acquire_weeks,
    candidate_links,
    disappearance_candidates,
    fondregistro_markers,
    hr_ledger,
    weekly_ledger,
)
from cnmv_iic.lifecycle_storage import write_lifecycle
from cnmv_iic.storage import FUNDS_SCHEMA

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------

class FakeWeeklyClient:
    request_delay = 0.0

    def __init__(self) -> None:
        self.select_calls: list[str] = []
        self.fetch_calls: list[str] = []

    def week_options(self) -> list[WeekOption]:
        return [
            WeekOption(week_id="100", start=date(2012, 1, 31),
                       end=date(2012, 2, 6), label="31/01/2012 al 06/02/2012"),
            WeekOption(week_id="101", start=date(2012, 2, 7),
                       end=date(2012, 2, 13), label="07/02/2012 al 13/02/2012"),
            WeekOption(week_id="102", start=date(2012, 2, 14),
                       end=date(2012, 2, 20), label="14/02/2012 al 20/02/2012"),
        ]

    def select_week(self, week_id: str) -> WeekSelection:
        self.select_calls.append(week_id)
        if week_id == "100":
            return WeekSelection(
                week_id=week_id, selected_label="w100",
                links={"registro": "https://www.cnmv.es/verdocumento/ver?e=A"},
                raw_html="<html>sel100</html>")
        if week_id == "101":
            return WeekSelection(
                week_id=week_id, selected_label="w101",
                links={
                    "boletin_completo":
                        "https://www.cnmv.es/verdocumento/ver?e=B"},
                raw_html="<html>sel101</html>")
        return WeekSelection(
            week_id=week_id, selected_label="w102", links={},
            raw_html="<html>sel102 no docs</html>")

    def fetch_document(self, url: str) -> DownloadedPayload:
        self.fetch_calls.append(url)
        return DownloadedPayload(
            url=url, content_type="application/pdf",
            data=b"%PDF-1.3 fake " + url.encode())


class FakeHrClient:
    request_delay = 0.0

    def __init__(self, nif: str | None = "A-1") -> None:
        self.search_calls: list[str] = []
        self.page_calls: list[str] = []
        self._nif = nif

    def search_entity(self, denominacion: str, *, desde: str = "",
                      hasta: str = "") -> HrSearchResult:
        self.search_calls.append(denominacion)
        html = (
            '<p class="tituloDatos">FONDO A, FI</p><ul><li>'
            '<li class="liFechaRegistro">28/10/2011</li>'
            '<li class="liHora">18:30</li>'
            '<span class="descripcionSubtituloCabecera">Fusión de IIC'
            '</span><li class="liSubtituloRegistro"><div>Autorizada la '
            'fusión por absorción de FONDO A, FI (número 111), por '
            'FONDO B, FI (número 222).</div></li>'
            '<span>Número de registro: 99887</span>'
            '<a href="resultadobusquedahr.aspx?x=1&page=2">p2</a>'
            '</li></ul>')
        url = (f"https://www.cnmv.es/portal/hr/resultadobusquedahr"
               f"?division=2&nif={self._nif}")
        return HrSearchResult(
            final_url=url, raw_html=html, nif=self._nif,
            nif_candidates=(self._nif,) if self._nif else (),
            no_results=self._nif is None)

    def fetch_result_page(self, result_url: str) -> HrPage:
        self.page_calls.append(result_url)
        return HrPage(url=result_url, raw_html="<ul><li></li></ul>")


def _manifest(tmp: Path, ids: list[str]) -> Path:
    m = tmp / "holdout.json"
    m.write_text(json.dumps({
        "entries": [{"candidate_id": i} for i in ids]}),
        encoding="utf-8")
    return m


def _cand(cid: str, key: str = "FI:111"):
    from cnmv_iic.lifecycle import DisappearanceCandidate
    return DisappearanceCandidate(
        candidate_id=cid, candidate_type="FUND_DISAPPEARED",
        entity_key=key, previous_observed_period="2012-01",
        current_observed_period="2012-02",
        last_observed_present="2012-01",
        first_observed_absent="2012-02",
        previous_artifact_id=None, previous_locator=None,
        entity_type="F", denominacion="FONDO A, FI",
        manager_register_number="1", lifespan_months=12)


# ---------------------------------------------------------------------------
# weekly acquisition
# ---------------------------------------------------------------------------

def test_weekly_roles_and_selection_evidence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    out = acquire_weeks(
        store, tmp_path / "ds", "2012-01", "2012-02",
        client=FakeWeeklyClient())
    assert out["acquired"] == 2
    assert out["no_document"] == 1
    arts = {a.period: a for a in store.load()}
    assert "100/registro" in arts
    assert "101/boletin_completo" in arts      # general fallback
    assert "102/selection" in arts           # gap evidence kept


def test_weekly_resume_is_zero_network(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    c1 = FakeWeeklyClient()
    acquire_weeks(store, tmp_path / "ds", "2012-01", "2012-02",
                  client=c1)
    c2 = FakeWeeklyClient()
    out = acquire_weeks(store, tmp_path / "ds", "2012-01", "2012-02",
                        client=c2)
    assert out["already_have"] == 3
    assert c2.select_calls == []             # 0 network on rerun
    assert c2.fetch_calls == []


def test_blob_supersedes_on_changed_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    a1, _ = store.put_blob(
        period="100/registro", source_page="p", source_url="u",
        content_type="application/pdf", data=b"PDF-v1",
        raw_suffix=".pdf", source_family="cnmv_weekly_registry",
        source_id_prefix="cnmv-weekly-registry")
    a2, _ = store.put_blob(
        period="100/registro", source_page="p", source_url="u",
        content_type="application/pdf", data=b"PDF-v2",
        raw_suffix=".pdf", source_family="cnmv_weekly_registry",
        source_id_prefix="cnmv-weekly-registry")
    assert a1.sha256 != a2.sha256
    assert a2.supersedes == a1.source_id
    assert store.raw_path(a1).exists()       # old bytes never overwritten
    assert store.raw_path(a2).exists()


# ---------------------------------------------------------------------------
# HR acquisition + holdout
# ---------------------------------------------------------------------------

def test_hr_never_queries_holdout(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    manifest = _manifest(tmp_path, ["sealed-1"])
    client = FakeHrClient()
    cands = [_cand("sealed-1"), _cand("dev-2", key="FI:999")]
    out = acquire_hr(
        store, tmp_path / "ds", manifest,
        candidates=cands, client=client)
    assert out["sealed_skipped"] == 1
    assert len(client.search_calls) == 1     # only the dev candidate


def test_hr_resolved_pages_stored(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    manifest = _manifest(tmp_path, [])
    client = FakeHrClient()
    out = acquire_hr(
        store, tmp_path / "ds", manifest,
        candidates=[_cand("dev-1")], client=client)
    assert out["resolved"] == 1
    periods = {a.period for a in store.load()}
    assert "hr/FI:111/search" in periods
    assert "hr/FI:111/history_p2" in periods  # pagination followed
    assert client.page_calls                # page 2 fetched


def test_hr_not_found_and_ambiguous(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    manifest = _manifest(tmp_path, [])
    out = acquire_hr(
        store, tmp_path / "ds", manifest,
        candidates=[_cand("dev-1")], client=FakeHrClient(nif=None))
    assert out["not_found"] == 1


# ---------------------------------------------------------------------------
# offline rebuild + determinism + holdout visibility
# ---------------------------------------------------------------------------

def _small_pdf() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50.0
    for ln in [
            "BOLETÍN DE REGISTRO", "Semana del 31/01/2012 al 06/02/2012",
            "FONDOS DE INVERSIÓN DE CARÁCTER FINANCIERO",
            "BAJAS",
            "FONDO A, FI", "111",
            "FUSIÓN DE FONDOS DE INVERSIÓN",
            "Inscribir la fusión por absorción de FONDO A, FI (inscrito "
            "en el correspondiente registro de la CNMV con el número "
            "111), por FONDO B, FI (inscrito en el correspondiente "
            "registro de la CNMV con el número 222)."]:
        page.insert_text((50, y), ln, fontsize=8)
        y += 12
    return doc.tobytes()


def _hr_html() -> bytes:
    return (
        '<p class="tituloDatos">FONDO A, FI</p><ul><li>'
        '<li class="liFechaRegistro">28/10/2011</li>'
        '<li class="liHora">18:30</li>'
        '<span class="descripcionSubtituloCabecera">Fusión de IIC'
        '</span><li class="liSubtituloRegistro"><div>Autorizada la '
        'fusión por absorción de FONDO A, FI (número 111), por '
        'FONDO B, FI (número 222).</div></li>'
        '<span>Número de registro: 99887</span>'
        '</li></ul>').encode()


def _seed_store(tmp: Path) -> ArtifactStore:
    store = ArtifactStore(tmp / "art")
    store.put_blob(
        period="100/registro", source_page="p", source_url="u",
        content_type="application/pdf", data=_small_pdf(),
        raw_suffix=".pdf", source_family="cnmv_weekly_registry",
        source_id_prefix="cnmv-weekly-registry")
    store.put_blob(
        period="hr/FI:111/search", source_page="p", source_url="u",
        content_type="text/html", data=_hr_html(), raw_suffix=".html",
        source_family="cnmv_iic_relevant_information",
        source_id_prefix="cnmv-iic-relevant-information")
    return store


def test_offline_rebuild_deterministic(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _seed_store(tmp_path)

    def _no_net(*a: object, **k: object) -> None:
        raise AssertionError("network access during offline rebuild")

    monkeypatch.setattr(urllib.request, "urlopen", _no_net)
    monkeypatch.setattr(
        urllib.request.OpenerDirector, "open", _no_net)
    d1 = weekly_ledger(store)
    h1 = hr_ledger(store)
    d2 = weekly_ledger(store)
    h2 = hr_ledger(store)
    assert d1 == d2 and h1 == h2


def test_hr_assertions_from_stored_artifact(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    docs, obs, asserts, res = hr_ledger(store)
    assert docs and obs and asserts
    merger = [a for a in asserts
              if a.assertion_type == "MERGER_AUTHORIZED"]
    assert merger
    assert merger[0].subject_identifier_raw == "111"
    assert merger[0].object_identifier_raw == "222"
    assert merger[0].assertion_stage == "AUTHORIZED"
    assert res[0].resolution_state == "EXACT_REGNUM_CORROBORATED"


def test_no_holdout_links_visible_in_export(tmp_path: Path) -> None:
    store = _seed_store(tmp_path)
    _, _, asserts = weekly_ledger(store)
    sealed = {"sealed-1"}
    links = candidate_links(
        [_cand("sealed-1"), _cand("dev-1")], asserts, sealed)
    out = write_lifecycle(
        tmp_path / "ds",
        documents=[], observations=[], assertions=asserts,
        entity_resolutions=[], candidate_links=links,
        candidates=[_cand("sealed-1"), _cand("dev-1")])
    assert out["candidate_links"] == len(links)
    table = pq.read_table(
        tmp_path / "ds" / "lifecycle" / "candidate_links"
        / "part-0.parquet")
    visible = set(table.column("candidate_id").to_pylist())
    assert "sealed-1" not in visible


# ---------------------------------------------------------------------------
# FONDREGISTRO markers
# ---------------------------------------------------------------------------

def _fund_row(key: str, reg: str, denom: str) -> dict:
    return {
        "period": "2012-01", "fund_key": key, "entity_type": "F",
        "numero_registro": reg, "denominacion": denom, "etf": None,
        "gestora_numero_registro": "1", "gestora_denominacion": None,
        "gestora_tipo": None, "grupo_gestora_numero": None,
        "grupo_gestora_denominacion": None,
        "depositario_numero_registro": None,
        "depositario_denominacion": None,
        "grupo_depositario_numero": None,
        "grupo_depositario_denominacion": None,
        "n_compartments": None, "n_share_classes": None,
        "source_artifact_id": "art-1", "source_sha256": "x",
        "xml_locator": f"f/{reg}", "parser": "p", "parser_version": "1"}


def _funds_parquet(tmp: Path) -> Path:
    ds = tmp / "ds"
    rows = [
        _fund_row("FI:111", "111", "FONDO A, FI baja 03.02.2012"),
        _fund_row("FI:222", "222", "FONDO B, FI (EN LIQUIDACION)")]
    path = ds / "funds" / "period=2012-01" / "part-0.parquet"
    path.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=FUNDS_SCHEMA), path)
    return ds


def test_fondregistro_markers_auxiliary(tmp_path: Path) -> None:
    ds = _funds_parquet(tmp_path)
    store = ArtifactStore(tmp_path / "art")
    docs, obs, asserts = fondregistro_markers(ds, store)
    types = {a.assertion_type for a in asserts}
    assert "REGISTRY_NAME_BAJA_MARKER" in types
    assert "REGISTRY_NAME_IN_LIQUIDATION_MARKER" in types
    baja = [a for a in asserts
            if a.assertion_type == "REGISTRY_NAME_BAJA_MARKER"][0]
    assert baja.asserted_date == "2012-02-03"
    assert baja.asserted_date_semantics == "SOURCE_BAJA_MARKER_DATE"
    # never a lifecycle cause — auxiliary source assertions only
    assert all(a.assertion_stage == "REPORTED" for a in asserts)


def test_disappearance_candidates_contiguous_only(tmp_path: Path) -> None:
    ds = _funds_parquet(tmp_path)
    cands = disappearance_candidates(ds)
    assert cands == []  # single period -> no adjacent diff


def test_correction_chain_resolved_by_explicit_date(
        tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    html = (
        '<p class="tituloDatos">FONDO A, FI</p><ul><li>'
        '<li class="liFechaRegistro">01/06/2015</li>'
        '<li class="liHora">10:00</li>'
        '<span class="descripcionSubtituloCabecera">Fusión de IIC'
        '</span><li class="liSubtituloRegistro"><div>Autorizada la '
        'fusión de FONDO A, FI (número 111).</div></li>'
        '<span>Número de registro: 1</span>'
        '<li class="liFechaRegistro">02/06/2015</li>'
        '<li class="liHora">10:00</li>'
        '<span class="descripcionSubtituloCabecera">Rectificación Hecho'
        ' Relevante</span><li class="liSubtituloRegistro"><div>'
        'Rectificación del hecho relevante publicado con fecha '
        '01/06/2015.</div></li>'
        '<span>Número de registro: 2</span>'
        '</li></ul>').encode()
    store.put_blob(
        period="hr/FI:111/search", source_page="p", source_url="u",
        content_type="text/html", data=html, raw_suffix=".html",
        source_family="cnmv_iic_relevant_information",
        source_id_prefix="cnmv-iic-relevant-information")
    _, obs, asserts, _ = hr_ledger(store)
    rect = [a for a in asserts
            if a.assertion_type == "RECTIFICATION_REPORTED"]
    assert len(rect) == 1
    assert rect[0].correction_target_state == "resolved"
    target = {o.source_observation_id for o in obs
              if o.publication_datetime == "2015-06-01T10:00"}
    assert rect[0].correction_of_observation_id in target


def test_correction_without_date_stays_unresolved(
        tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "art")
    html = (
        '<p class="tituloDatos">FONDO A, FI</p><ul><li>'
        '<li class="liFechaRegistro">02/06/2015</li>'
        '<li class="liHora">10:00</li>'
        '<span class="descripcionSubtituloCabecera">Rectificación Hecho'
        ' Relevante</span><li class="liSubtituloRegistro"><div>'
        'Rectificación del hecho relevante anterior.</div></li>'
        '<span>Número de registro: 2</span>'
        '</li></ul>').encode()
    store.put_blob(
        period="hr/FI:111/search", source_page="p", source_url="u",
        content_type="text/html", data=html, raw_suffix=".html",
        source_family="cnmv_iic_relevant_information",
        source_id_prefix="cnmv-iic-relevant-information")
    _, _, asserts, _ = hr_ledger(store)
    rect = [a for a in asserts
            if a.assertion_type == "RECTIFICATION_REPORTED"]
    assert rect[0].correction_target_state == "unresolved"
    assert rect[0].correction_of_observation_id is None
