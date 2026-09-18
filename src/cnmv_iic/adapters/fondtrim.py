"""FONDTRIM adapter — XML instance -> ShareClassQuarterlyMetrics rows.

G4 scope (docs/g4/contract.md): verbatim quarterly metrics per share
class. The measured grain is uniformly class-level
(``NumeroClase=0`` = fund-level row, same convention as FONDMENS);
compartment-level (``VocacionInversora``, ``ClaseFondo``) and
entity-level (``CodigoDivisaIIC``) attributes are denormalized onto the
record with their source level documented in the domain type.

Observed-source semantics implemented here:

- ``None`` means the source element was absent (missing) — never an
  inferred value. Rolling-block containers may be present but empty and
  their T_1/T_2/T_3 sub-elements individually absent (insufficient
  history) — preserved as missing, never zero.
- ``0`` is a genuine observed value, NOT a sentinel (contrast with
  FONDMENS — measured: real 0.00 fees/returns throughout).
- Fees may be negative (``ComisionGestion``/``ComisionDepositario``
  negatives observed — rebates/credits): kept verbatim signed.
- Monetary fields are in the CLASS denomination currency
  (``codigo_divisa``), which is not always EUR — the raw currency field
  is preserved, never assumed.
- A present but non-numeric metric value fails closed with
  ``ParseError`` (none observed in ~11k cells across both era
  extremes; a real occurrence would be a schema deviation).
- ``registry_state`` records whether the class key exists in the
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
    Provenance,
    RegistryJoinState,
    ShareClassQuarterlyMetrics,
    classify_isin,
    share_class_key,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondtrim"
PARSER_VERSION = __version__
FAMILY = "FONDTRIM"


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


def _int(el: etree._Element, tag: str, locator: str) -> int | None:
    raw = text_of(el, tag)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ParseError(
            f"{FAMILY}: non-integer {tag}={raw!r} at {locator}"
        ) from exc


def _block(block: etree._Element | None, tag: str,
           locator: str) -> Decimal | None:
    if block is None:
        return None
    return _dec(block, tag, locator)


def parse_fondtrim(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
    registry_keys: frozenset[str] | None = None,
) -> list[ShareClassQuarterlyMetrics]:
    """Parse one FONDTRIM member into per-class quarterly metric rows.

    ``registry_keys``: share-class keys from the same-period FONDREGISTRO
    snapshot (exact join). ``None`` = no registry data ingested; every
    row is then marked ``unresolved_registry_reference``.
    """
    root = secure_parse(xml, FAMILY)
    assert_structure(FAMILY, root)
    period = parse_period(root, FAMILY)

    rows: list[ShareClassQuarterlyMetrics] = []
    seen: set[str] = set()
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondTrim/Entidad[{i}]"
        tipo = required_text(ent, "Tipo", FAMILY, e_loc)
        nreg = required_text(ent, "NumeroRegistro", FAMILY, e_loc)
        divisa_iic = text_of(ent, "CodigoDivisaIIC")
        for j, comp in enumerate(ent.findall("Compartimento"), start=1):
            c_loc = f"{e_loc}/Compartimento[{j}]"
            ncomp = required_text(comp, "NumeroCompartimento",
                                  FAMILY, c_loc)
            vocacion = text_of(comp, "VocacionInversora")
            clase_fondo = text_of(comp, "ClaseFondo")
            for k, cl in enumerate(comp.findall("Clase"), start=1):
                k_loc = f"{c_loc}/Clase[{k}]"
                nclase = required_text(cl, "NumeroClase", FAMILY, k_loc)
                key = share_class_key(tipo, nreg, ncomp, nclase)
                if key in seen:
                    raise ParseError(
                        f"{FAMILY}: duplicate class key {key} at {k_loc}")
                seen.add(key)
                reg_state = (
                    RegistryJoinState.RESOLVED
                    if registry_keys is not None and key in registry_keys
                    else RegistryJoinState.UNRESOLVED
                )
                isin_raw = text_of(cl, "ISIN")
                rent = cl.find("Rentabilidad")
                gastos = cl.find("RatioTotalGastos")
                vol = cl.find("Volatilidad_VL")
                rows.append(ShareClassQuarterlyMetrics(
                    entity_type=tipo,
                    numero_registro=nreg,
                    numero_compartimento=ncomp,
                    numero_clase=nclase,
                    isin_raw=isin_raw,
                    isin_state=classify_isin(isin_raw),
                    codigo_divisa=text_of(cl, "CodigoDivisa"),
                    periodicidad_calculo_vl=text_of(
                        cl, "PeriodicidadCalculoVL"),
                    base_calculo_comision_gestion=text_of(
                        cl, "BaseCalculo_ComisionGestion"),
                    sistema_imputacion_comisiones=text_of(
                        cl, "SistemaImputacionComisiones"),
                    patrimonio=_dec(cl, "Patrimonio", k_loc),
                    valor_liquidativo=_dec(cl, "ValorLiquidativo", k_loc),
                    numero_participaciones=_dec(
                        cl, "NumeroParticipaciones", k_loc),
                    numero_participes=_int(cl, "NumeroParticipes", k_loc),
                    beneficio_dividendo_bruto=_dec(
                        cl, "Beneficio_Dividendo_Bruto", k_loc),
                    comision_gestion=_dec(cl, "ComisionGestion", k_loc),
                    comision_depositario=_dec(
                        cl, "ComisionDepositario", k_loc),
                    comision_suscripcion_minima=_dec(
                        cl, "ComisionSuscripcionMinima", k_loc),
                    comision_suscripcion_maxima=_dec(
                        cl, "ComisionSuscripcionMaxima", k_loc),
                    comision_reembolso_minima=_dec(
                        cl, "ComisionReembolsoMinima", k_loc),
                    comision_reembolso_maxima=_dec(
                        cl, "ComisionReembolsoMaxima", k_loc),
                    comision_descuento_favor_fondo_minima=_dec(
                        cl, "ComisionDescuentoFavorFondoMinima", k_loc),
                    comision_descuento_favor_fondo_maxima=_dec(
                        cl, "ComisionDescuentoFavorFondoMaxima", k_loc),
                    official_return_t=_block(
                        rent, "Rentabilidad_TrimestreActual", k_loc),
                    official_return_t_1=_block(
                        rent, "Rentabilidad_T_1", k_loc),
                    official_return_t_2=_block(
                        rent, "Rentabilidad_T_2", k_loc),
                    official_return_t_3=_block(
                        rent, "Rentabilidad_T_3", k_loc),
                    ratio_total_gastos_t=_block(
                        gastos, "RatioTotalGastos_TrimestreActual", k_loc),
                    ratio_total_gastos_t_1=_block(
                        gastos, "RatioTotalGastos_T_1", k_loc),
                    ratio_total_gastos_t_2=_block(
                        gastos, "RatioTotalGastos_T_2", k_loc),
                    ratio_total_gastos_t_3=_block(
                        gastos, "RatioTotalGastos_T_3", k_loc),
                    volatilidad_vl_t=_block(
                        vol, "Volatilidad_TrimestreActual", k_loc),
                    volatilidad_vl_t_1=_block(
                        vol, "Volatilidad_T_1", k_loc),
                    volatilidad_vl_t_2=_block(
                        vol, "Volatilidad_T_2", k_loc),
                    volatilidad_vl_t_3=_block(
                        vol, "Volatilidad_T_3", k_loc),
                    vocacion_inversora=vocacion,
                    clase_fondo=clase_fondo,
                    codigo_divisa_iic=divisa_iic,
                    registry_state=reg_state,
                    period=period,
                    provenance=Provenance(
                        source_artifact_id=artifact.source_id,
                        source_sha256=artifact.sha256,
                        member_name=member_name,
                        member_sha256=member_sha256,
                        xml_locator=k_loc,
                        parser=PARSER_NAME,
                        parser_version=PARSER_VERSION,
                    ),
                ))
    return rows
