#!/usr/bin/env python3
"""G0 viability probe — CNMV 'descarga de información individual de IIC'.

Reproduces the evidence in docs/g0/results.md:
  A  acquisition   — scrape ejercicio index, download tokenized ZIPs, hash
  B  schema        — XSD SHA-256 fingerprints + lxml instance validation
  D  portfolio     — FONDCART position extraction stats (ISIN coverage etc.)
  E  reconciliation— sum(ValorMercado) vs FONDPATRIMDISVAR aggregates
  I  provenance    — manifest JSON with artifact/member hashes

Stdlib-only core; lxml used for XSD validation when available.
Never writes outside --outdir. Polite: ~1.5 s between downloads.

Usage:  python tools/g0_probe.py --outdir .research/cnmv --years 2012 2025
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from xml.etree import ElementTree as ET

try:
    from lxml import etree  # type: ignore
except ImportError:  # pragma: no cover
    etree = None

BASE = "https://www.cnmv.es"
PAGE = BASE + "/portal/Publicaciones/Descarga-Informacion-Individual.aspx"
UA = {"User-Agent": "cnmv-iic-g0-probe/0.1 (research; reproducible data check)"}
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
LINK_RE = re.compile(
    r'<a[^>]*href="(https://www\.cnmv\.es/webservices/verdocumento/ver\?e=[^"]+)"'
    r'[^>]*title="([^"]+)"'
)
ISIN_RE = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
MAX_BYTES = 64 * 1024 * 1024          # hard response cap
MAX_ZIP_ENTRIES = 128
MAX_ENTRY_BYTES = 128 * 1024 * 1024
MAX_RATIO = 200.0


def fetch(url: str) -> tuple[bytes, str | None]:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:  # redirects bounded by urllib (default ~10)
        data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("response exceeded byte cap")
        return data, r.headers.get("Content-Type")


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def list_months(year: int) -> dict[int, str]:
    html, _ = fetch(f"{PAGE}?ejercicio={year}&lang=es")
    out = {}
    for url, title in LINK_RE.findall(html.decode("utf-8", "replace")):
        m = MONTHS.get(title.strip().lower())
        if m:
            out[m] = url
    return out


@dataclass
class Member:
    name: str
    size: int
    sha256: str


@dataclass
class Artifact:
    period: str
    url: str
    retrieved_at: str
    content_type: str | None
    size_bytes: int
    sha256: str
    members: list[Member] = field(default_factory=list)
    xsd_sha256: dict[str, str] = field(default_factory=dict)


def inspect_zip(period: str, url: str, retrieved_at: str,
                data: bytes, ctype: str | None) -> Artifact:
    if not data[:2] == b"PK":
        raise ValueError("not a ZIP (magic missing)")
    zf = zipfile.ZipFile(io.BytesIO(data))
    if len(zf.infolist()) > MAX_ZIP_ENTRIES:
        raise ValueError("too many zip entries")
    art = Artifact(period, url, retrieved_at, ctype, len(data), sha256(data))
    total = 0
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if "/" in name or ".." in name:
            raise ValueError(f"unsafe zip member name: {name}")
        total += info.file_size
        if info.file_size > MAX_ENTRY_BYTES or total > 4 * MAX_ENTRY_BYTES:
            raise ValueError("decompressed size cap exceeded")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO:
            raise ValueError(f"compression-ratio cap exceeded: {name}")
        content = zf.read(info)
        art.members.append(Member(info.filename, info.file_size, sha256(content)))
        if name.lower().endswith(".xsd"):
            fam = name.split("/")[-1].split(".")[0].split("_")[0].upper()
            art.xsd_sha256[fam] = sha256(content)
    return art


def fondcart_stats(xml: bytes) -> dict:
    root = ET.parse(io.BytesIO(xml)).getroot()
    n_ent = n_pos = n_isin = n_masked = n_absent = 0
    for e in root.findall("Entidad"):
        n_ent += 1
        for c in e.findall("Compartimento"):
            for inv in c.findall("InversionesFinancieras"):
                n_pos += 1
                el = inv.find("CodigoISIN")
                if el is None:
                    n_absent += 1
                elif (el.text or "").strip() == "X" * 12:
                    n_masked += 1
                elif ISIN_RE.fullmatch((el.text or "").strip()):
                    n_isin += 1
    return {"entidad_elements": n_ent, "positions": n_pos,
            "isin_valid_format": n_isin, "isin_masked": n_masked,
            "isin_absent": n_absent}


def reconcile(cart_xml: bytes, pdv_xml: bytes) -> dict:
    def num(el, tag):
        v = el.findtext(tag)
        return Decimal(v) if v else Decimal(0)

    def sums(xml, is_cart):
        root = ET.parse(io.BytesIO(xml)).getroot()
        out = {}
        for e in root.findall("Entidad"):
            key = (e.findtext("Tipo"), e.findtext("NumeroRegistro"))
            for c in e.findall("Compartimento"):
                if is_cart:
                    v = sum(Decimal(i.findtext("ValorMercado"))
                            for i in c.findall("InversionesFinancieras"))
                    out[key] = out.get(key, Decimal(0)) + v
                else:
                    v = (num(c, "CarteraInterior") + num(c, "CarteraExterior")
                         + num(c, "InversionesDudosas"))
                    out[key] = out.get(key, Decimal(0)) + v
        return out

    cart, pdv = sums(cart_xml, True), sums(pdv_xml, False)
    common = set(cart) & set(pdv)
    exact = within_01pct = divergent = 0
    max_diff = Decimal(0)
    for k in common:
        diff = abs(cart[k] - pdv[k])
        max_diff = max(max_diff, diff)
        if diff == 0:
            exact += 1
        elif pdv[k] and diff / abs(pdv[k]) < Decimal("0.001"):
            within_01pct += 1
        else:
            divergent += 1
    return {"entities": len(common), "exact": exact,
            "within_0.1pct": within_01pct, "divergent": divergent,
            "max_abs_diff": str(max_diff)}


def validate(fam: str, xsd: bytes, xml: bytes) -> dict:
    if etree is None:
        return {"family": fam, "validation": "skipped-no-lxml"}
    schema = etree.XMLSchema(etree.fromstring(xsd))
    ok = schema.validate(etree.parse(io.BytesIO(xml)))
    return {"family": fam, "xsd_valid": ok,
            "n_errors": len(schema.error_log),
            "first_error": str(schema.error_log[0]) if not ok else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--years", nargs="+", type=int, default=[2025])
    ap.add_argument("--months", nargs="+", type=int, default=[3, 6])
    args = ap.parse_args()

    import os
    from datetime import datetime, timezone
    os.makedirs(f"{args.outdir}/zips", exist_ok=True)
    report = {"ran_at": datetime.now(timezone.utc).isoformat(),
              "artifacts": [], "fondcart": {}, "reconciliation": {},
              "validation": []}

    for year in args.years:
        index = list_months(year)
        print(f"{year}: months available {sorted(index)}")
        for month in args.months:
            url = index.get(month)
            if not url:
                continue
            ts = datetime.now(timezone.utc).isoformat()
            data, ctype = fetch(url)
            art = inspect_zip(f"{year}-{month:02d}", url, ts, data, ctype)
            with open(f"{args.outdir}/zips/cnmv_{year}{month:02d}.zip", "wb") as f:
                f.write(data)
            report["artifacts"].append(asdict(art))
            print(f"  {art.period}: {art.size_bytes:,}B "
                  f"sha={art.sha256[:12]} members={len(art.members)}")

            zf = zipfile.ZipFile(io.BytesIO(data))
            cart = next((n for n in zf.namelist()
                         if n.upper().startswith("FONDCART")
                         and n.lower().endswith(".xml")), None)
            pdv = next((n for n in zf.namelist()
                        if n.upper().startswith("FONDPATRIMDISVAR")
                        and n.lower().endswith(".xml")), None)
            if cart:
                report["fondcart"][art.period] = fondcart_stats(zf.read(cart))
                print("    FONDCART:", report["fondcart"][art.period])
            if cart and pdv:
                report["reconciliation"][art.period] = reconcile(
                    zf.read(cart), zf.read(pdv))
                print("    reconcile:", report["reconciliation"][art.period])
            for n in zf.namelist():
                if n.lower().endswith(".xsd"):
                    fam = n.split(".")[0].split("_")[0].upper()
                    xml = next((m for m in zf.namelist() if m.upper()
                                .startswith(fam) and m.lower()
                                .endswith(".xml")), None)
                    if xml:
                        report["validation"].append(
                            {"period": art.period,
                             **validate(fam, zf.read(n), zf.read(xml))})
            time.sleep(1.5)

    with open(f"{args.outdir}/g0_report.json", "w") as f:
        json.dump(report, f, indent=1, default=str)
    print(f"report -> {args.outdir}/g0_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
