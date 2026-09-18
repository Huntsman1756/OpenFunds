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


# ---------------------------------------------------------------------------
# G5 — FONDDERI: derivative-operation evidence ledger
# ---------------------------------------------------------------------------


class DerivativeSide(StrEnum):
    """Official Descripcion facet: right vs obligation (documented)."""

    DERECHO = "derecho"
    OBLIGACION = "obligacion"


class UnderlierClass(StrEnum):
    """Official Descripcion facet: underlier asset class (4 values)."""

    RENTA_FIJA = "renta_fija"
    RENTA_VARIABLE = "renta_variable"
    TIPO_DE_CAMBIO = "tipo_de_cambio"
    OTROS = "otros"


class DerivativeObjective(StrEnum):
    """Official Objetivo coded field (3 documented values)."""

    COBERTURA = "cobertura"
    INVERSION = "inversion"
    OBJETIVO_CONCRETO_DE_RENTABILIDAD = "objetivo_concreto_de_rentabilidad"


class DerivativeRepresentation(StrEnum):
    """How much of a row is source-structured (never inferred)."""

    STRUCTURED = "structured"
    PARTIALLY_STRUCTURED = "partially_structured"
    VERBATIM_ONLY = "verbatim_only"


#: Official Descripcion composite -> (side, underlier class). This is a
#: documented closed code (explanatory PDF), not text inference.
DERI_DESCRIPCION_FACETS: dict[str, tuple[DerivativeSide, UnderlierClass]] = {
    "Obligaciones en renta fija": (
        DerivativeSide.OBLIGACION, UnderlierClass.RENTA_FIJA),
    "Obligaciones en renta variable": (
        DerivativeSide.OBLIGACION, UnderlierClass.RENTA_VARIABLE),
    "Obligaciones en tipos de cambio": (
        DerivativeSide.OBLIGACION, UnderlierClass.TIPO_DE_CAMBIO),
    "Otras Obligaciones": (
        DerivativeSide.OBLIGACION, UnderlierClass.OTROS),
    "Derechos en renta fija": (
        DerivativeSide.DERECHO, UnderlierClass.RENTA_FIJA),
    "Derechos en renta variable": (
        DerivativeSide.DERECHO, UnderlierClass.RENTA_VARIABLE),
    "Derechos en tipos de cambio": (
        DerivativeSide.DERECHO, UnderlierClass.TIPO_DE_CAMBIO),
    "Otros Derechos": (
        DerivativeSide.DERECHO, UnderlierClass.OTROS),
}

DERI_OBJETIVO_VALUES: dict[str, DerivativeObjective] = {
    "Cobertura": DerivativeObjective.COBERTURA,
    "Inversión": DerivativeObjective.INVERSION,
    "Objetivo Concreto de Rentabilidad": (
        DerivativeObjective.OBJETIVO_CONCRETO_DE_RENTABILIDAD),
}


@dataclass(frozen=True)
class CompartmentDerivativeOperation:
    """One OperativaDerivados row from FONDDERI (docs/g5/contract.md).

    Measured grain: ``(compartment_key, operation_ordinal)`` — the file
    contains ZERO ``Clase`` elements; one row per reported derivative
    operation. Compartments report even with zero operations (explicit
    empty state, coverage-level — not fabricated rows).

    Source-structured fields only:

    - ``descripcion`` is a documented closed enum (8 values); its two
      facets (``side``, ``underlier_class``) are decomposed per the
      official document — never regex-parsed.
    - ``objetivo`` is a documented coded field (3 values).
    - ``importe`` is the committed nominal amount IN EUR per the
      explanatory PDF ("importe nominal comprometido expresado en
      euros") — signed, scale 2; negatives observed.
    - ``subyacente``/``instrumento`` are officially "texto no
      normalizado" — verbatim, never parsed into product attributes.
    """

    entity_type: str
    numero_registro: str
    numero_compartimento: str
    operation_index: int            # 1-based ordinal within compartment
    # verbatim + documented facets
    descripcion: str                # closed-enum label, verbatim
    side: DerivativeSide
    underlier_class: UnderlierClass
    # officially non-normalized text — verbatim only
    subyacente: str
    instrumento: str
    # committed nominal, EUR (documented basis), signed
    importe: Decimal
    objetivo: DerivativeObjective | None   # 1 absent in 2014-03
    # entity-level attribute
    codigo_divisa_iic: str | None
    representation: DerivativeRepresentation
    registry_state: RegistryJoinState
    period: str                     # observed_period (YYYY-MM)
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


@dataclass(frozen=True)
class CompartmentDerivativeCoverage:
    """Per-compartment reporting state from FONDDERI.

    A compartment present with zero OperativaDerivados is an
    explicitly reported no-derivatives state — different from a
    compartment absent from the file entirely.
    """

    compartment_key: str
    fund_key: str
    entity_type: str
    numero_registro: str
    numero_compartimento: str
    codigo_divisa_iic: str | None
    n_operations: int               # 0 = explicitly reported none
    registry_state: RegistryJoinState
    period: str
    provenance: Provenance


# ---------------------------------------------------------------------------
# G7 — resolution evidence ledger (provider observations, NOT canonical
# resolution). Adjudication happens later (G7-E) over ALL providers'
# observations — never inside a single-provider adapter.
# ---------------------------------------------------------------------------

TEMPORAL_SEMANTICS = "current_enrichment_of_historical_security"


class ResolutionState(StrEnum):
    """Per-observation outcome — what one provider snapshot said about one
    ISIN. ``no_match`` means only "this provider snapshot contains no
    ISIN->LEI row for this ISIN" — never "issuer has no LEI"."""

    MATCHED = "matched"                          # exactly one candidate
    NO_MATCH = "no_match"                        # no row for this ISIN
    MULTIPLE_CANDIDATES = "multiple_candidates"  # >1 rows (model supports N)
    NOT_APPLICABLE = "not_applicable"            # provider out of scope
    PROVIDER_ERROR = "provider_error"            # per-record provider failure


@dataclass(frozen=True)
class ResolutionObservation:
    """One provider's answer for one ISIN in one pinned snapshot.

    Grain: (isin, provider, provider_snapshot_date). ``holding_periods``
    records which corpus periods carry the ISIN — kept separate from
    ``provider_snapshot_date`` so current enrichment can never be read as
    as-of-holding knowledge.
    """

    observation_id: str             # "<provider>/<snapshot>/<isin>"
    isin: str                       # upstream-gated to isin_state=valid
    provider: str                   # "gleif_anna_isin_lei"
    provider_dataset: str           # "isin-lei"
    provider_snapshot_date: str     # "YYYY-MM-DD" — artifact date
    provider_artifact_id: str       # immutable provider artifact
    state: ResolutionState
    candidate_count: int
    holding_periods: tuple[str, ...]  # corpus periods where ISIN observed
    temporal_semantics: str         # TEMPORAL_SEMANTICS constant
    retrieved_at: str
    source_sha256: str              # provider zip sha256
    member_name: str                # csv member inside the zip
    member_sha256: str
    parser: str
    parser_version: str


@dataclass(frozen=True)
class ResolutionCandidate:
    """One candidate LEI attached to an observation. The model allows 0/1/N
    candidates — observed GLEIF snapshots are functional (0 or 1), but a
    future snapshot breaking the invariant becomes ``multiple_candidates``,
    not a DB exception or a dropped row."""

    observation_id: str
    candidate_index: int            # 1-based, deterministic (provider row order)
    candidate_lei: str
    relationship_semantics: str     # "isin_issuer_to_lei"
    provider_record_locator: str    # "<member>#row=<n>" — to the GLEIF csv line
    raw_json: str                   # verbatim provider fields as JSON


# ---------------------------------------------------------------------------
# G7-B — GLEIF Level-1 entity + Level-2 relationship/exception evidence.
# Evidence only: relationship types are verbatim GLEIF vocabulary, never
# collapsed to a generic "parent". Absence of an RR record is NOT absence
# of a parent — reporting exceptions are first-class rows.
# ---------------------------------------------------------------------------

# why a legal-entity record was pulled into evidence
ENTITY_EVIDENCE_RESOLVED = "resolved"             # LEI appears in G7-A candidates
ENTITY_EVIDENCE_CLOSURE = "closure_end_node"      # one-hop RR end node


@dataclass(frozen=True)
class LegalEntityObservation:
    """GLEIF LEI-CDF Level-1 "who is who" record for one LEI."""

    entity_id: str                  # "<provider>/<snapshot>/<lei>"
    lei: str
    provider: str                   # "gleif_lei_cdf"
    provider_dataset: str           # "lei-cdf-3.1"
    provider_snapshot_date: str     # YYYY-MM-DD
    provider_artifact_id: str
    evidence_role: str              # resolved | closure_end_node
    legal_name: str | None
    other_names_json: str           # JSON array, verbatim
    legal_address_json: str         # JSON object, verbatim
    headquarters_address_json: str  # JSON object, verbatim
    legal_jurisdiction: str | None
    entity_category: str | None     # FUND|SUBFUND|GENERAL|BRANCH|...
    entity_status: str | None       # ACTIVE|INACTIVE|...
    legal_form: str | None          # ISO 20275 code / free text, verbatim
    registration_status: str | None # ISSUED|LAPSED|...
    initial_registration_date: str | None
    last_update_date: str | None
    next_renewal_date: str | None
    managing_lou: str | None
    provider_record_locator: str    # xml element ordinal
    raw_json: str                   # full verbatim field set
    retrieved_at: str
    source_sha256: str
    member_name: str
    member_sha256: str
    parser: str
    parser_version: str


@dataclass(frozen=True)
class RelationshipObservation:
    """One GLEIF RR-CDF record — verbatim relationship type + status.

    ``relationship_type`` keeps the official vocabulary verbatim:
    IS_DIRECTLY_CONSOLIDATED_BY, IS_ULTIMATELY_CONSOLIDATED_BY,
    IS_INTERNATIONAL_BRANCH_OF, IS_FUND-MANAGED_BY, IS_SUBFUND_OF,
    IS_FEEDER_TO. Never renamed to a generic "parent".
    """

    relationship_id: str            # "<provider>/<snapshot>/<start>/<type>/<end>"
    start_lei: str
    end_lei: str
    relationship_type: str          # verbatim GLEIF vocabulary
    relationship_status: str        # ACTIVE|INACTIVE|NULL, verbatim
    relationship_periods_json: str  # [{type,start_date,end_date}]
    validation_sources: str | None  # verbatim
    registration_status: str | None
    provider: str                   # "gleif_rr_cdf"
    provider_dataset: str           # "rr-cdf-2.1"
    provider_snapshot_date: str
    provider_artifact_id: str
    provider_record_locator: str
    raw_json: str
    retrieved_at: str
    source_sha256: str
    member_name: str
    member_sha256: str
    parser: str
    parser_version: str


@dataclass(frozen=True)
class RelationshipExceptionObservation:
    """GLEIF Reporting Exceptions row — an officially declared reason a
    consolidation-parent relationship cannot be provided. NOT a NULL:
    NO_KNOWN_PERSON / NON_CONSOLIDATING / NATURAL_PERSONS / NO_LEI /
    NON_PUBLIC are first-class evidence."""

    exception_id: str               # "<provider>/<snapshot>/<lei>/<category>"
    lei: str
    exception_category: str         # DIRECT_/ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT
    exception_reason: str           # verbatim GLEIF vocabulary
    provider: str                   # "gleif_repex"
    provider_dataset: str           # "repex-2.1"
    provider_snapshot_date: str
    provider_artifact_id: str
    provider_record_locator: str
    raw_json: str
    retrieved_at: str
    source_sha256: str
    member_name: str
    member_sha256: str
    parser: str
    parser_version: str
