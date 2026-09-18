"""Adversarial ZIP/XML validation (defence-in-depth, Aletheia-pattern)."""

from __future__ import annotations

import io
import zipfile

import pytest

from cnmv_iic.acquisition.client import validate_zip
from cnmv_iic.errors import ZipRejectedError
from tests.conftest import make_zip


def test_zip_bomb_ratio_rejected():
    payload = b"A" * (1024 * 1024)  # compresses >200x
    data = make_zip({"big.txt": payload})
    with pytest.raises(ZipRejectedError, match="ratio"):
        validate_zip(data)


def test_traversal_member_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../evil.xml", b"<x/>")
    with pytest.raises(ZipRejectedError, match="unsafe"):
        validate_zip(buf.getvalue())


def test_backslash_traversal_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("..\\evil.xml", b"<x/>")
    with pytest.raises(ZipRejectedError, match="unsafe"):
        validate_zip(buf.getvalue())


def test_too_many_entries_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(130):
            zf.writestr(f"f{i}.xml", b"<x/>")
    with pytest.raises(ZipRejectedError, match="entries"):
        validate_zip(buf.getvalue())


def test_corrupt_zip_rejected():
    with pytest.raises(ZipRejectedError):
        validate_zip(b"PK\x03\x04garbagegarbagegarbage")


def test_normal_zip_accepted():
    data = make_zip({"FONDCART_202512.xml": b"<x/>", "FONDCART.xsd": b"<x/>"})
    zf = validate_zip(data)
    assert len(zf.infolist()) == 2
