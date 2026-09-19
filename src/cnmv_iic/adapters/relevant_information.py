"""G9-B — relevant-information (HR) event parser + stage classifier.

One observation per hecho relevante; zero-or-more descriptive
assertions per observation. Stage semantics stay source-literal:

    autoriza/aprueba          -> AUTHORIZED
    solicita/proyecta         -> REQUESTED/PROPOSED
    inscribe/registra         -> REGISTERED
    ejecuta/canje definitivo  -> EXECUTED
    desiste/renuncia          -> RENOUNCED
    disolución acordada       -> DISSOLUTION_AGREED
    liquidación efectuada     -> LIQUIDATION_EXECUTED
    rectificación             -> RECTIFICATION_REPORTED

AUTHORIZED is never promoted to EXECUTED; a later disappearance never
reclassifies the assertion. Unknown categories are preserved raw and
classified UNKNOWN/OTHER — never coerced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cnmv_iic.acquisition.hr import (
    parse_entity_header,
    parse_event_entries,
)

PARSER = "cnmv_iic.adapters.relevant_information"
PARSER_VERSION = "1"

_BAJA_MARKER = re.compile(r"baja\s+(\d{2})\.(\d{2})\.(\d{2,4})", re.I)
_EN_LIQ = re.compile(r"\(?\s*EN LIQUIDACI.N\s*\)?", re.I)
_REGNUM_TEXT = re.compile(r"n[úu]mero\s*(\d{1,6})", re.I)
_POR_CLAUSE = re.compile(r",\s*por\s+")
_DDMMYYYY = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_DATE_ES = re.compile(
    r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|"
    r"agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
    re.I)
_MONTHS = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
           "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
           "octubre": 10, "noviembre": 11, "diciembre": 12}

_EFECTOS = re.compile(
    r"(?:con\s+)?efectos?(?:\s+econ.micos)?(?:\s+de|\s+desde|\s+a\s+"
    r"partir\s+de)?\s*(?:el\s+)?", re.I)
_EFECTIVIDAD = re.compile(r"efectividad\s+(?:el\s+)?", re.I)
_CANJE_FECHA = re.compile(
    r"canje[^.]{0,60}?(?:el|el\s+d.a|fecha)\s+", re.I)


@dataclass(frozen=True)
class HrObservationDraft:
    """One hecho relevante — becomes lifecycle_source_observation."""
    publication_date: str | None       # ISO from 'date' field
    publication_time: str | None
    category_raw: str
    summary_raw: str
    doc_url: str | None
    hr_event_reg_number: str | None    # event reg number (not fund's)
    regnums_in_text: tuple[str, ...]
    successor_regnums: tuple[str, ...]
    source_locator: str
    correction_indicator: bool
    representation: str


@dataclass(frozen=True)
class HrAssertionDraft:
    """(type, stage, subject_regnum, object_regnum, object_name_raw,
    asserted_date, asserted_date_semantics)."""
    assertion_type: str
    assertion_stage: str
    subject_regnum: str | None
    object_regnum: str | None
    object_name_raw: str | None
    asserted_date: str | None = None
    asserted_date_semantics: str | None = None


@dataclass(frozen=True)
class HrPageParse:
    entity_header: str | None
    baja_marker_date: str | None       # ISO — SOURCE_BAJA_MARKER_DATE
    in_liquidation_marker: bool
    observations: tuple[HrObservationDraft, ...] = field(
        default_factory=tuple)


def _iso(d: int, m: int, y: int) -> str:
    return f"{y:04d}-{m:02d}-{d:02d}"


def _date_es_to_iso(text: str) -> str | None:
    m = _DATE_ES.search(text)
    if not m:
        return None
    return _iso(int(m.group(1)), _MONTHS[m.group(2).lower()],
                int(m.group(3)))


def _ddmm_to_iso(text: str) -> str | None:
    m = _DDMMYYYY.search(text)
    if not m:
        return None
    return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _pub_date(date_str: str) -> str | None:
    m = _DDMMYYYY.fullmatch(date_str.strip())
    if not m:
        return None
    return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _por_successors(text: str) -> tuple[str, ...]:
    hits = list(_POR_CLAUSE.finditer(text))
    if not hits:
        return ()
    tail = text[hits[-1].end():]
    return tuple(_REGNUM_TEXT.findall(tail))


def _explicit_date(text: str) -> tuple[str | None, str | None]:
    """Explicit official dates only — never publication-date fallback."""
    for pat, sem in ((_EFECTOS, "EFFECTIVE_DATE"),
                     (_EFECTIVIDAD, "EFFECTIVE_DATE"),
                     (_CANJE_FECHA, "EXECUTION_DATE")):
        m = pat.search(text)
        if m:
            iso = _ddmm_to_iso(text[m.end():m.end() + 25])
            if iso is None:
                iso = _date_es_to_iso(text[m.end():m.end() + 60])
            if iso:
                return iso, sem
    return None, None


def parse_history_page(html: str) -> HrPageParse:
    """Parse one ResultadoBusquedaHR page (any pagination page)."""
    header = parse_entity_header(html)
    baja_date = None
    in_liq = False
    if header:
        m = _BAJA_MARKER.search(header)
        if m:
            y = int(m.group(3))
            y += 2000 if y < 100 else 0
            baja_date = _iso(int(m.group(1)), int(m.group(2)), y)
        in_liq = bool(_EN_LIQ.search(header))
    obs: list[HrObservationDraft] = []
    for i, e in enumerate(parse_event_entries(html)):
        obs.append(HrObservationDraft(
            publication_date=_pub_date(e.date),
            publication_time=e.time or None,
            category_raw=e.category,
            summary_raw=e.summary,
            doc_url=e.doc_url,
            hr_event_reg_number=e.hr_event_reg_number,
            regnums_in_text=tuple(_REGNUM_TEXT.findall(e.summary)),
            successor_regnums=_por_successors(e.summary),
            source_locator=f"hr_event={i}/date={e.date}",
            correction_indicator=bool(
                re.search(r"rectific", e.summary + e.category, re.I)),
            representation="structured",
        ))
    return HrPageParse(
        entity_header=header, baja_marker_date=baja_date,
        in_liquidation_marker=in_liq,
        observations=tuple(obs))


# ---------------------------------------------------------------------------
# stage classification — source-literal, never promoted
# ---------------------------------------------------------------------------

def _has(t: str, *pats: str) -> bool:
    return any(re.search(p, t, re.I) for p in pats)


def _subject_of(o: HrObservationDraft) -> str | None:
    """Primary subject regnum: first non-successor regnum in prose."""
    succ = set(o.successor_regnums)
    for r in o.regnums_in_text:
        if r not in succ:
            return r
    return None


def hr_assertions(o: HrObservationDraft) -> list[HrAssertionDraft]:
    """Descriptive assertions for one HR event. Category semantics are
    never assumed — the 57 CNMV categories are preserved raw."""
    t = o.category_raw + " " + o.summary_raw
    subj = _subject_of(o)
    succ = o.successor_regnums[0] if o.successor_regnums else None
    oname = None
    if succ is None:
        m = list(_POR_CLAUSE.finditer(o.summary_raw))
        if m:
            nm = re.match(r"([^,(]+)", o.summary_raw[m[-1].end():])
            oname = nm.group(1).strip() if nm else None
    date_iso, date_sem = _explicit_date(t)
    out: list[HrAssertionDraft] = []

    def emit(atype: str, stage: str) -> None:
        out.append(HrAssertionDraft(
            assertion_type=atype, assertion_stage=stage,
            subject_regnum=subj, object_regnum=succ,
            object_name_raw=oname, asserted_date=date_iso,
            asserted_date_semantics=date_sem))

    if _has(t, r"rectific"):
        emit("RECTIFICATION_REPORTED", "REPORTED")
        return out
    merger = _has(t, r"fusi.n|absorci.n|absorb|canje")
    if merger:
        if _has(t, r"desist|renunci|revoc"):
            emit("MERGER_RENOUNCED", "RENOUNCED")
        elif _has(t, r"ecuaci.n de canje definitiva|efectuad|"
                     r"consumad|extinguid|llevad[oa] a cabo"):
            emit("MERGER_EXECUTED", "EXECUTED")
        elif _has(t, r"autoriz|aprueb|aprob"):
            emit("MERGER_AUTHORIZED", "AUTHORIZED")
        elif _has(t, r"inscrib|registr|inscripci.n"):
            emit("MERGER_REGISTERED", "REGISTERED")
        elif _has(t, r"proyecto|solicitud|com.n de fusi.n|"
                     r"somete[rd]?.*aprobaci.n"):
            emit("MERGER_REQUESTED", "REQUESTED")
        else:
            emit("OTHER_LIFECYCLE_ASSERTION", "UNKNOWN_STAGE")
        return out
    if _has(t, r"disoluci"):
        emit("DISSOLUTION_AGREED", "DISSOLUTION_AGREED")
    if _has(t, r"liquidaci"):
        emit("LIQUIDATION_EXECUTED", "LIQUIDATION_EXECUTED")
    if out:
        return out
    if _has(t, r"\bbaja\b|cancelaci.n de la inscripci.n"):
        emit("DEREGISTRATION_REPORTED", "REPORTED")
    elif _has(t, r"transformaci"):
        emit("TRANSFORMATION_RECORDED", "TRANSFORMATION_RECORDED")
    elif _has(t, r"sustituci|revocaci") and _has(t, r"gestor|gesti.n"):
        emit("MANAGER_SUBSTITUTION_REPORTED", "REPORTED")
    elif _has(t, r"sustituci|cambio") and _has(t, r"depositar"):
        emit("DEPOSITARY_SUBSTITUTION_REPORTED", "REPORTED")
    else:
        emit("OTHER_LIFECYCLE_ASSERTION", "REPORTED")
    return out
