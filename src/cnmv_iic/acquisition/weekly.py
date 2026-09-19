"""Hardened client for the CNMV weekly registry bulletin surface.

Mechanics (measured, docs/g9/coverage-probe.md):

- Week enumeration: ASP.NET ``<select name="ctl00$ContentPrincipal$
  ddlFechas">`` on ``internet.cnmv.es`` — ~1,100 weekly options,
  2004 -> present.
- Selection requires a POST containing BOTH ``ddlFechas=<week_id>``
  AND ``btnFechas=Buscar``; changing the dropdown alone returns the
  current week (verified failure mode).
- Each selected week exposes per-document links
  ``ctl00_ContentPrincipal_lnk<Role>`` pointing at opaque
  ``www.cnmv.es/webservices/verdocumento/ver?e=<token>`` URLs.
  ``lnkRegistro`` is the registry-acts document; when absent the
  ``lnkBoletinCompleto`` full bulletin carries the same section
  (fallback, e.g. week 7169).

Defence set mirrors ``acquisition.client``: origin allowlist,
bounded redirects, byte caps, payload-type checks, retries with
backoff. Never writes to the repository; the caller supplies paths.
"""

from __future__ import annotations

import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from http.cookiejar import CookieJar

from cnmv_iic.errors import AcquisitionError, PayloadRejectedError

WEEKLY_PAGE = (
    "https://internet.cnmv.es/portal/publicaciones/cnmvinforma?lang=es"
)
ALLOWED_ORIGINS = ("https://internet.cnmv.es/", "https://www.cnmv.es/")
MAX_PAGE_BYTES = 8 * 1024 * 1024
MAX_DOC_BYTES = 96 * 1024 * 1024
MAX_ATTEMPTS = 3

_WEEK_OPTION_RE = re.compile(
    r'<option value="([^"]*)"[^>]*>(\d{2}/\d{2}/\d{4}) al '
    r"(\d{2}/\d{2}/\d{4})</option>"
)
_LINK_RE = re.compile(
    r'id="ctl00_ContentPrincipal_(lnk[A-Za-z]+)"[^>]*href="([^"]*)"'
)
_SELECTED_RE = re.compile(r"seleccionado \(([^)]*)\)")
_PDF_MAGIC = b"%PDF"

_ROLE_ALIASES = {
    "boletincompleto": "boletin_completo",
    "registro": "registro",
    "emisiones": "emisiones",
    "hechos": "hechos",
    "opas": "opas",
}


def _field(name: str, body: str) -> str:
    m = re.search(rf'name="{re.escape(name)}"[^>]*value="([^"]*)"', body)
    return m.group(1) if m else ""


def _es_date(s: str) -> date:
    dd, mm, yy = s.split("/")
    return date(int(yy), int(mm), int(dd))


@dataclass(frozen=True)
class WeekOption:
    week_id: str
    start: date
    end: date
    label: str                     # "dd/mm/yyyy al dd/mm/yyyy"


@dataclass(frozen=True)
class WeekSelection:
    week_id: str
    selected_label: str | None
    links: dict[str, str]          # role -> absolute document URL
    raw_html: str = ""             # POST response — kept for gap evidence


@dataclass(frozen=True)
class DownloadedPayload:
    url: str
    content_type: str | None
    data: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.data).hexdigest()


class WeeklyBulletinClient:
    """Stateful ASP.NET client for the weekly bulletin surface.

    Holds a cookie jar + cached view-state. ``week_options`` performs a
    fresh GET (which also refreshes the view-state used by subsequent
    ``select_week`` POSTs).
    """

    def __init__(
        self,
        user_agent: str = "cnmv-iic/0.1 (+https://github.com/cnmv-iic)",
        timeout: float = 60.0,
        request_delay: float = 1.5,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.request_delay = request_delay
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()),
            _BoundedRedirectHandler(5),
        )
        self._viewstate: dict[str, str] = {}

    # -- transport ----------------------------------------------------

    def _check_origin(self, url: str) -> None:
        if not url.startswith(ALLOWED_ORIGINS):
            raise PayloadRejectedError(
                f"URL outside CNMV origins rejected: {url}")

    def _open(
        self, url: str, data: bytes | None, *, max_bytes: int
    ) -> tuple[str, bytes, str | None]:
        self._check_origin(url)
        req = urllib.request.Request(  # noqa: S310 — allowlisted above
            url, data=data,
            headers={"User-Agent": self.user_agent},
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                final_url = resp.geturl()
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise PayloadRejectedError(
                            f"response exceeded byte cap ({max_bytes}): "
                            f"{url}")
                    chunks.append(chunk)
                ctype = resp.headers.get("Content-Type")
            return final_url, b"".join(chunks), ctype
        except PayloadRejectedError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize transport failures
            raise AcquisitionError(f"request failed for {url}: {exc}") \
                from exc

    def _get_html(self, url: str) -> tuple[str, str]:
        final, body, ctype = self._open(
            url, None, max_bytes=MAX_PAGE_BYTES)
        media = (ctype or "").split(";")[0].strip().lower()
        if media and media not in {"text/html", "application/xhtml+xml"}:
            raise PayloadRejectedError(
                f"HTML page Content-Type rejected: {ctype}")
        return final, body.decode("utf-8", "replace")

    # -- surface ------------------------------------------------------

    def week_options(self) -> list[WeekOption]:
        """Fresh GET of the weekly page; returns all selectable weeks
        (oldest -> newest as ordered by the page) and caches the
        view-state required by ``select_week``."""
        _, body = self._get_html(WEEKLY_PAGE)
        self._viewstate = {
            n: _field(n, body)
            for n in ("__VIEWSTATE", "__VIEWSTATEGENERATOR",
                      "__EVENTVALIDATION")
        }
        out = []
        for week_id, a, b in _WEEK_OPTION_RE.findall(body):
            out.append(WeekOption(
                week_id=week_id, start=_es_date(a), end=_es_date(b),
                label=f"{a} al {b}"))
        if not out:
            raise AcquisitionError("no weekly options found on page")
        return out

    def select_week(self, week_id: str) -> WeekSelection:
        """POST the week selector + Buscar; returns the document links
        exposed for that week."""
        last_err: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                data = {
                    "__EVENTTARGET": "", "__EVENTARGUMENT": "",
                    "__VIEWSTATE": self._viewstate.get("__VIEWSTATE", ""),
                    "__VIEWSTATEGENERATOR": self._viewstate.get(
                        "__VIEWSTATEGENERATOR", ""),
                    "__EVENTVALIDATION": self._viewstate.get(
                        "__EVENTVALIDATION", ""),
                    "ctl00$ContentPrincipal$ddlFechas": week_id,
                    "ctl00$ContentPrincipal$btnFechas": "Buscar",
                    "ctl00$UcBuscar$txtBuscar": "",
                    "ctl00$CultureSelector$ddlCultura": "es",
                }
                _, body = self._get_post(WEEKLY_PAGE, data)
                sel = _SELECTED_RE.search(body)
                links = {
                    _ROLE_ALIASES.get(
                        link_id.removeprefix("lnk").lower(),
                        link_id.removeprefix("lnk").lower()):
                    urllib.parse.urljoin(WEEKLY_PAGE, href)
                    for link_id, href in _LINK_RE.findall(body)
                }
                return WeekSelection(
                    week_id=week_id,
                    selected_label=sel.group(1) if sel else None,
                    links=links,
                    raw_html=body)
            except AcquisitionError as exc:
                last_err = exc
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(2 * (attempt + 1))
                self.week_options()  # refresh view-state
        raise AcquisitionError(  # pragma: no cover — defensive
            f"select_week failed: {last_err}")

    def _get_post(self, url: str, data: dict[str, str]) -> tuple[str, str]:
        encoded = urllib.parse.urlencode(data).encode()
        final, body, ctype = self._open(
            url, encoded, max_bytes=MAX_PAGE_BYTES)
        media = (ctype or "").split(";")[0].strip().lower()
        if media and media not in {"text/html", "application/xhtml+xml"}:
            raise PayloadRejectedError(
                f"HTML page Content-Type rejected: {ctype}")
        return final, body.decode("utf-8", "replace")

    def fetch_document(self, url: str) -> DownloadedPayload:
        """Download a bulletin PDF with structural validation."""
        last_err: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                _, data, ctype = self._open(
                    url, None, max_bytes=MAX_DOC_BYTES)
                media = (ctype or "").split(";")[0].strip().lower()
                if media in {"text/html", "application/xhtml+xml"}:
                    raise PayloadRejectedError("expected PDF, got HTML")
                if media and media not in {
                    "application/pdf", "application/octet-stream",
                    "binary/octet-stream",
                }:
                    raise PayloadRejectedError(
                        f"document Content-Type rejected: {ctype}")
                if not data.startswith(_PDF_MAGIC):
                    raise PayloadRejectedError("PDF magic missing")
                return DownloadedPayload(
                    url=url, content_type=ctype, data=data)
            except AcquisitionError as exc:
                last_err = exc
                if attempt == MAX_ATTEMPTS - 1:
                    raise
                time.sleep(2 * (attempt + 1))
        raise AcquisitionError(  # pragma: no cover — defensive
            f"fetch_document failed: {last_err}")


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int) -> None:
        self._max = max_redirects
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        count = getattr(req, "_cnmv_redirects", 0) + 1
        if count > self._max:
            raise AcquisitionError(
                f"too many redirects fetching {req.full_url}")
        if not newurl.startswith(ALLOWED_ORIGINS):
            raise AcquisitionError(
                f"redirect off CNMV origins rejected: {newurl}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new._cnmv_redirects = count
        return new
