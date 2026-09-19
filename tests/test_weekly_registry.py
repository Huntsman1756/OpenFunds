"""G9-B — weekly registry bulletin parser tests.

Synthetic PDFs built with PyMuPDF reproduce the measured layout:
stacked/interleaved headers, table rows (name/gestora/dep/regnum and
two-column name/regnum), prose acts with subject headers, merger prose
with '… número N' / ', por <fund> (… número K)' clauses, and other
entity sections sharing the document.
"""

from __future__ import annotations

import pymupdf
import pytest

from cnmv_iic.adapters.weekly_registry import (
    bulletin_assertions,
    parse_registry_document,
)


def _pdf(lines: list[str], *, header: bool = True) -> bytes:
    """Each entry becomes 1+ PDF lines wrapped at ~100 chars (insert_text
    clips at page width)."""
    import textwrap
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50.0
    if header:
        page.insert_text(
            (50, y),
            "BOLETÍN DE REGISTRO DE INSTITUCIONES DE INVERSIÓN COLECTIVA",
            fontsize=9)
        y += 14
        page.insert_text(
            (50, y), "Semana del 12/04/2016 al 18/04/2016", fontsize=9)
        y += 20
    for entry in lines:
        for ln in textwrap.wrap(entry, 100) or [""]:
            if y > 780:
                page = doc.new_page()
                y = 50.0
            page.insert_text((50, y), ln, fontsize=8)
            y += 11
    return doc.tobytes()


FI_HDR = "FONDOS DE INVERSIÓN DE CARÁCTER FINANCIERO"


def _baja_doc() -> bytes:
    """Stacked headers + mixed baja table (4-col then 2-col rows)."""
    return _pdf([
        FI_HDR,
        "NUEVAS INSCRIPCIONES",
        "Denominación", "Gestora", "Depositaria", "Nº", "Registro",
        "NOVAGALICIA GARANTIZADO PREMIUM, FI",
        "AHORRO CORPORACION GESTION, S.G.I.I.C., S.A.",
        "NCG BANCO, S.A.",
        "4434",
        "BAJAS",
        "MODIFICACIONES EN REGLAMENTOS",
        "ACTUALIZACIÓN DE ELEMENTOS ESENCIALES DE FOLLETOS",
        "INFORMATIVOS",
        "BANCA CIVICA TIPO",
        "GARANTIZADO V, FI",
        "BANCA CIVICA GESTION DE",
        "ACTIVOS, SGIIC, SA",
        "BANCA CIVICA,",
        "S.A.",
        "4435",
        "BBVA BONOS INTERES FLOTANTE II, FI",
        "3375",
        "FONCAIXA AHORRO, FI",
        "155",
        "FUSIÓN DE FONDOS DE INVERSIÓN",
        "Inscribir a solicitud de SANTANDER ASSET MANAGEMENT, S.A., "
        "SGIIC, como entidad Gestora, y de SANTANDER INVESTMENT, S.A., "
        "como entidad Depositaria, la fusión por absorción de BANIF "
        "ESTRUCTURADO BANCA EUROPEA, FI (inscrito en el correspondiente "
        "registro de la CNMV con el número 4000), por BANIF MONETARIO, "
        "FI (inscrito en el correspondiente registro de la CNMV con el "
        "número 3944).",
        "SOCIEDADES DE INVERSIÓN DE CARÁCTER FINANCIERO",
        "NUEVAS INSCRIPCIONES",
        "BAJAS",
        "MURADA DE INVERSIONES, SICAV S.A. (EN LIQUIDACION)",
        "665",
    ])


def test_fi_section_found_and_week_label() -> None:
    r = parse_registry_document(_baja_doc())
    assert r.fi_section_found
    assert r.week_label == "12/04/2016 al 18/04/2016"


def test_baja_rows_are_deregistration_not_liquidation() -> None:
    r = parse_registry_document(_baja_doc())
    bajas = [
        o for o in r.observations if o.source_section_raw == "BAJAS"]
    regs = {o.subject_register_number_raw for o in bajas}
    assert {"4435", "3375", "155"} <= regs
    sicav = [o for o in bajas if o.subject_register_number_raw == "665"]
    assert not sicav  # SICAV baja is a different registry namespace
    for o in bajas:
        for atype, stage, *_ in bulletin_assertions(o):
            assert atype == "DEREGISTRATION_RECORDED"
            assert stage == "DEREGISTERED"  # never LIQUIDATED


def test_alta_row_is_registration_recorded() -> None:
    r = parse_registry_document(_baja_doc())
    nuevas = [
        o for o in r.observations
        if o.source_section_raw == "NUEVAS INSCRIPCIONES"]
    assert [o.subject_register_number_raw for o in nuevas] == ["4434"]
    assert nuevas[0].subject_name_raw == (
        "NOVAGALICIA GARANTIZADO PREMIUM, FI")
    assert bulletin_assertions(nuevas[0]) == [
        ("REGISTRATION_RECORDED", "REGISTERED", "4434", None, None)]


def test_merger_exact_subject_and_successor() -> None:
    r = parse_registry_document(_baja_doc())
    fus = [
        o for o in r.observations
        if o.source_section_raw == "FUSION DE FONDOS DE INVERSION"]
    assert len(fus) == 1
    o = fus[0]
    assert o.successor_regnums == ("3944",)
    asserts = bulletin_assertions(o)
    assert asserts == [(
        "MERGER_REGISTRATION_RECORDED", "REGISTERED",
        "4000", "3944", None)]


def test_merger_name_only_successor_stays_unresolved() -> None:
    pdf = _pdf([
        FI_HDR,
        "FUSIÓN DE FONDOS DE INVERSIÓN",
        "Inscribir la fusión por absorción de FONDO ALFA, FI (inscrito "
        "en el correspondiente registro de la CNMV con el número 1111), "
        "por FONDO BETA EXTRANJERO, entidad domiciliada en Luxemburgo.",
    ])
    r = parse_registry_document(pdf)
    fus = [
        o for o in r.observations
        if o.source_section_raw == "FUSION DE FONDOS DE INVERSION"]
    assert len(fus) == 1
    asserts = bulletin_assertions(fus[0])
    assert len(asserts) == 1
    atype, stage, subj, obj, oname = asserts[0]
    assert atype == "MERGER_REGISTRATION_RECORDED"
    assert subj == "1111"
    assert obj is None                 # no fuzzy successor
    assert oname and "FONDO BETA" in oname


def test_unknown_template_degrades_to_verbatim() -> None:
    pdf = _pdf([
        FI_HDR,
        "ACTOS NO RECONOCIBLES DE LA PLANTILLA HISTORICA",
        "algún texto sin estructura de tabla ni verbo de acto reg.",
    ])
    r = parse_registry_document(pdf)
    assert r.observations              # evidence is never dropped
    reps = {o.representation for o in r.observations}
    assert "verbatim_only" in reps


def test_no_fi_section_marks_document() -> None:
    pdf = _pdf(["DOCUMENTO SIN SECCION DE FONDOS", "texto cualquiera"])
    r = parse_registry_document(pdf)
    assert not r.fi_section_found
    assert any(o.source_section_raw == "NO_FI_SECTION"
               for o in r.observations)


def test_sicav_and_other_entities_get_no_fi_assertions() -> None:
    r = parse_registry_document(_baja_doc())
    others = [
        o for o in r.observations
        if o.source_section_raw == "OTHER_ENTITY_CONTEXT"]
    assert others                      # SICAV 665 preserved verbatim
    assert any("665" in o.observation_text_verbatim for o in others)
    for o in others:
        assert bulletin_assertions(o) == []


def test_determinism() -> None:
    pdf = _baja_doc()
    a = parse_registry_document(pdf)
    b = parse_registry_document(pdf)
    assert a == b


def test_prose_subject_header_pairs_regnum() -> None:
    """NAME/NUM/<verb> — the row header is the act's subject."""
    pdf = _pdf([
        FI_HDR,
        "MODIFICACIONES EN REGLAMENTOS",
        "KUTXAINDEX, FI",
        "924",
        "Inscribir el cambio de la denominación de la institución que "
        "pasa a ser KUTXABANK GARANTIZADO II, FI.",
    ])
    r = parse_registry_document(pdf)
    prose = [
        o for o in r.observations if o.representation != "verbatim_only"]
    assert any(
        o.subject_register_number_raw == "924"
        and o.subject_name_raw == "KUTXAINDEX, FI" for o in prose)


@pytest.mark.parametrize("verb", ["Inscribir", "Verificar y registrar",
                                  "Autorizar"])
def test_act_verbs_recognized(verb: str) -> None:
    pdf = _pdf([
        FI_HDR,
        f"{verb} a solicitud de X GESTORA, el acto sobre FONDO Z, FI "
        "(inscrito en el correspondiente registro de la CNMV con el "
        "número 555).",
    ])
    r = parse_registry_document(pdf)
    assert any("555" in o.regnums_in_text for o in r.observations)
