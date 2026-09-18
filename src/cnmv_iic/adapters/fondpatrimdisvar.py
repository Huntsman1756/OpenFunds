"""FONDPATRIMDISVAR adapter — XML -> CompartmentPatrimonySnapshot rows.

G4 scope (docs/g4/contract.md): verbatim patrimony distribution and
variation per compartment. The measured grain is compartment/fund-level
— the file contains ZERO ``Clase`` elements — keyed by the same
``compartment_key`` FONDCART reports positions against.

Observed-source semantics implemented here:

- One record MIXES two unit classes (``PDV_UNIT_BASIS`` in domain.py):
  stock fields are monetary in the IIC denomination currency
  (``codigo_divisa_iic``); flow/variation fields are SIGNED percentages
  over the period's average daily patrimonio (verified: real values
  like -4.88 / -0.95 — costs are negative contributions, never money).
- ``IndiceRotacionCarteraAnterior`` refers to the prior reporting
  period and is absent for compartments without one (measured: 46
  absent in 2012-03, 51 in 2025-12) — preserved as missing.
- ``None`` = absent element (missing), never inferred. ``0`` is a
  genuine observed value.
- A present but non-numeric value fails closed with ``ParseError``.
- ``registry_state`` records whether the compartment key exists in the
  same-period FONDREGISTRO snapshot — ``unresolved_registry_reference``
  when it does not. No fuzzy matching, ever.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from lxml import etree

from cnmv_iic import __version__
from cnmv_iic.adapters.common import (
    parse_period,
    required_text,
    secure_parse,
    text_of,
)
from cnmv_iic.domain import (
    CompartmentPatrimonySnapshot,
    Provenance,
    RegistryJoinState,
    compartment_key,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondpatrimdisvar"
PARSER_VERSION = __version__
FAMILY = "FONDPATRIMDISVAR"


def _dec(el: etree._Element, tag: str, locator: str) -> Decimal | None:
    raw = text_of(el, tag)
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(
            f"{FAMILY}: non-decimal {tag}={raw!r} at {locator}"
        ) from exc


def parse_fondpatrimdisvar(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
    registry_compartment_keys: frozenset[str] | None = None,
) -> list[CompartmentPatrimonySnapshot]:
    """Parse one FONDPATRIMDISVAR member into per-compartment records.

    ``registry_compartment_keys``: compartment keys from the same-period
    FONDREGISTRO snapshot (exact join). ``None`` = no registry data
    ingested; every row is then marked ``unresolved_registry_reference``.
    """
    root = secure_parse(xml, FAMILY)
    assert_structure(FAMILY, root)
    period = parse_period(root, FAMILY)

    rows: list[CompartmentPatrimonySnapshot] = []
    seen: set[str] = set()
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondPatrimDisVar/Entidad[{i}]"
        tipo = required_text(ent, "Tipo", FAMILY, e_loc)
        nreg = required_text(ent, "NumeroRegistro", FAMILY, e_loc)
        divisa_iic = text_of(ent, "CodigoDivisaIIC")
        for j, comp in enumerate(ent.findall("Compartimento"), start=1):
            c_loc = f"{e_loc}/Compartimento[{j}]"
            ncomp = required_text(comp, "NumeroCompartimento",
                                  FAMILY, c_loc)
            key = compartment_key(tipo, nreg, ncomp)
            if key in seen:
                raise ParseError(
                    f"{FAMILY}: duplicate compartment key {key} at {c_loc}")
            seen.add(key)
            reg_state = (
                RegistryJoinState.RESOLVED
                if registry_compartment_keys is not None
                and key in registry_compartment_keys
                else RegistryJoinState.UNRESOLVED
            )
            rows.append(CompartmentPatrimonySnapshot(
                entity_type=tipo,
                numero_registro=nreg,
                numero_compartimento=ncomp,
                codigo_divisa_iic=divisa_iic,
                indice_rotacion_cartera_actual=_dec(
                    comp, "IndiceRotacionCarteraActual", c_loc),
                indice_rotacion_cartera_anterior=_dec(
                    comp, "IndiceRotacionCarteraAnterior", c_loc),
                dp_inversiones_financieras=_dec(
                    comp, "DPInversionesFinancieras", c_loc),
                cartera_interior=_dec(comp, "CarteraInterior", c_loc),
                cartera_exterior=_dec(comp, "CarteraExterior", c_loc),
                intereses_cartera=_dec(comp, "InteresesCartera", c_loc),
                inversiones_dudosas=_dec(comp, "InversionesDudosas", c_loc),
                liquidez=_dec(comp, "Liquidez", c_loc),
                resto=_dec(comp, "Resto", c_loc),
                total_patrimonio=_dec(comp, "TotalPatrimonio", c_loc),
                patrimonio_fin_periodo_anterior=_dec(
                    comp, "PatrimonioFinPeriodoAnterior", c_loc),
                patrimonio_fin_periodo_actual=_dec(
                    comp, "PatrimonioFinPeriodoActual", c_loc),
                suscripciones_reembolsos_netos=_dec(
                    comp, "Suscripciones_Reembolsos_Netos", c_loc),
                beneficios_brutos_distribuidos=_dec(
                    comp, "BeneficiosBrutosDistribuidos", c_loc),
                rendimientos_netos=_dec(comp, "RendimientosNetos", c_loc),
                rendimientos_gestion=_dec(
                    comp, "RendimientosGestion", c_loc),
                intereses=_dec(comp, "Intereses", c_loc),
                dividendos=_dec(comp, "Dividendos", c_loc),
                resultados_renta_fija=_dec(
                    comp, "ResultadosRentaFija", c_loc),
                resultados_renta_variable=_dec(
                    comp, "ResultadosRentaVariable", c_loc),
                resultados_depositos=_dec(
                    comp, "ResultadosDepositos", c_loc),
                resultados_derivados=_dec(
                    comp, "ResultadosDerivados", c_loc),
                resultados_iic=_dec(comp, "ResultadosIIC", c_loc),
                otros_resultados=_dec(comp, "OtrosResultados", c_loc),
                otros_rendimientos=_dec(comp, "OtrosRendimientos", c_loc),
                gastos_repercutidos=_dec(
                    comp, "GastosRepercutidos", c_loc),
                comision_gestion=_dec(comp, "ComisionGestion", c_loc),
                comision_depositario=_dec(
                    comp, "ComisionDepositario", c_loc),
                gastos_servicios_exteriores=_dec(
                    comp, "GastosServiciosExteriores", c_loc),
                otros_gastos_gestion=_dec(
                    comp, "OtrosGastosGestion", c_loc),
                otros_gastos_repercutidos=_dec(
                    comp, "OtrosGastosRepercutidos", c_loc),
                ingresos=_dec(comp, "Ingresos", c_loc),
                comisiones_descuento=_dec(
                    comp, "ComisionesDescuento", c_loc),
                comisiones_retrocedidas=_dec(
                    comp, "ComisionesRetrocedidas", c_loc),
                otros_ingresos=_dec(comp, "OtrosIngresos", c_loc),
                registry_state=reg_state,
                period=period,
                provenance=Provenance(
                    source_artifact_id=artifact.source_id,
                    source_sha256=artifact.sha256,
                    member_name=member_name,
                    member_sha256=member_sha256,
                    xml_locator=c_loc,
                    parser=PARSER_NAME,
                    parser_version=PARSER_VERSION,
                ),
            ))
    return rows
