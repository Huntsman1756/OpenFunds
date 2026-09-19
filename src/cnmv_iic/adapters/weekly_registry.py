"""G9-B — weekly registry bulletin parser.

PDF -> source observations (never adjudicated events).

Measured template facts (docs/g9/coverage-probe.md):

- The FI fund section starts at the ALL-CAPS line-anchored header
  ``FONDOS DE INVERSIÓN DE CARÁCTER FINANCIERO`` (last occurrence —
  earlier hits are the document TOC).
- Column-interleaved extraction stacks subsection headers (``BAJAS``,
  ``MODIFICACIONES...``, ``ACTUALIZACIÓN...`` may appear consecutively
  before their content) and can inject a header mid-sentence. Section
  boundaries are therefore NOT trusted: units are segmented by
  content and classified by their own act verbs.
- Unit shapes seen:
    * table row:    ``NAME <wrapped> / GESTORA / DEPOSITARIA / NNNN``
                    or two-column ``NAME / NNNN``
    * prose act:    ``NAME / NNNN / <verb-paragraph>`` or bare
                    ``<verb-paragraph>`` — verbs observed: ``Inscribir``,
                    ``Verificar y registrar``, ``Autorizar``
- Merger prose: ``fusión por absorción de A (… número N), B (… número
  M), por S (… número K)`` — the ``, por`` clause carries the
  absorbing fund's register number.

Fail-closed: unrecognized templates degrade to ``verbatim_only``
observations — evidence is never dropped.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import pymupdf

PARSER = "cnmv_iic.adapters.weekly_registry"
PARSER_VERSION = "1"

# ---------------------------------------------------------------------------
# text normalization
# ---------------------------------------------------------------------------


def norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("�", "")
    s = re.sub(r"[^A-Z0-9]+", " ", s.upper())
    return re.sub(r"\s+", " ", s).strip()


FUND_HDR = re.compile(
    r"(?m)^\s*FONDOS DE INVERSI.N DE CAR.CTER FINANCIERO\s*$")

#: FI (carácter financiero) entity evidence — a fund name carrying the
#: legal suffix. Other registry namespaces (SICAV, FCR, gestoras, EAF)
#: lack it, so interleaved non-FI content is kept as observations but
#: never produces FI assertions.
_FI_EVIDENCE = re.compile(
    r",\s*(FI COTIZADO|FIIF|FIM|FICC|FI)\b|"
    r"Registro Administrativo de Fondos de Inversi", re.I)

#: Known ALL-CAPS header lines inside the FI section (normalized text).
#: They mark context only — never trusted as content boundaries.
TABLE_HEADERS = {"NUEVAS INSCRIPCIONES", "BAJAS"}
KNOWN_HEADERS = TABLE_HEADERS | {
    "MODIFICACIONES EN REGLAMENTOS",
    "MODIFICACIONES EN ESTATUTOS",
    "ACTUALIZACION DE ELEMENTOS ESENCIALES DE FOLLETOS INFORMATIVOS",
    "ACTUALIZACION DE FOLLETOS INFORMATIVOS",
    "ACUERDO DE DELEGACION REVOCACION DE LA GESTION DE ACTIVOS",
    "FUSION DE FONDOS DE INVERSION",
    "FUSION",
    "TRANSMISIONES DE PARTICIPACIONES",
    "VERIFICACION ADMISION A BOLSA",
    "EMISION DE PASAPORTE COMUNITARIO",
    "OTROS ACUERDOS",
}

_VERB_START = re.compile(
    r"(?i)^\s*(inscribir|verificar y registrar|autorizar|acordar|"
    r"comunicar|resolver|ordenar|disponer|dejar constancia|"
    r"verificar)\b")
_HEADER_NOISE = re.compile(
    r"^(n\.?º?\.?\s*registro|n\.?º?\.?|registro|denominaci.n|denominaci|"
    r"gestora|deposit|depositaria|entidad|fecha|domicilio|capital)$",
    re.I)
_REGNUM_LINE = re.compile(r"^\s*(\d{2,6})\s*$")
_REGNUM_TEXT = re.compile(r"n[úu]mero\s*(\d{1,6})", re.I)
_NAME_NUM_INSCRITO = re.compile(
    r"([^()]{2,}?)\s*\(\s*inscrito[^)]*?n[úu]mero\s*(\d{1,6})")
_NO_DATA = re.compile(r"no hay datos para esta semana", re.I)
_MAX_NAME_LINES = 8


@dataclass(frozen=True)
class ObservationDraft:
    """Parser output — becomes one lifecycle_source_observation."""
    source_section_raw: str | None
    subject_name_raw: str | None
    subject_register_number_raw: str | None
    regnums_in_text: tuple[str, ...]
    successor_regnums: tuple[str, ...]
    observation_text_verbatim: str
    source_locator: str
    representation: str


@dataclass(frozen=True)
class RegistryParse:
    n_pages: int
    week_label: str | None
    fi_section_found: bool
    sections_seen: tuple[str, ...]
    observations: tuple[ObservationDraft, ...] = field(
        default_factory=tuple)


def extract_pdf_text(pdf_bytes: bytes) -> tuple[str, list[int]]:
    """Concatenated page text + page boundary offsets."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    parts: list[str] = []
    bounds: list[int] = []
    pos = 0
    for pi in range(doc.page_count):
        t = doc.load_page(pi).get_text()
        parts.append(t)
        pos += len(t) + 1
        bounds.append(pos)
        parts.append("\n")
    return "".join(parts), bounds


def _page_of(bounds: list[int], offset: int) -> int:
    for i, b in enumerate(bounds):
        if offset < b:
            return i + 1
    return len(bounds)


def _fi_span(txt: str) -> tuple[int, int, bool]:
    """FI section start → end of document. Later sections' content is
    segmented too (injected header blocks cut mid-sentence, so hard
    truncation loses FI acts); the FI-evidence gate separates FI
    registry acts from other entity namespaces downstream."""
    matches = list(FUND_HDR.finditer(txt))
    if not matches:
        return 0, len(txt), False
    start = matches[-1].start()          # last hit = content, not TOC
    return start, len(txt), True


def _por_successors(text: str) -> tuple[str, ...]:
    """Register numbers inside the ', por <fund>' successor clause."""
    hits = list(re.finditer(r",\s*por\s+", text))
    if not hits:
        return ()
    tail = text[hits[-1].end():]
    return tuple(_REGNUM_TEXT.findall(tail))


def _name_regnums(text: str) -> list[tuple[str, str]]:
    """(name, regnum) pairs in '<name> (inscrito … número N)' form."""
    return [(m.group(1).strip(" ,.-"), m.group(2))
            for m in _NAME_NUM_INSCRITO.finditer(text)]


# ---------------------------------------------------------------------------
# content-driven unit segmentation
# ---------------------------------------------------------------------------

@dataclass
class _Unit:
    kind: str                        # table_row | prose_act | verbatim
    name_block: str | None
    regnum: str | None
    text: str
    section: str | None
    offset: int


def _looks_name(ln: str) -> bool:
    """A fund/entity name line: mostly uppercase, no sentence end."""
    if not ln or len(ln) < 3:
        return False
    if ln.endswith((".", ";", ":")):
        return False
    letters = [c for c in ln if c.isalpha()]
    if not letters:
        return False
    upper = sum(1 for c in letters if c.isupper() or not c.isalpha())
    return upper / len(letters) > 0.75


def _units(
        span: str,
        base_offset: int) -> tuple[list[_Unit], list[str]]:
    """Segment the FI span into table rows / prose acts / verbatim
    fragments. Headers update context only."""
    lines = span.splitlines()
    units: list[_Unit] = []
    sections_seen: list[str] = []
    pending_table: str | None = None
    name_acc: list[str] = []
    name_off = 0
    prose: list[str] | None = None
    prose_off = 0
    prose_name: str | None = None
    prose_regnum: str | None = None
    last_row: _Unit | None = None
    pos = 0

    def flush_orphan() -> None:
        nonlocal name_acc
        if name_acc:
            text = " ".join(name_acc).strip()
            if text:
                units.append(_Unit(
                    "verbatim", None, None, text, None, name_off))
            name_acc = []

    def flush_prose() -> None:
        nonlocal prose, prose_name, prose_regnum
        if prose:
            text = " ".join(prose).strip()
            units.append(_Unit(
                "prose_act", prose_name, prose_regnum, text,
                None, prose_off))
            prose = None
            prose_name = None
            prose_regnum = None

    i = 0
    while i < len(lines):
        ln = lines[i].strip()
        n = norm(ln)
        line_off = base_offset + pos
        pos += len(lines[i]) + 1
        i += 1
        if not ln:
            continue
        # wrapped headers: "… DE FOLLETOS \nINFORMATIVOS" — join lookahead
        nxt_join = ""
        if i < len(lines):
            nxt_join = norm(ln + " " + lines[i].strip())
        if n in KNOWN_HEADERS or nxt_join in KNOWN_HEADERS:
            if n not in KNOWN_HEADERS:
                pos += len(lines[i]) + 1
                i += 1                    # consume the second line too
                n = nxt_join
            if n not in sections_seen:
                sections_seen.append(n)
            if n in TABLE_HEADERS:
                pending_table = n
            flush_orphan()
            last_row = None
            continue
        if _HEADER_NOISE.match(ln) or _NO_DATA.match(ln):
            continue
        if _VERB_START.match(ln):
            flush_orphan()
            flush_prose()
            prose = [ln]
            prose_off = line_off
            if last_row is not None:
                # NAME\nNUM\n<verb> — the row is this act's subject header
                prose_name = last_row.name_block
                prose_regnum = last_row.regnum
                units.remove(last_row)
                last_row = None
            continue
        m = _REGNUM_LINE.match(ln)
        if m:
            if prose is not None:
                prose.append(ln)         # wrapped number inside prose
                continue
            text = (" ".join(name_acc) + " " + ln).strip()
            last_row = _Unit(
                "table_row", " ".join(name_acc).strip() or None,
                m.group(1), text, pending_table, name_off or line_off)
            units.append(last_row)
            name_acc = []
            continue
        if prose is not None:
            # possible next-unit name line? lookahead for a regnum line
            nxt = [lines[j].strip() for j in range(i, min(i + 3, len(lines)))]
            if _looks_name(ln) and any(
                    _REGNUM_LINE.match(x) for x in nxt if x):
                flush_prose()
                name_acc = [ln]
                name_off = line_off
                continue
            prose.append(ln)
            continue
        # default: accumulate name block
        name_acc.append(ln)
        if not name_acc or len(name_acc) == 1:
            name_off = line_off
        if len(name_acc) > _MAX_NAME_LINES:
            # interleave guard: drop oldest lines as verbatim fragment
            frag = " ".join(name_acc[:-_MAX_NAME_LINES // 2]).strip()
            if frag:
                units.append(_Unit("verbatim", None, None, frag,
                                   None, name_off))
            name_acc = name_acc[-_MAX_NAME_LINES // 2:]
            name_off = line_off
    flush_orphan()
    flush_prose()
    return units, sections_seen


def _regnums_of(text: str) -> tuple[str, ...]:
    return tuple(_REGNUM_TEXT.findall(text))


def _classify_section(unit: _Unit) -> str | None:
    """Content-derived section — pending table header wins for bare
    table rows; act verbs classify prose."""
    t = norm(unit.text)
    if unit.kind == "table_row":
        return unit.section or "UNKNOWN_TABLE"
    if re.search(r"FUSI|ABSORC|CANJE", t):
        return "FUSION DE FONDOS DE INVERSION"
    if re.search(r"DELEGACI|REVOCACI", t) and "GESTI" in t:
        return "ACUERDO DE DELEGACION REVOCACION DE LA GESTION DE ACTIVOS"
    if re.search(r"CAMBIO DE LA DENOMINACI|MODIFICACI.N DE LA "
                 r"DENOMINACI|MODIFICACI.N DE LA DENOMINACI", t):
        return "MODIFICACIONES EN REGLAMENTOS"
    if re.search(r"ACTUALIZACI.N DEL FOLLETO|MODIFICACI.N DEL "
                 r"REGLAMENTO|ELEMENTOS ESENCIALES", t):
        return "ACTUALIZACION DE ELEMENTOS ESENCIALES DE FOLLETOS "\
            "INFORMATIVOS"
    if re.search(r"DISOLUCI|LIQUIDACI", t):
        return "MODIFICACIONES EN REGLAMENTOS"
    if re.search(r"\bBAJA\b", t):
        return "BAJAS"
    if unit.kind == "table_row":
        return unit.section
    return "OTHER_REGISTRY_PROSE"


_FUND_SUFFIX = re.compile(
    r",\s*(FI COTIZADO|FIIF|FIM|FICC|FII|FIL|FI|FCR|SCR|SICAV)\b")

#: leading fragments of stacked/wrapped headers that leak into names
_HDR_FRAG = re.compile(
    r"(?i)^(ACTUALIZACI.N DE ELEMENTOS ESENCIALES DE FOLLETOS|"
    r"INFORMATIVOS|MODIFICACIONES EN REGLAMENTOS|BAJAS|"
    r"NUEVAS INSCRIPCIONES|FUSI.N DE FONDOS DE INVERSI.N|"
    r"ACUERDO DE DELEGACI.N/REVOCACI.N DE LA GESTI.N DE ACTIVOS|"
    r"VERIFICACI.N ADMISI.N A BOLSA)\b[\s.,]*")


def _clean_row_name(name: str | None) -> str | None:
    if not name:
        return None
    s = _HDR_FRAG.sub("", name.strip())
    m = _FUND_SUFFIX.search(s)
    if m:
        s = s[: m.end()].strip()
    return s.strip(" ,.-") or None


def _subject_of(unit: _Unit) -> tuple[str | None, str | None]:
    """(subject_name, subject_regnum) for a unit."""
    if unit.kind == "table_row":
        return _clean_row_name(unit.name_block), unit.regnum
    pairs = _name_regnums(unit.text)
    if unit.regnum:
        name = pairs[0][0] if pairs else unit.name_block
        return name, unit.regnum
    if pairs:
        return pairs[0][0], pairs[0][1]
    regs = _regnums_of(unit.text)
    if regs:
        return None, regs[0]
    return unit.name_block, None


def parse_registry_document(pdf_bytes: bytes) -> RegistryParse:
    """Full parse of one bulletin PDF into observation drafts."""
    txt, bounds = extract_pdf_text(pdf_bytes)
    n_pages = len(bounds)
    mw = re.search(
        r"[Dd]el?\s*(\d{2}/\d{2}/\d{4})\s*al\s*(\d{2}/\d{2}/\d{4})", txt)
    week_label = f"{mw.group(1)} al {mw.group(2)}" if mw else None
    fstart, fend, found = _fi_span(txt)
    span = txt[fstart:fend] if found else txt
    units, sections_seen = _units(span, fstart if found else 0)
    obs: list[ObservationDraft] = []
    for j, u in enumerate(units):
        section = _classify_section(u)
        if not _FI_EVIDENCE.search(u.text):
            # other CNMV registry namespaces (SICAV/FCR/gestoras/EAF) —
            # keep the observation, never emit FI assertions
            section = "OTHER_ENTITY_CONTEXT"
        sname, sreg = _subject_of(u)
        regs = _regnums_of(u.text)
        succ = _por_successors(u.text)
        if u.kind == "table_row":
            rep = "structured" if sreg and sname else \
                "partially_structured"
        elif u.kind == "prose_act":
            rep = ("partially_structured" if (regs or u.regnum)
                   else "verbatim_only")
        else:
            rep = "verbatim_only"
            if not regs and len(u.text) < 30:
                continue                 # noise fragment
        page = _page_of(bounds, u.offset)
        obs.append(ObservationDraft(
            source_section_raw=section,
            subject_name_raw=sname,
            subject_register_number_raw=sreg,
            regnums_in_text=regs if regs else (
                (u.regnum,) if u.regnum else ()),
            successor_regnums=succ,
            observation_text_verbatim=u.text[:4000],
            source_locator=(
                f"page={page}/section={norm(section or 'NONE')[:40]}"
                f"/unit={j}"),
            representation=rep))
    if not found:
        obs.append(ObservationDraft(
            source_section_raw="NO_FI_SECTION",
            subject_name_raw=None, subject_register_number_raw=None,
            regnums_in_text=(), successor_regnums=(),
            observation_text_verbatim=txt[:4000],
            source_locator="page=1/section=NO_FI_SECTION/unit=0",
            representation="verbatim_only"))
    return RegistryParse(
        n_pages=n_pages, week_label=week_label,
        fi_section_found=found,
        sections_seen=tuple(sections_seen),
        observations=tuple(obs))


# ---------------------------------------------------------------------------
# assertions from bulletin observations
# ---------------------------------------------------------------------------

_SECTION_ASSERTION = {
    "NUEVAS INSCRIPCIONES": ("REGISTRATION_RECORDED", "REGISTERED"),
    "BAJAS": ("DEREGISTRATION_RECORDED", "DEREGISTERED"),
    "FUSION DE FONDOS DE INVERSION": (
        "MERGER_REGISTRATION_RECORDED", "REGISTERED"),
    "MODIFICACIONES EN REGLAMENTOS": ("OTHER_REGISTRY_ACT", "REGISTERED"),
    "ACTUALIZACION DE ELEMENTOS ESENCIALES DE FOLLETOS INFORMATIVOS": (
        "OTHER_REGISTRY_ACT", "REGISTERED"),
    "ACUERDO DE DELEGACION REVOCACION DE LA GESTION DE ACTIVOS": (
        "OTHER_REGISTRY_ACT", "REGISTERED"),
    "OTHER_REGISTRY_PROSE": ("OTHER_REGISTRY_ACT", "REGISTERED"),
    "UNKNOWN_TABLE": ("UNKNOWN_REGISTRY_ASSERTION", "UNKNOWN_STAGE"),
}


def bulletin_assertions(
        obs: ObservationDraft
) -> list[tuple[str, str, str | None, str | None, str | None]]:
    """(assertion_type, stage, subject_regnum, object_regnum,
    object_name_raw) tuples. Subject/object are exact CNMV register
    numbers only; a name without regnum stays unresolved."""
    sec = obs.source_section_raw or ""
    if sec == "OTHER_ENTITY_CONTEXT":
        return []
    if obs.representation == "verbatim_only":
        return [("UNKNOWN_REGISTRY_ASSERTION", "UNKNOWN_STAGE",
                 r, None, None) for r in obs.regnums_in_text]
    atype, stage = _SECTION_ASSERTION.get(
        sec, ("UNKNOWN_REGISTRY_ASSERTION", "UNKNOWN_STAGE"))
    if atype == "MERGER_REGISTRATION_RECORDED":
        succ = list(obs.successor_regnums)
        absorbed = [r for r in obs.regnums_in_text if r not in succ]
        obj_reg = succ[0] if succ else None
        obj_name = None
        if obj_reg is None:
            hits = list(re.finditer(
                r",\s*por\s+([^,(]+)", obs.observation_text_verbatim))
            if hits:
                obj_name = hits[-1].group(1).strip()
        if not absorbed and obs.subject_register_number_raw \
                and obs.subject_register_number_raw != obj_reg:
            absorbed = [obs.subject_register_number_raw]
        if absorbed:
            return [(atype, stage, r, obj_reg, obj_name)
                    for r in absorbed]
        if obj_reg:
            return [(atype, stage, None, obj_reg, obj_name)]
        return []
    if obs.subject_register_number_raw:
        return [(atype, stage, obs.subject_register_number_raw,
                 None, None)]
    return [(atype, stage, r, None, None)
            for r in obs.regnums_in_text]
