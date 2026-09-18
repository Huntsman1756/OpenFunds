"""Localized month-name resolution for CNMV index rows.

The listing page is served in the requested language; observed deployments
use Spanish month names in the link ``title`` attribute, but the site is
also localized to Catalan, Galician, Basque and English. Mapping pattern
informed by EidoAut/Aletheia (MIT) — see NOTICE.md.
"""

from __future__ import annotations

import unicodedata

_MONTH_NAMES: tuple[tuple[str, ...], ...] = (
    ("enero", "january", "gener", "xaneiro", "urtarrila"),
    ("febrero", "february", "febrer", "febreiro", "otsaila"),
    ("marzo", "march", "marc", "marz", "martxoa"),
    ("abril", "april", "apirila"),
    ("mayo", "may", "maig", "maio", "maiatza"),
    ("junio", "june", "juny", "xuno", "ekaina"),
    ("julio", "july", "juliol", "xullo", "uztaila"),
    ("agosto", "august", "agost", "abuztua"),
    ("septiembre", "september", "setiembre", "setembre", "setembro", "iraila"),
    ("octubre", "october", "outubro", "urria"),
    ("noviembre", "november", "novembre", "azaroa"),
    ("diciembre", "december", "desembre", "decembro", "abendua"),
)

_MONTHS: dict[str, int] = {
    name: num for num, names in enumerate(_MONTH_NAMES, start=1) for name in names
}


def month_number(label: str) -> int | None:
    """Resolve a localized month label to 1..12, or None if unrecognised."""
    decomposed = unicodedata.normalize("NFKD", label.strip().lower())
    letters = "".join(c for c in decomposed if c.isalpha())
    return _MONTHS.get(letters)
