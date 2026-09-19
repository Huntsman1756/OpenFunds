"""G9-B — CNMV relevant-information (HR) acquisition client.

Measured mechanics (docs/g9/coverage-probe.md):

- ``GET /Portal/hr/busquedahr?division=2`` -> ASP.NET form state;
  ``POST`` with ``txtDenominacion=<name>`` + optional
  ``fecha_desde/fecha_hasta`` (dd/mm/yyyy) + ``btnOk=Buscar``.
- Single-entity result redirects to ``ResultadoBusquedaHR?nif=<NIF>``;
  ambiguous results render an entity list carrying ``?nif=`` links.
- Events per page: ``liFechaRegistro`` / ``liHora`` / category /
  summary prose + ``verdocumento`` links + the event's own
  ``Número de registro: N`` — which is the HR EVENT register number,
  never the fund's CNMV register number.
- Pagination via ``&page=N`` on the result URL.
- Entity header (``tituloDatos``) may carry terminal markers such as
  ``baja dd.mm.yy``.

Discovery by denomination only — identity corroboration is the
caller's job (exact fund register number in event prose).
"""

from __future__ import annotations

import http.cookiejar
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from cnmv_iic.errors import CnmvIicError

SEARCH_URL = "https://www.cnmv.es/Portal/hr/busquedahr?division=2"
_ALLOWED = ("https://www.cnmv.es", "http://www.cnmv.es")
_UA = {"User-Agent": "cnmv-iic/0.1 (open data, reproducible research)"}
_MAX_REDIRECTS = 6

_FIELD_RE = 'name="{name}"[^>]*value="([^"]*)"'
_FORM_FIELDS = ("__EVENTTARGET", "__EVENTARGUMENT", "__VIEWSTATE",
                "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


class HrError(CnmvIicError):
    """HR surface failures (network, origin, malformed response)."""


@dataclass(frozen=True)
class HrSearchResult:
    """Raw evidence of one denominacion search."""
    final_url: str
    raw_html: str
    nif: str | None                # resolved NIF iff unambiguous
    nif_candidates: tuple[str, ...]
    no_results: bool


@dataclass(frozen=True)
class HrPage:
    url: str
    raw_html: str


def _field(name: str, body: str) -> str:
    m = re.search(_FIELD_RE.format(name=re.escape(name)), body)
    return m.group(1) if m else ""


def _check_origin(url: str) -> None:
    if not url.startswith(_ALLOWED):
        raise HrError(f"response left expected CNMV origin: {url}")


class HrClient:
    """Stateful (cookie-jar) HR client with bounded polite pacing."""

    def __init__(self, *, request_delay: float = 0.55,
                 timeout: float = 25.0,
                 opener: urllib.request.OpenerDirector | None = None
                 ) -> None:
        self.request_delay = request_delay
        self.timeout = timeout
        if opener is None:
            cj = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
        self._op = opener

    def _open(self, url: str,
              data: bytes | None = None) -> tuple[str, bytes]:
        req = urllib.request.Request(  # noqa: S310 — allowlisted above
            url, data=data, headers=dict(_UA))
        try:
            resp = self._op.open(req, timeout=self.timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise HrError(f"HR request failed for {url}: {exc}") from exc
        final = resp.geturl()
        _check_origin(final)
        return final, resp.read()

    def search_entity(self, denominacion: str, *,
                      desde: str = "",
                      hasta: str = "") -> HrSearchResult:
        """POST the search form; dates are dd/mm/yyyy strings."""
        url, body = self._open(SEARCH_URL)
        data = {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$wBusqueda$txtBusqueda": "",
            "ctl00$ContentPrincipal$wNombreEntidad$txtDenominacion":
                denominacion,
            "ctl00$ContentPrincipal$wFechas$fecha_desde": desde,
            "ctl00$ContentPrincipal$wFechas$fecha_hasta": hasta,
            "ctl00$ContentPrincipal$wFechas$ult_dias": "",
            "ctl00$ContentPrincipal$btnOk": "Buscar",
        }
        for f in _FORM_FIELDS:
            data[f] = _field(f, body.decode("utf-8", "replace"))
        final, raw = self._open(
            SEARCH_URL, urllib.parse.urlencode(data).encode())
        html = raw.decode("utf-8", "replace")
        nifs = sorted(set(re.findall(r"[?&]nif=([A-Z0-9-]+)", html)))
        m_nif = re.search(r"[?&]nif=([A-Z0-9-]+)", final)
        nif = m_nif.group(1) if m_nif else (
            nifs[0] if len(nifs) == 1 else None)
        return HrSearchResult(
            final_url=final, raw_html=html, nif=nif,
            nif_candidates=tuple(nifs),
            no_results="No se han encontrado" in html)

    def fetch_result_page(self, result_url: str) -> HrPage:
        """GET a result page (incl. &page=N pagination)."""
        _check_origin(result_url)
        final, raw = self._open(result_url)
        return HrPage(url=final, raw_html=raw.decode("utf-8", "replace"))


@dataclass(frozen=True)
class HrEventDraft:
    """One hecho relevante row — parser-level fields only."""
    date: str                       # dd/mm/yyyy verbatim
    time: str                       # hh:mm verbatim
    category: str
    summary: str
    doc_url: str | None
    hr_event_reg_number: str | None  # event register number — NOT fund


_EVENT_RE = re.compile(
    r"liFechaRegistro[^>]*>\s*([^<]+).*?liHora[^>]*>\s*([^<]+).*?"
    r"descripcionSubtituloCabecera[^>]*>([^<]+).*?"
    r"liSubtituloRegistro[^>]*>(.*?)</li>(.{0,900}?)"
    r"(?=liFechaRegistro|</ul>\s*</li>|$)", re.S)
_REGNO_RE = re.compile(r"N.mero de registro:\s*(\d+)")
_ENTITY_HDR_RE = re.compile(r"tituloDatos[^>]*>(.*?)</p>", re.S)
_PAGE_RE = re.compile(
    r"resultadobusquedahr\.aspx\?[^\"']*page=(\d+)", re.I)


def parse_event_entries(html: str) -> list[HrEventDraft]:
    """HR event rows from a ResultadoBusquedaHR page (verbatim)."""
    out: list[HrEventDraft] = []
    for m in _EVENT_RE.finditer(html):
        f, h, cat, summ_html, tail = m.groups()
        doc = re.search(r'href="([^"]*verdocumento[^"]*)"', summ_html)
        regno = _REGNO_RE.search(tail + summ_html)
        txt = re.sub(r"<[^>]+>", " ", summ_html)
        txt = re.sub(r"\s+", " ", txt).strip()
        out.append(HrEventDraft(
            date=f.strip(), time=h.strip(), category=cat.strip(),
            summary=txt[:2000],
            doc_url=doc.group(1) if doc else None,
            hr_event_reg_number=regno.group(1) if regno else None))
    return out


def parse_entity_header(html: str) -> str | None:
    """Entity header text — may carry 'baja dd.mm.yy' markers."""
    m = _ENTITY_HDR_RE.search(html)
    if not m:
        return None
    return re.sub(r"<[^>]+>", " ", m.group(1)).strip() or None


def result_pages(html: str) -> tuple[int, ...]:
    """Pagination page numbers linked from a result page."""
    return tuple(sorted({int(x) for x in _PAGE_RE.findall(html)}))
