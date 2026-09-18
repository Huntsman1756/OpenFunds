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


# ---------------------------------------------------------------------------
# G2 — regulatory identity (FONDREGISTRO)
# ---------------------------------------------------------------------------


def fund_key(entity_type: str, numero_registro: str) -> str:
    return f"{entity_type}:{numero_registro}"


def compartment_key(entity_type: str, numero_registro: str,
                    numero_compartimento: str) -> str:
    return f"{entity_type}:{numero_registro}:{numero_compartimento}"


def share_class_key(entity_type: str, numero_registro: str,
                    numero_compartimento: str, numero_clase: str) -> str:
    return f"{entity_type}:{numero_registro}:{numero_compartimento}:{numero_clase}"


@dataclass(frozen=True)
class Institution:
    """Gestora or Depositario as recorded on a fund (registry-scoped)."""

    numero_registro: str | None
    denominacion: str | None
    tipo: str | None = None              # gestora only (e.g. 'SGIIC')
    grupo_numero: str | None = None
    grupo_denominacion: str | None = None


@dataclass(frozen=True)
class ShareClass:
    numero_clase: str
    isin_raw: str | None
    isin_state: IsinState
    denominacion: str | None

    def key(self, entity_type: str, numero_registro: str,
            numero_compartimento: str) -> str:
        return share_class_key(
            entity_type, numero_registro, numero_compartimento,
            self.numero_clase,
        )


@dataclass(frozen=True)
class Compartment:
    numero_compartimento: str
    denominacion: str | None
    classes: tuple[ShareClass, ...]


@dataclass(frozen=True)
class FundRecord:
    """One FONDREGISTRO Entidad at one observed period — verbatim identity."""

    entity_type: str
    numero_registro: str
    denominacion: str | None
    etf: str | None                      # 'SI' | 'NO' (verbatim)
    gestora: Institution
    depositario: Institution
    compartments: tuple[Compartment, ...]
    period: str                          # observed_period (YYYY-MM)
    provenance: Provenance

    @property
    def key(self) -> str:
        return fund_key(self.entity_type, self.numero_registro)

    def portfolio_owners(self) -> list[str]:
        """Compartment keys = the keys FONDCART reports positions against."""
        return [
            compartment_key(
                self.entity_type, self.numero_registro,
                c.numero_compartimento,
            )
            for c in self.compartments
        ]


class ResolutionKind(StrEnum):
    EXACT_SHARE_CLASS = "exact_share_class"
    EXACT_COMPARTMENT = "exact_compartment"
    EXACT_FUND = "exact_fund"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Resolution:
    kind: ResolutionKind
    requested: str
    portfolio_owners: tuple[str, ...]     # compartment keys for FONDCART
    share_class_key: str | None = None
    share_class_isin: str | None = None
    fund_key: str | None = None
    registry_artifact_id: str | None = None
    registry_locator: str | None = None
    note: str | None = None


class IdentityEventKind(StrEnum):
    NAME_CHANGED = "name_changed"
    MANAGER_CHANGED = "manager_changed"
    DEPOSITARY_CHANGED = "depositary_changed"
    ETF_CHANGED = "etf_changed"
    SHARE_CLASS_ADDED = "share_class_added"
    SHARE_CLASS_REMOVED = "share_class_removed"
    ISIN_CHANGED = "isin_changed"
    COMPARTMENT_ADDED = "compartment_added"
    COMPARTMENT_REMOVED = "compartment_removed"


@dataclass(frozen=True)
class IdentityEvent:
    """Mechanical diff between two registry observations — no cause inferred."""

    kind: IdentityEventKind
    fund_key: str
    field: str
    old: str | None
    new: str | None
    from_period: str
    to_period: str
