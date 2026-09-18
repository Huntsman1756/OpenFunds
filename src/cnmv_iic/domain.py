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
    INVALID_IDENTIFIER = "invalid_identifier"   # malformed/masked/non-valid ISIN
    AMBIGUOUS = "ambiguous"                      # >1 plausible resolutions only
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


# ---------------------------------------------------------------------------
# G3 — daily share-class observations (FONDMENS)
# ---------------------------------------------------------------------------


class ObservationState(StrEnum):
    """Per-metric state of one day cell (docs/g3/contract.md)."""

    OBSERVED = "observed"                    # real published value
    SOURCE_ZERO_SENTINEL = "source_zero_sentinel"  # '0' = no observation
    MISSING = "missing"                      # element/block absent in source
    INVALID = "invalid"                      # present but non-numeric


class RegistryJoinState(StrEnum):
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved_registry_reference"


@dataclass(frozen=True)
class MetricObservation:
    """One metric on one day: clean value + verbatim raw + state."""

    value: Decimal | int | None   # populated only when state == OBSERVED
    raw: str | None               # verbatim lexical value (None if absent)
    state: ObservationState


@dataclass(frozen=True)
class ShareClassDailyObservation:
    """One (share_class, calendar day) row from FONDMENS.

    The grain is the SHARE CLASS — never collapsed to the compartment
    portfolio owner (contrast with G1 holdings). Values are OBSERVED only;
    nothing is forward-filled or interpolated.
    """

    entity_type: str
    numero_registro: str
    numero_compartimento: str
    numero_clase: str
    isin_raw: str | None
    isin_state: IsinState
    observation_date: str         # ISO 'YYYY-MM-DD', calendar-valid day only
    day_index: int                # 1..month_length
    nav: MetricObservation        # VL_DiaN (EUR)
    aum: MetricObservation        # Patrimonio_DiaN (EUR)
    investors: MetricObservation  # Participes_DiaN
    registry_state: RegistryJoinState
    period: str                   # observed_period (YYYY-MM)
    provenance: Provenance

    @property
    def share_class_key(self) -> str:
        return share_class_key(
            self.entity_type, self.numero_registro,
            self.numero_compartimento, self.numero_clase,
        )

    @property
    def compartment_key(self) -> str:
        return compartment_key(
            self.entity_type, self.numero_registro,
            self.numero_compartimento,
        )

    @property
    def fund_key(self) -> str:
        return fund_key(self.entity_type, self.numero_registro)


# ---------------------------------------------------------------------------
# G4-B — compartment patrimony distribution/variation (FONDPATRIMDISVAR)
# ---------------------------------------------------------------------------

#: Unit basis of every FONDPATRIMDISVAR field (docs/g4/contract.md §3).
#: The source record MIXES monetary stock fields with signed percentage
#: flow fields — the distinction is contractual, not cosmetic.
#:   monetary_iic_currency        -> units of CodigoDivisaIIC
#:   pct_over_avg_daily_patrimonio -> % over the period's average daily
#:                                   patrimonio; SIGNED (costs negative)
#:   ratio                        -> turnover index [(C+V)-(S+R)]/PMD
PDV_UNIT_BASIS: dict[str, str] = {
    "indice_rotacion_cartera_actual": "ratio",
    "indice_rotacion_cartera_anterior": "ratio",
    "dp_inversiones_financieras": "monetary_iic_currency",
    "cartera_interior": "monetary_iic_currency",
    "cartera_exterior": "monetary_iic_currency",
    "intereses_cartera": "monetary_iic_currency",
    "inversiones_dudosas": "monetary_iic_currency",
    "liquidez": "monetary_iic_currency",
    "resto": "monetary_iic_currency",
    "total_patrimonio": "monetary_iic_currency",
    "patrimonio_fin_periodo_anterior": "monetary_iic_currency",
    "patrimonio_fin_periodo_actual": "monetary_iic_currency",
    "suscripciones_reembolsos_netos": "pct_over_avg_daily_patrimonio",
    "beneficios_brutos_distribuidos": "pct_over_avg_daily_patrimonio",
    "rendimientos_netos": "pct_over_avg_daily_patrimonio",
    "rendimientos_gestion": "pct_over_avg_daily_patrimonio",
    "intereses": "pct_over_avg_daily_patrimonio",
    "dividendos": "pct_over_avg_daily_patrimonio",
    "resultados_renta_fija": "pct_over_avg_daily_patrimonio",
    "resultados_renta_variable": "pct_over_avg_daily_patrimonio",
    "resultados_depositos": "pct_over_avg_daily_patrimonio",
    "resultados_derivados": "pct_over_avg_daily_patrimonio",
    "resultados_iic": "pct_over_avg_daily_patrimonio",
    "otros_resultados": "pct_over_avg_daily_patrimonio",
    "otros_rendimientos": "pct_over_avg_daily_patrimonio",
    "gastos_repercutidos": "pct_over_avg_daily_patrimonio",
    "comision_gestion": "pct_over_avg_daily_patrimonio",
    "comision_depositario": "pct_over_avg_daily_patrimonio",
    "gastos_servicios_exteriores": "pct_over_avg_daily_patrimonio",
    "otros_gastos_gestion": "pct_over_avg_daily_patrimonio",
    "otros_gastos_repercutidos": "pct_over_avg_daily_patrimonio",
    "ingresos": "pct_over_avg_daily_patrimonio",
    "comisiones_descuento": "pct_over_avg_daily_patrimonio",
    "comisiones_retrocedidas": "pct_over_avg_daily_patrimonio",
    "otros_ingresos": "pct_over_avg_daily_patrimonio",
}


@dataclass(frozen=True)
class CompartmentPatrimonySnapshot:
    """One (compartment, period) row from FONDPATRIMDISVAR.

    Measured grain is compartment/fund-level — the file contains ZERO
    ``Clase`` elements (docs/g4/contract.md). Keyed by the same
    ``compartment_key`` FONDCART reports positions against.

    Two unit classes coexist in one record — see ``PDV_UNIT_BASIS``:

    - stock fields (``cartera_*``, ``liquidez``, ``resto``,
      ``total_patrimonio``, ``patrimonio_fin_periodo_*``,
      ``dp_inversiones_financieras``, ``intereses_cartera``,
      ``inversiones_dudosas``): monetary, IIC denomination currency
      (``codigo_divisa_iic``).
    - flow/variation fields (``suscripciones_reembolsos_netos`` ..
      ``otros_ingresos``): SIGNED percentages over the period's average
      daily patrimonio — NOT money (verified: real values like -4.88 /
      -0.95). Costs are negative contributions.
    - ``indice_rotacion_cartera_*``: turnover ratio; ``_anterior`` refers
      to the prior reporting period and is absent when none exists.

    ``None`` = absent element (missing), never inferred. ``0`` is a
    genuine observed value.
    """

    entity_type: str
    numero_registro: str
    numero_compartimento: str
    codigo_divisa_iic: str | None          # entity-level, unit of stock fields
    # ratios
    indice_rotacion_cartera_actual: Decimal | None
    indice_rotacion_cartera_anterior: Decimal | None
    # stock — monetary, IIC currency
    dp_inversiones_financieras: Decimal | None   # = CI+CE+IC+ID (G1 recon)
    cartera_interior: Decimal | None
    cartera_exterior: Decimal | None
    intereses_cartera: Decimal | None
    inversiones_dudosas: Decimal | None
    liquidez: Decimal | None
    resto: Decimal | None
    total_patrimonio: Decimal | None
    patrimonio_fin_periodo_anterior: Decimal | None
    patrimonio_fin_periodo_actual: Decimal | None
    # flow — signed % over avg daily patrimonio (NOT money)
    suscripciones_reembolsos_netos: Decimal | None
    beneficios_brutos_distribuidos: Decimal | None
    rendimientos_netos: Decimal | None
    rendimientos_gestion: Decimal | None
    intereses: Decimal | None
    dividendos: Decimal | None
    resultados_renta_fija: Decimal | None
    resultados_renta_variable: Decimal | None
    resultados_depositos: Decimal | None
    resultados_derivados: Decimal | None
    resultados_iic: Decimal | None
    otros_resultados: Decimal | None
    otros_rendimientos: Decimal | None
    gastos_repercutidos: Decimal | None
    comision_gestion: Decimal | None
    comision_depositario: Decimal | None
    gastos_servicios_exteriores: Decimal | None
    otros_gastos_gestion: Decimal | None
    otros_gastos_repercutidos: Decimal | None
    ingresos: Decimal | None
    comisiones_descuento: Decimal | None
    comisiones_retrocedidas: Decimal | None
    otros_ingresos: Decimal | None
    registry_state: RegistryJoinState
    period: str                   # observed_period (YYYY-MM)
    provenance: Provenance

    @property
    def compartment_key(self) -> str:
        return compartment_key(
            self.entity_type, self.numero_registro,
            self.numero_compartimento,
        )

    @property
    def fund_key(self) -> str:
        return fund_key(self.entity_type, self.numero_registro)


# ---------------------------------------------------------------------------
# G4-A — quarterly share-class metrics (FONDTRIM)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShareClassQuarterlyMetrics:
    """One (share_class, period) row from FONDTRIM (docs/g4/contract.md).

    Measured grain is uniformly class-level: every metric element lives
    under ``Clase`` (``NumeroClase=0`` = fund-level row, same convention
    as FONDMENS). Compartment-level (``VocacionInversora``, ``ClaseFondo``)
    and entity-level (``CodigoDivisaIIC``) attributes are denormalized
    onto the record, their true source level documented here.

    Units (official semantics): ``patrimonio``/``valor_liquidativo``/
    ``numero_participaciones``/``beneficio_dividendo_bruto`` are monetary
    in the CLASS denomination currency (``codigo_divisa`` — NOT always
    EUR). All ``comision_*``, ``official_return_*``, ``ratio_total_gastos_*``
    and ``volatilidad_*`` are percentages (fees: effectively accrued over
    the period; returns: official CNMV non-annualized; ratio: % of
    average daily patrimonio — NOT labelled "TER"; volatility: %).
    ``None`` everywhere means the source element was absent (missing) —
    never an inferred value. ``0`` is a genuine observed value, not a
    sentinel (contrast with FONDMENS).
    """

    entity_type: str
    numero_registro: str
    numero_compartimento: str
    numero_clase: str
    isin_raw: str | None
    isin_state: IsinState
    # class metadata (verbatim enums)
    codigo_divisa: str | None                # unit of the monetary fields
    periodicidad_calculo_vl: str | None      # Diaria|Semanal|Quincenal|Otros
    base_calculo_comision_gestion: str | None  # Patrimonio|Resultados|Mixta
    sistema_imputacion_comisiones: str | None
    # stock metrics — monetary, class currency
    patrimonio: Decimal | None
    valor_liquidativo: Decimal | None
    numero_participaciones: Decimal | None
    numero_participes: int | None
    beneficio_dividendo_bruto: Decimal | None
    # fees — % effectively accrued/borne during the period (may be negative)
    comision_gestion: Decimal | None
    comision_depositario: Decimal | None
    comision_suscripcion_minima: Decimal | None
    comision_suscripcion_maxima: Decimal | None
    comision_reembolso_minima: Decimal | None
    comision_reembolso_maxima: Decimal | None
    comision_descuento_favor_fondo_minima: Decimal | None
    comision_descuento_favor_fondo_maxima: Decimal | None
    # official CNMV returns — non-annualized %, quarters T / T-1 / T-2 / T-3
    official_return_t: Decimal | None
    official_return_t_1: Decimal | None
    official_return_t_2: Decimal | None
    official_return_t_3: Decimal | None
    # operating-expense ratio — % of avg daily patrimonio
    ratio_total_gastos_t: Decimal | None
    ratio_total_gastos_t_1: Decimal | None
    ratio_total_gastos_t_2: Decimal | None
    ratio_total_gastos_t_3: Decimal | None
    # historical NAV volatility — %
    volatilidad_vl_t: Decimal | None
    volatilidad_vl_t_1: Decimal | None
    volatilidad_vl_t_2: Decimal | None
    volatilidad_vl_t_3: Decimal | None
    # compartment-level attributes (verbatim, denormalized)
    vocacion_inversora: str | None
    clase_fondo: str | None
    # entity-level attribute
    codigo_divisa_iic: str | None
    registry_state: RegistryJoinState
    period: str                   # observed_period (YYYY-MM)
    provenance: Provenance

    @property
    def share_class_key(self) -> str:
        return share_class_key(
            self.entity_type, self.numero_registro,
            self.numero_compartimento, self.numero_clase,
        )

    @property
    def compartment_key(self) -> str:
        return compartment_key(
            self.entity_type, self.numero_registro,
            self.numero_compartimento,
        )

    @property
    def fund_key(self) -> str:
        return fund_key(self.entity_type, self.numero_registro)
