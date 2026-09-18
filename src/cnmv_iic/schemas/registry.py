"""Schema fingerprint registry + observed-deviation catalog (ADR-003).

Fail-closed contract:

1. Every XSD in an artifact is hashed; a family whose XSD hash is not in
   ``KNOWN_XSD_SHA256`` raises :class:`SchemaRegistryError`.
2. Adapters parse leniently (real instances deviate from the XSDs in stable,
   documented ways) but every element path encountered must be in
   ``KNOWN_ELEMENTS``; anything else raises :class:`UnsupportedSchemaError`.
3. ``DEVIATIONS`` records the enumerable instance-vs-XSD deviations observed
   in official files (docs/research/schema-history.md). They are data —
   quality metadata — never silent skips.

``KNOWN_ELEMENTS`` was built from the live element inventory of the
2012-03 and 2025-12 official instances (identical path sets).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from cnmv_iic.errors import SchemaRegistryError, UnsupportedSchemaError

# Full SHA-256 prefix (16 hex chars) per family; identical 2012->2025.
KNOWN_XSD_SHA256: dict[str, str] = {
    "FONDREGISTRO": "1b0a949a3940cd2f",
    "FONDMENS": "923803f9a93fa658",
    "FONDTRIM": "7a39ece36605ee85",
    "FONDPATRIMDISVAR": "aae1105328bd4c24",
    "FONDCART": "c5ab271b641242d4",
    "FONDDERI": "abeccc345799fa9d",
    "SOCREGISTRO": "6c47400171a8e705",
    "SOCTRIM": "d2867f6d6538a77d",
    "SOCPATRIMDISVAR": "8a1a5b24b066da8d",
    "SOCCART": "db61da5d84bf9b96",
    "SOCDERI": "0a23059a385dfa86",
}

FONDCART_ELEMENTS = frozenset({
    "FondCart",
    "FondCart/FechaDatos",
    "FondCart/Entidad",
    "FondCart/Entidad/Tipo",
    "FondCart/Entidad/NumeroRegistro",
    "FondCart/Entidad/Compartimento",
    "FondCart/Entidad/Compartimento/NumeroCompartimento",
    "FondCart/Entidad/Compartimento/InversionesFinancieras",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/ClaseIF",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/DescripcionIF",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/CodigoISIN",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/DescripcionValor",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/Divisa",
    "FondCart/Entidad/Compartimento/InversionesFinancieras/ValorMercado",
})

FONDPATRIMDISVAR_ELEMENTS = frozenset({
    "FondPatrimDisVar",
    "FondPatrimDisVar/FechaDatos",
    "FondPatrimDisVar/Entidad",
    "FondPatrimDisVar/Entidad/Tipo",
    "FondPatrimDisVar/Entidad/NumeroRegistro",
    "FondPatrimDisVar/Entidad/CodigoDivisaIIC",
    "FondPatrimDisVar/Entidad/Compartimento",
    "FondPatrimDisVar/Entidad/Compartimento/NumeroCompartimento",
    "FondPatrimDisVar/Entidad/Compartimento/IndiceRotacionCarteraActual",
    "FondPatrimDisVar/Entidad/Compartimento/IndiceRotacionCarteraAnterior",
    "FondPatrimDisVar/Entidad/Compartimento/DPInversionesFinancieras",
    "FondPatrimDisVar/Entidad/Compartimento/CarteraInterior",
    "FondPatrimDisVar/Entidad/Compartimento/CarteraExterior",
    "FondPatrimDisVar/Entidad/Compartimento/InteresesCartera",
    "FondPatrimDisVar/Entidad/Compartimento/InversionesDudosas",
    "FondPatrimDisVar/Entidad/Compartimento/Liquidez",
    "FondPatrimDisVar/Entidad/Compartimento/Resto",
    "FondPatrimDisVar/Entidad/Compartimento/TotalPatrimonio",
    "FondPatrimDisVar/Entidad/Compartimento/PatrimonioFinPeriodoAnterior",
    "FondPatrimDisVar/Entidad/Compartimento/Suscripciones_Reembolsos_Netos",
    "FondPatrimDisVar/Entidad/Compartimento/BeneficiosBrutosDistribuidos",
    "FondPatrimDisVar/Entidad/Compartimento/RendimientosGestion",
    "FondPatrimDisVar/Entidad/Compartimento/RendimientosNetos",
    "FondPatrimDisVar/Entidad/Compartimento/Intereses",
    "FondPatrimDisVar/Entidad/Compartimento/Dividendos",
    "FondPatrimDisVar/Entidad/Compartimento/ResultadosRentaFija",
    "FondPatrimDisVar/Entidad/Compartimento/ResultadosRentaVariable",
    "FondPatrimDisVar/Entidad/Compartimento/ResultadosDepositos",
    "FondPatrimDisVar/Entidad/Compartimento/ResultadosDerivados",
    "FondPatrimDisVar/Entidad/Compartimento/ResultadosIIC",
    "FondPatrimDisVar/Entidad/Compartimento/OtrosRendimientos",
    "FondPatrimDisVar/Entidad/Compartimento/OtrosResultados",
    "FondPatrimDisVar/Entidad/Compartimento/ComisionGestion",
    "FondPatrimDisVar/Entidad/Compartimento/ComisionDepositario",
    "FondPatrimDisVar/Entidad/Compartimento/ComisionesDescuento",
    "FondPatrimDisVar/Entidad/Compartimento/ComisionesRetrocedidas",
    "FondPatrimDisVar/Entidad/Compartimento/GastosServiciosExteriores",
    "FondPatrimDisVar/Entidad/Compartimento/GastosRepercutidos",
    "FondPatrimDisVar/Entidad/Compartimento/OtrosGastosGestion",
    "FondPatrimDisVar/Entidad/Compartimento/OtrosGastosRepercutidos",
    "FondPatrimDisVar/Entidad/Compartimento/Ingresos",
    "FondPatrimDisVar/Entidad/Compartimento/OtrosIngresos",
    "FondPatrimDisVar/Entidad/Compartimento/PatrimonioFinPeriodoActual",
})

FONDREGISTRO_ELEMENTS = frozenset({
    "FondRegistro",
    "FondRegistro/FechaDatos",
    "FondRegistro/Entidad",
    "FondRegistro/Entidad/Tipo",
    "FondRegistro/Entidad/NumeroRegistro",
    "FondRegistro/Entidad/Denominacion",
    "FondRegistro/Entidad/ETF",
    "FondRegistro/Entidad/Gestora",
    "FondRegistro/Entidad/Gestora/NumeroRegistroGestora",
    "FondRegistro/Entidad/Gestora/DenominacionGestora",
    "FondRegistro/Entidad/Gestora/TipoGestora",
    "FondRegistro/Entidad/Gestora/GrupoGestora",
    "FondRegistro/Entidad/Gestora/GrupoGestora/NumeroGrupoGestora",
    "FondRegistro/Entidad/Gestora/GrupoGestora/DenominacionGrupoGestora",
    "FondRegistro/Entidad/Depositario",
    "FondRegistro/Entidad/Depositario/NumeroRegistroDepositario",
    "FondRegistro/Entidad/Depositario/DenominacionDepositario",
    "FondRegistro/Entidad/Depositario/GrupoDepositario",
    "FondRegistro/Entidad/Depositario/GrupoDepositario/NumeroGrupoDepositario",
    "FondRegistro/Entidad/Depositario/GrupoDepositario/DenominacionGrupoDepositario",
    "FondRegistro/Entidad/Compartimento",
    "FondRegistro/Entidad/Compartimento/NumeroCompartimento",
    "FondRegistro/Entidad/Compartimento/DenominacionCompartimento",
    "FondRegistro/Entidad/Compartimento/Clase",
    "FondRegistro/Entidad/Compartimento/Clase/NumeroClase",
    "FondRegistro/Entidad/Compartimento/Clase/ISIN",
    "FondRegistro/Entidad/Compartimento/Clase/DenominacionClase",
})

_CLASE = "FondMens/Entidad/Compartimento/Clase"
FONDMENS_ELEMENTS = frozenset({
    "FondMens",
    "FondMens/FechaDatos",
    "FondMens/Entidad",
    "FondMens/Entidad/Tipo",
    "FondMens/Entidad/NumeroRegistro",
    "FondMens/Entidad/Compartimento",
    "FondMens/Entidad/Compartimento/NumeroCompartimento",
    _CLASE,
    f"{_CLASE}/NumeroClase",
    f"{_CLASE}/ISIN",
    f"{_CLASE}/VLDiario",
    f"{_CLASE}/PatrimonioDiario",
    f"{_CLASE}/ParticipesDiario",
    *{f"{_CLASE}/VLDiario/VL_Dia{d}" for d in range(1, 32)},
    *{f"{_CLASE}/PatrimonioDiario/Patrimonio_Dia{d}" for d in range(1, 32)},
    *{f"{_CLASE}/ParticipesDiario/Participes_Dia{d}" for d in range(1, 32)},
})

_T_CLASE = "FondTrim/Entidad/Compartimento/Clase"

FONDTRIM_ELEMENTS = frozenset({
    "FondTrim",
    "FondTrim/FechaDatos",
    "FondTrim/Entidad",
    "FondTrim/Entidad/Tipo",
    "FondTrim/Entidad/NumeroRegistro",
    "FondTrim/Entidad/CodigoDivisaIIC",
    "FondTrim/Entidad/Compartimento",
    "FondTrim/Entidad/Compartimento/NumeroCompartimento",
    "FondTrim/Entidad/Compartimento/ClaseFondo",
    "FondTrim/Entidad/Compartimento/VocacionInversora",
    _T_CLASE,
    f"{_T_CLASE}/NumeroClase",
    f"{_T_CLASE}/ISIN",
    f"{_T_CLASE}/CodigoDivisa",
    f"{_T_CLASE}/Patrimonio",
    f"{_T_CLASE}/ValorLiquidativo",
    f"{_T_CLASE}/NumeroParticipaciones",
    f"{_T_CLASE}/NumeroParticipes",
    f"{_T_CLASE}/ComisionGestion",
    f"{_T_CLASE}/ComisionDepositario",
    f"{_T_CLASE}/ComisionSuscripcionMinima",
    f"{_T_CLASE}/ComisionSuscripcionMaxima",
    f"{_T_CLASE}/ComisionReembolsoMinima",
    f"{_T_CLASE}/ComisionReembolsoMaxima",
    f"{_T_CLASE}/ComisionDescuentoFavorFondoMinima",
    f"{_T_CLASE}/ComisionDescuentoFavorFondoMaxima",
    f"{_T_CLASE}/BaseCalculo_ComisionGestion",
    f"{_T_CLASE}/SistemaImputacionComisiones",
    f"{_T_CLASE}/PeriodicidadCalculoVL",
    f"{_T_CLASE}/Beneficio_Dividendo_Bruto",
    f"{_T_CLASE}/Rentabilidad",
    f"{_T_CLASE}/Rentabilidad/Rentabilidad_TrimestreActual",
    f"{_T_CLASE}/Rentabilidad/Rentabilidad_T_1",
    f"{_T_CLASE}/Rentabilidad/Rentabilidad_T_2",
    f"{_T_CLASE}/Rentabilidad/Rentabilidad_T_3",
    f"{_T_CLASE}/RatioTotalGastos",
    f"{_T_CLASE}/RatioTotalGastos/RatioTotalGastos_TrimestreActual",
    f"{_T_CLASE}/RatioTotalGastos/RatioTotalGastos_T_1",
    f"{_T_CLASE}/RatioTotalGastos/RatioTotalGastos_T_2",
    f"{_T_CLASE}/RatioTotalGastos/RatioTotalGastos_T_3",
    f"{_T_CLASE}/Volatilidad_VL",
    f"{_T_CLASE}/Volatilidad_VL/Volatilidad_TrimestreActual",
    f"{_T_CLASE}/Volatilidad_VL/Volatilidad_T_1",
    f"{_T_CLASE}/Volatilidad_VL/Volatilidad_T_2",
    f"{_T_CLASE}/Volatilidad_VL/Volatilidad_T_3",
})

KNOWN_ELEMENTS: dict[str, frozenset[str]] = {
    "FONDCART": FONDCART_ELEMENTS,
    "FONDPATRIMDISVAR": FONDPATRIMDISVAR_ELEMENTS,
    "FONDREGISTRO": FONDREGISTRO_ELEMENTS,
    "FONDMENS": FONDMENS_ELEMENTS,
    "FONDTRIM": FONDTRIM_ELEMENTS,
}


@dataclass(frozen=True)
class Deviation:
    family: str
    element_path: str
    kind: str                      # MISSING_REQUIRED_ELEMENT | MASKED_VALUE | ...
    periods_observed: tuple[str, ...]
    note: str


DEVIATIONS: tuple[Deviation, ...] = (
    Deviation(
        family="FONDCART",
        element_path="Entidad/Compartimento/InversionesFinancieras/CodigoISIN",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2012-03", "2025-12"),
        note="element absent on deposit positions (DescripcionIF=Depositos); "
             "2012-03 n~3543 (~5.9%), 2025-12 n~237",
    ),
    Deviation(
        family="FONDCART",
        element_path="Entidad/Compartimento/InversionesFinancieras/CodigoISIN",
        kind="MASKED_VALUE",
        periods_observed=("2025-12",),
        note="literal 'XXXXXXXXXXXX' (148 obs. in 2025-12) — CNMV-masked ISIN",
    ),
    Deviation(
        family="FONDCART",
        element_path="Entidad/Compartimento/InversionesFinancieras/Divisa",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2012-03",),
        note="17 positions lack the Divisa element; absent in all other "
             "sampled periods 2014-2025",
    ),
    Deviation(
        family="FONDPATRIMDISVAR",
        element_path="Entidad/CodigoDivisaIIC",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2025-12",),
        note="absent on ~288 entidad records",
    ),
    Deviation(
        family="FONDTRIM",
        element_path="Entidad/CodigoDivisaIIC",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2025-12",),
        note="absent on 287/1668 entidad records (same element as "
             "FONDPATRIMDISVAR deviation)",
    ),
    Deviation(
        family="FONDTRIM",
        element_path="Entidad/Compartimento/Clase/SistemaImputacionComisiones",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2012-03", "2025-12"),
        note="absent on ~50% of class records in both eras",
    ),
    Deviation(
        family="FONDTRIM",
        element_path="Entidad/Compartimento/Clase/Beneficio_Dividendo_Bruto",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2012-03", "2025-12"),
        note="absent on ~6% of class records",
    ),
    Deviation(
        family="FONDTRIM",
        element_path="Entidad/Compartimento/Clase/Rentabilidad",
        kind="EMPTY_CONTAINER",
        periods_observed=("2025-12",),
        note="block container present but empty (243 instances across the "
             "three rolling blocks) — class without metric history; also "
             "T_1/T_2/T_3 sub-elements individually absent (insufficient "
             "history), preserved as missing not zero",
    ),
    Deviation(
        family="FONDTRIM",
        element_path="Entidad/Compartimento/Clase/CodigoDivisa",
        kind="MISSING_REQUIRED_ELEMENT",
        periods_observed=("2012-03", "2025-12"),
        note="1 class per era lacks CodigoDivisa and all metric elements — "
             "identity-only row (like FONDMENS missing blocks)",
    ),
)


def check_xsd(family: str, sha256_hex: str) -> None:
    """Fail closed on an unrecognized XSD fingerprint."""
    known = KNOWN_XSD_SHA256.get(family)
    if known is None:
        raise SchemaRegistryError(f"no XSD fingerprint registered for family {family}")
    if not sha256_hex.startswith(known):
        raise SchemaRegistryError(
            f"{family} XSD fingerprint {sha256_hex[:16]}… not in registry"
        )


def check_element(family: str, path: str) -> None:
    """Fail closed on an element not in (official schema union deviations)."""
    allowed = KNOWN_ELEMENTS.get(family)
    if allowed is None:
        raise SchemaRegistryError(f"no element catalog for family {family}")
    if path not in allowed:
        raise UnsupportedSchemaError(f"{family}: unknown element {path!r}")


def assert_structure(family: str, root: Any) -> None:
    """Walk an instance's element tree; every path must be registered."""
    def walk(el: Any, path: str) -> None:
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        p = f"{path}/{tag}" if path else tag
        check_element(family, p)
        for child in el:
            walk(child, p)

    walk(root, "")
