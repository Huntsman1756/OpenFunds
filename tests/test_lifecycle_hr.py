"""G9-B — HR parser, stage discipline, and candidate-linkage tests."""

from __future__ import annotations

import pytest

from cnmv_iic.adapters.relevant_information import (
    hr_assertions,
    parse_history_page,
)
from cnmv_iic.lifecycle import (
    DisappearanceCandidate,
    LifecycleAssertion,
)
from cnmv_iic.lifecycle_ingest import candidate_links


def _hr_page(events: list[tuple[str, str, str, str]],
             header: str = "") -> str:
    """(date, time, category, summary) -> synthetic result page."""
    ev = ""
    for date, time, cat, summ in events:
        ev += (
            f'<li class="liFechaRegistro">{date}</li>'
            f'<li class="liHora">{time}</li>'
            f'<span class="descripcionSubtituloCabecera">{cat}</span>'
            f'<li class="liSubtituloRegistro"><div>{summ}'
            f'<a href="/verdocumento/ver?e=ABC123">doc</a></div></li>'
            f'<span>Número de registro: 99887</span>')
    return (
        f'<p class="tituloDatos">{header}</p>'
        f"<ul><li>{ev}</li></ul>")


def test_event_fields_and_event_regnum() -> None:
    html = _hr_page([(
        "28/10/2011", "18:30", "Fusión de IIC",
        "Autorizada la fusión por absorción de FONDO A, FI (número 111)"
        ", por FONDO B, FI (número 222).")])
    p = parse_history_page(html)
    assert len(p.observations) == 1
    o = p.observations[0]
    assert o.publication_date == "2011-10-28"
    assert o.publication_time == "18:30"
    assert o.category_raw == "Fusión de IIC"
    assert o.hr_event_reg_number == "99887"  # event reg, NOT fund reg
    assert o.regnums_in_text == ("111", "222")
    assert o.successor_regnums == ("222",)


def test_authorized_never_promoted() -> None:
    html = _hr_page([(
        "28/10/2011", "18:30", "Fusión de IIC",
        "Autorizada la fusión por absorción de FONDO A, FI (número 111)"
        ", por FONDO B, FI (número 222).")])
    p = parse_history_page(html)
    asserts = hr_assertions(p.observations[0])
    assert len(asserts) == 1
    a = asserts[0]
    assert a.assertion_type == "MERGER_AUTHORIZED"
    assert a.assertion_stage == "AUTHORIZED"
    assert a.subject_regnum == "111"
    assert a.object_regnum == "222"


def test_executed_via_definitive_canje() -> None:
    html = _hr_page([(
        "03/02/2012", "09:00", "Ecuación de canje",
        "Se comunica la ecuación de canje definitiva de la fusión por "
        "absorción de FONDO A, FI (número 111), por FONDO B, FI "
        "(número 222).")])
    p = parse_history_page(html)
    asserts = hr_assertions(p.observations[0])
    assert asserts[0].assertion_type == "MERGER_EXECUTED"
    assert asserts[0].assertion_stage == "EXECUTED"


def test_renounced_and_rectified_preserved() -> None:
    html = _hr_page([
        ("01/06/2015", "10:00", "Fusión de IIC",
         "Desistimiento de la fusión autorizada de FONDO A, FI "
         "(número 111)."),
        ("02/06/2015", "10:00", "Rectificación Hecho Relevante",
         "Rectificación del hecho relevante publicado con fecha "
         "01/06/2015."),
    ])
    p = parse_history_page(html)
    a0 = hr_assertions(p.observations[0])[0]
    a1 = hr_assertions(p.observations[1])[0]
    assert a0.assertion_type == "MERGER_RENOUNCED"
    assert a0.assertion_stage == "RENOUNCED"
    assert a1.assertion_type == "RECTIFICATION_REPORTED"
    assert p.observations[1].correction_indicator


def test_dissolution_and_liquidation_stay_separate() -> None:
    html = _hr_page([(
        "15/03/2018", "12:00", "Baja de IIC",
        "Acuerdos de disolución y liquidación de FONDO X, FI "
        "(número 333).")])
    p = parse_history_page(html)
    types = {a.assertion_type for a in hr_assertions(p.observations[0])}
    assert types == {"DISSOLUTION_AGREED", "LIQUIDATION_EXECUTED"}


def test_entity_header_baja_marker() -> None:
    html = _hr_page(
        [], header="BBVA FONDO, FI baja 03.02.2012")
    p = parse_history_page(html)
    assert p.baja_marker_date == "2012-02-03"


def test_entity_header_en_liquidacion() -> None:
    html = _hr_page(
        [], header="FONDO Z, FI (EN LIQUIDACION)")
    p = parse_history_page(html)
    assert p.in_liquidation_marker


def test_unknown_category_preserved_not_coerced() -> None:
    html = _hr_page([(
        "01/01/2020", "08:00", "Categoria Nunca Vista",
        "Texto libre sin términos de ciclo de vida reconocibles.")])
    p = parse_history_page(html)
    o = p.observations[0]
    assert o.category_raw == "Categoria Nunca Vista"
    a = hr_assertions(o)[0]
    assert a.assertion_type == "OTHER_LIFECYCLE_ASSERTION"


def test_explicit_effective_date_only() -> None:
    html = _hr_page([(
        "10/10/2019", "09:00", "Fusión de IIC",
        "Autorizada la fusión con efectos de 01/12/2019 de FONDO A, FI "
        "(número 111), por FONDO B, FI (número 222).")])
    p = parse_history_page(html)
    a = hr_assertions(p.observations[0])[0]
    assert a.asserted_date == "2019-12-01"
    assert a.asserted_date_semantics == "EFFECTIVE_DATE"
    # publication date is never a fallback
    html2 = _hr_page([(
        "10/10/2019", "09:00", "Fusión de IIC",
        "Autorizada la fusión de FONDO A, FI (número 111) por "
        "FONDO B, FI (número 222).")])
    p2 = parse_history_page(html2)
    a2 = hr_assertions(p2.observations[0])[0]
    assert a2.asserted_date is None
    assert a2.asserted_date_semantics is None


# ---------------------------------------------------------------------------
# candidate linkage — exact regnum only, holdout guard
# ---------------------------------------------------------------------------

def _cand(cid: str, key: str = "FI:111") -> DisappearanceCandidate:
    return DisappearanceCandidate(
        candidate_id=cid, candidate_type="FUND_DISAPPEARED",
        entity_key=key, previous_observed_period="2012-01",
        current_observed_period="2012-02",
        last_observed_present="2012-01",
        first_observed_absent="2012-02",
        previous_artifact_id=None, previous_locator=None,
        entity_type="F", denominacion="FONDO A, FI",
        manager_register_number="1", lifespan_months=12)


def _assertion(subject: str | None, obj: str | None) -> LifecycleAssertion:
    return LifecycleAssertion(
        assertion_id=f"lass-{subject}-{obj}",
        source_observation_id="lobs-x", source_document_id="ldoc-x",
        source_family="cnmv_weekly_registry",
        assertion_type="MERGER_REGISTRATION_RECORDED",
        assertion_stage="REGISTERED",
        subject_key=f"FI:{subject}" if subject else None,
        subject_identifier_type=(
            "cnmv_register_number" if subject else None),
        subject_identifier_raw=subject,
        object_key=f"FI:{obj}" if obj else None,
        object_identifier_type=(
            "cnmv_register_number" if obj else None),
        object_identifier_raw=obj,
        asserted_date=None, asserted_date_semantics=None,
        publication_datetime=None, raw_text="", source_locator="",
        identity_state="exact_register_number",
        representation="structured",
        correction_of_observation_id=None,
        supersedes_assertion_id=None, correction_target_state=None,
        parser_version="1", rule_version="1")


def test_exact_subject_link() -> None:
    links = candidate_links(
        [_cand("c1")], [_assertion("111", "222")], sealed=set())
    assert len(links) == 1
    assert links[0].link_state == "EXACT_SUBJECT_REGNUM"


def test_exact_object_link() -> None:
    links = candidate_links(
        [_cand("c1")], [_assertion("999", "111")], sealed=set())
    assert len(links) == 1
    assert links[0].link_state == "EXACT_OBJECT_REGNUM"


def test_no_fuzzy_or_temporal_links() -> None:
    links = candidate_links(
        [_cand("c1")], [_assertion("112", None)], sealed=set())
    assert links == []  # similar regnum is not identity


def test_holdout_never_linked() -> None:
    links = candidate_links(
        [_cand("sealed-1"), _cand("c2")],
        [_assertion("111", None), _assertion("222", None)],
        sealed={"sealed-1"})
    assert all(lk.candidate_id != "sealed-1" for lk in links)
    assert [lk.candidate_id for lk in links] == ["c2"]


@pytest.mark.parametrize("sealed", [{"c1"}, {"c1", "c2"}])
def test_holdout_guard_parameterized(sealed: set[str]) -> None:
    links = candidate_links(
        [_cand("c1"), _cand("c2")],
        [_assertion("111", None)], sealed=sealed)
    assert all(lk.candidate_id not in sealed for lk in links)
