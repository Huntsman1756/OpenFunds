"""Hardened CNMV download client.

Downloads are treated as untrusted input. Defence set (pattern informed by
EidoAut/Aletheia's ``CnmvIicProvider``, MIT — see NOTICE.md):

- bounded redirects, handled manually
- response byte cap enforced while streaming
- content-type allowlist per payload role
- ZIP magic + HTML-lookalike rejection
- ZIP entry count / per-entry decompressed size / total size / ratio caps
- member name traversal rejection
- SHA-256 computed at rest, before anything parses

This module never writes to the repository; the caller supplies paths.
"""

from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from html import unescape as html_unescape

from cnmv_iic.acquisition.months import month_number
from cnmv_iic.errors import (
    AcquisitionError,
    PayloadRejectedError,
    ZipRejectedError,
)

CNMV_BASE = "https://www.cnmv.es"
INDEX_PAGE = CNMV_BASE + "/portal/Publicaciones/Descarga-Informacion-Individual.aspx"

MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_ZIP_ENTRIES = 128
MAX_ZIP_ENTRY_BYTES = 128 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 512 * 1024 * 1024
MAX_ZIP_RATIO = 200.0
MAX_INDEX_BYTES = 4 * 1024 * 1024

_LINK_RE = re.compile(
    rb'<a[^>]*href="(https://www\.cnmv\.es/webservices/verdocumento/ver\?e=[^"]+)"'
    rb'[^>]*title="([^"]+)"'
)
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


@dataclass(frozen=True)
class DownloadedPayload:
    url: str
    content_type: str | None
    data: bytes

    @property
    def sha256(self) -> str:
        return sha256(self.data).hexdigest()


class CnmvClient:
    """Minimal, polite, fail-closed CNMV client (stdlib only)."""

    def __init__(self, user_agent: str = "cnmv-iic/0.1 (+https://github.com/cnmv-iic)",
                 timeout: float = 60.0, request_delay: float = 1.5) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.request_delay = request_delay
        self._opener = urllib.request.build_opener(_BoundedRedirectHandler(MAX_REDIRECTS))

    def _get(self, url: str, *, max_bytes: int, accept: str) -> tuple[bytes, str | None]:
        if not url.startswith("https://www.cnmv.es/"):
            raise PayloadRejectedError(f"URL outside CNMV origin rejected: {url}")
        req = urllib.request.Request(  # noqa: S310 — origin allowlisted above
            url,
            headers={"User-Agent": self.user_agent, "Accept": accept},
        )
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                chunks: list[bytes] = []
                total = 0
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise PayloadRejectedError(
                            f"response exceeded byte cap ({max_bytes}): {url}"
                        )
                    chunks.append(chunk)
                return b"".join(chunks), resp.headers.get("Content-Type")
        except PayloadRejectedError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalize all transport failures
            raise AcquisitionError(f"GET failed for {url}: {exc}") from exc

    def list_months(self, year: int) -> dict[int, str]:
        """Return {month_number: download_url} for a publication year."""
        body, ctype = self._get(
            f"{INDEX_PAGE}?ejercicio={year}&lang=es",
            max_bytes=MAX_INDEX_BYTES,
            accept="text/html,application/xhtml+xml",
        )
        media = (ctype or "").split(";")[0].strip().lower()
        if media and media not in {"text/html", "application/xhtml+xml"}:
            raise PayloadRejectedError(f"index page Content-Type rejected: {ctype}")
        if not body[:512].lstrip().lower().startswith((b"<!doctype", b"<html", b"<")):
            raise PayloadRejectedError("index page is not HTML")
        out: dict[int, str] = {}
        for url_b, title_b in _LINK_RE.findall(body):
            month = month_number(html_unescape(title_b.decode("utf-8", "replace")))
            if month is not None:
                out[month] = url_b.decode("ascii")
        if not out:
            raise AcquisitionError(f"no download links found on index for {year}")
        return out

    def download_zip(self, url: str) -> DownloadedPayload:
        """Download a monthly artifact ZIP with structural validation."""
        data, ctype = self._get(
            url, max_bytes=MAX_RESPONSE_BYTES, accept="application/zip,application/octet-stream"
        )
        media = (ctype or "").split(";")[0].strip().lower()
        if media in {"text/html", "application/xhtml+xml"}:
            raise PayloadRejectedError("expected ZIP, got HTML")
        if media and media not in {
            "application/zip", "application/octet-stream",
            "application/x-zip-compressed", "binary/octet-stream",
        }:
            raise PayloadRejectedError(f"ZIP Content-Type rejected: {ctype}")
        if data[:4] not in _ZIP_MAGICS:
            head = data[:256].lstrip().lower()
            if head.startswith((b"<!doctype", b"<html")):
                raise ZipRejectedError("expected ZIP, got HTML document")
            raise ZipRejectedError("ZIP magic missing")
        validate_zip(data)
        return DownloadedPayload(url=url, content_type=ctype, data=data)


def validate_zip(data: bytes) -> zipfile.ZipFile:
    """Structural validation of an artifact ZIP (defence-in-depth).

    Returns an open ZipFile on success. Caller still validates member names
    and expected families.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ZipRejectedError(f"corrupt ZIP: {exc}") from exc
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ZipRejectedError(f"too many entries ({len(infos)} > {MAX_ZIP_ENTRIES})")
    total = 0
    for info in infos:
        name = info.filename.replace("\\", "/")
        if ".." in name.split("/") or name.startswith("/"):
            raise ZipRejectedError(f"unsafe member name: {info.filename!r}")
        total += info.file_size
        if info.file_size > MAX_ZIP_ENTRY_BYTES:
            raise ZipRejectedError(f"entry too large: {info.filename}")
        if total > MAX_ZIP_TOTAL_BYTES:
            raise ZipRejectedError("total decompressed size cap exceeded")
        if info.compress_size > 0 and info.file_size / info.compress_size > MAX_ZIP_RATIO:
            raise ZipRejectedError(f"compression-ratio cap exceeded: {info.filename}")
    return zf


class _BoundedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects: int) -> None:
        self._max = max_redirects
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        count = getattr(req, "_cnmv_redirects", 0) + 1
        if count > self._max:
            raise AcquisitionError(f"too many redirects fetching {req.full_url}")
        if not newurl.startswith("https://www.cnmv.es/"):
            raise AcquisitionError(f"redirect off CNMV origin rejected: {newurl}")
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new._cnmv_redirects = count
        return new
