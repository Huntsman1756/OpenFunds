"""Localized month-label resolution."""

from cnmv_iic.acquisition.months import month_number


def test_spanish_months():
    assert month_number("enero") == 1
    assert month_number("marzo") == 3
    assert month_number("diciembre") == 12


def test_variants_and_locales():
    assert month_number("septiembre") == 9
    assert month_number("setiembre") == 9
    assert month_number("December 2025") == 12
    assert month_number("Desembre") == 12      # Catalan
    assert month_number("Decembro") == 12      # Galician
    assert month_number("Abendua") == 12       # Basque


def test_case_and_whitespace():
    assert month_number("  JUNIO  ") == 6
    assert month_number("Noviembre 2025") == 11


def test_unknown_returns_none():
    assert month_number("notamonth") is None
    assert month_number("") is None
