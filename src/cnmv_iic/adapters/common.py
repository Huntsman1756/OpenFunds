"""Shared secure-XML helpers for source adapters."""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from lxml import etree

from cnmv_iic.errors import ParseError, UnsupportedSchemaError


def secure_parse(xml: bytes, family: str) -> etree._Element:
    """Parse untrusted XML with all DTD/entity processing disabled."""
    head = xml[:2048].lstrip()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ParseError(f"{family}: DOCTYPE/ENTITY declarations rejected")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        recover=False,
        huge_tree=False,
    )
    try:
        return etree.parse(io.BytesIO(xml), parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"{family}: XML syntax error: {exc}") from exc


def text_of(el: etree._Element, tag: str) -> str | None:
    """Stripped text of a child element; None if absent or empty."""
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    v = child.text.strip()
    return v or None


def required_text(el: etree._Element, tag: str, family: str,
                  locator: str) -> str:
    if el.find(tag) is None:
        raise UnsupportedSchemaError(
            f"{family}: required element {tag} absent at {locator}"
        )
    v = text_of(el, tag)
    if v is None:
        raise ParseError(f"{family}: empty {tag} at {locator}")
    return v


def required_decimal(el: etree._Element, tag: str, family: str,
                     locator: str) -> Decimal:
    raw = required_text(el, tag, family, locator)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(
            f"{family}: non-decimal {tag}={raw!r} at {locator}"
        ) from exc


def parse_period(root: etree._Element, family: str) -> str:
    """FechaDatos 'YYYYMM' -> 'YYYY-MM'."""
    raw = text_of(root, "FechaDatos")
    if raw is None or len(raw) != 6 or not raw.isdigit():
        raise ParseError(f"{family}: bad FechaDatos {raw!r}")
    month = int(raw[4:6])
    if not 1 <= month <= 12:
        raise ParseError(f"{family}: bad FechaDatos month {raw!r}")
    return f"{raw[:4]}-{raw[4:6]}"
