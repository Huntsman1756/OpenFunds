"""Minimal canonical domain model (G1).

Rules (docs/architecture/principles.md):
- Monetary values are Decimal, never float.
- OBSERVED (source-verbatim) and DERIVED values are separate fields.
- Identity is fail-closed: real CNMV keys only. Masked/absent/malformed
  identifiers are preserved explicitly, never synthesized.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Literal

_ISIN_FORMAT = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")
MASKED_ISIN = "X" * 12


class IsinState(StrEnum):
    VALID = "valid"            # ISO 6166 format + check digit verified
    INVALID = "invalid"        # element present but malformed/failed check
    MASKED = "masked"          # literal 'XXXXXXXXXXXX' (CNMV-masked)
    ABSENT = "absent"          # element missing or empty


class PositionKind(StrEnum):
    SECURITY = "security"
    CASH = "cash"              # DescripcionIF == 'Depositos' only


def isin_checkdigit(isin: str) -> bool:
    """ISO 6166 mod-10 check digit (Luhn; check digit at right offset 0)."""
    digits = "".join(str(ord(c) - 55) if c.isalpha() else c for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def classify_isin(raw: str | None) -> IsinState:
    if raw is None or not raw.strip():
        return IsinState.ABSENT
    v = raw.strip()
    if v == MASKED_ISIN:
        return IsinState.MASKED
    if not _ISIN_FORMAT.fullmatch(v):
        return IsinState.INVALID
    return IsinState.VALID if isin_checkdigit(v) else IsinState.INVALID


@dataclass(frozen=True)
class FundIdentity:
    """CNMV composite key — Tipo + NumeroRegistro + NumeroCompartimento."""

    entity_type: str            # FI | FHF | ... (verbatim)
    numero_registro: str
    numero_compartimento: str

    @property
    def key(self) -> str:
        return f"{self.entity_type}:{self.numero_registro}:{self.numero_compartimento}"


@dataclass(frozen=True)
class Provenance:
    source_artifact_id: str
    source_sha256: str
    member_name: str
    member_sha256: str
    xml_locator: str
    parser: str                 # e.g. "cnmv_iic.adapters.fondcart"
    parser_version: str


@dataclass(frozen=True)
class Position:
    """One reported portfolio position. All source fields verbatim."""

    kind: PositionKind
    clase_if: str               # INTERIOR | EXTERIOR | DUDOSAS (verbatim)
    descripcion_if: str         # asset-class label (verbatim)
    descripcion_valor: str | None  # TIPO|ISSUER|COUPON|MATURITY (verbatim, never parsed)
    divisa: str | None
    reported_market_value: Decimal | None
    isin_raw: str | None
    isin_state: IsinState
    provenance: Provenance
    derived_weight: Decimal | None = None   # = market_value / snapshot total


@dataclass(frozen=True)
class QualityObservation:
    """Reconciliation of position sum vs FONDPATRIMDISVAR declared totals."""

    metric: str                 # "fondcart_vs_patrimdisvar"
    cart_sum: Decimal
    pdv_sum: Decimal
    abs_diff: Decimal
    rel_diff: Decimal | None    # None when pdv_sum == 0
    tolerance: Decimal
    state: Literal["exact", "within_tolerance", "divergent", "unreconcilable"]
    note: str | None = None


@dataclass(frozen=True)
class PortfolioSnapshot:
    identity: FundIdentity
    period: str                 # "YYYY-MM" (from FechaDatos)
    positions: tuple[Position, ...]
    quality: tuple[QualityObservation, ...] = field(default_factory=tuple)

    @property
    def reported_total(self) -> Decimal:
        return sum(
            (p.reported_market_value for p in self.positions
             if p.reported_market_value is not None),
            Decimal(0),
        )
