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

KNOWN_ELEMENTS: dict[str, frozenset[str]] = {
    "FONDCART": FONDCART_ELEMENTS,
    "FONDPATRIMDISVAR": FONDPATRIMDISVAR_ELEMENTS,
    "FONDREGISTRO": FONDREGISTRO_ELEMENTS,
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
