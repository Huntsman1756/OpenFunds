"""FONDDERI adapter — XML -> derivative-operation evidence rows.

G5 scope (docs/g5/contract.md): an evidence ledger, NOT a derivatives
normalization engine. The measured grain is
``(compartment_key, operation_ordinal)`` — the file contains ZERO
``Clase`` elements and ``OperativaDerivados`` repeats 0..N per
compartment.

Observed-source semantics implemented here:

- ``Descripcion`` is a documented closed enum (8 values) — verbatim
  label kept AND decomposed into ``side``/``underlier_class`` facets
  per the official explanatory document. An out-of-vocabulary value
  fails closed with ``ParseError``.
- ``Objetivo`` is a documented coded field (3 values) — typed enum;
  absent → ``None`` (1 occurrence in 49,522 ops, 2014-03).
- ``Subyacente``/``Instrumento`` are officially "texto no
  normalizado" — verbatim, NEVER regex-parsed into product type,
  underlier, expiry or side. Pipe-delimited and ``C/``-prefixed
  shapes are observable structure, not authoritative structure.
- ``Importe`` = "importe nominal comprometido expresado en euros"
  (official PDF) — committed nominal in EUR, ``Decimal``, signed;
  negatives observed (55 in 2012-03).
- Compartments present with zero ``OperativaDerivados`` yield a
  coverage row (explicitly reported no-derivatives state), not
  fabricated operation rows.
- ``registry_state`` records whether the compartment key exists in
  the same-period FONDREGISTRO snapshot —
  ``unresolved_registry_reference`` when it does not. No fuzzy
  matching, ever.
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
    DERI_DESCRIPCION_FACETS,
    DERI_OBJETIVO_VALUES,
    CompartmentDerivativeCoverage,
    CompartmentDerivativeOperation,
    DerivativeObjective,
    DerivativeRepresentation,
    DerivativeSide,
    Provenance,
    RegistryJoinState,
    UnderlierClass,
    compartment_key,
    fund_key,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondderi"
PARSER_VERSION = __version__
FAMILY = "FONDDERI"


def _descripcion(
    raw: str, locator: str,
) -> tuple[DerivativeSide, UnderlierClass]:
    facets = DERI_DESCRIPCION_FACETS.get(raw)
    if facets is None:
        raise ParseError(
            f"{FAMILY}: Descripcion {raw!r} outside the documented "
            f"closed enum at {locator}")
    return facets


def _objetivo(
    op: etree._Element, locator: str,
) -> DerivativeObjective | None:
    raw = text_of(op, "Objetivo")
    if raw is None:
        return None
    val = DERI_OBJETIVO_VALUES.get(raw)
    if val is None:
        raise ParseError(
            f"{FAMILY}: Objetivo {raw!r} outside the documented "
            f"closed enum at {locator}")
    return val


def _importe(op: etree._Element, locator: str) -> Decimal:
    raw = required_text(op, "Importe", FAMILY, locator)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(
            f"{FAMILY}: non-decimal Importe={raw!r} at {locator}"
        ) from exc


def parse_fondderi(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
    registry_compartment_keys: frozenset[str] | None = None,
) -> tuple[
    list[CompartmentDerivativeOperation],
    list[CompartmentDerivativeCoverage],
]:
    """Parse one FONDDERI member into operation + coverage rows.

    Returns ``(operations, coverage)``: one coverage row per reported
    compartment (``n_operations`` may be 0 — an explicitly reported
    no-derivatives state), one operation row per
    ``OperativaDerivados``.
    """
    root = secure_parse(xml, FAMILY)
    assert_structure(FAMILY, root)
    period = parse_period(root, FAMILY)

    ops: list[CompartmentDerivativeOperation] = []
    coverage: list[CompartmentDerivativeCoverage] = []
    seen: set[str] = set()
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondDeri/Entidad[{i}]"
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
                    f"{FAMILY}: duplicate compartment key {key} "
                    f"at {c_loc}")
            seen.add(key)
            reg_state = (
                RegistryJoinState.RESOLVED
                if registry_compartment_keys is not None
                and key in registry_compartment_keys
                else RegistryJoinState.UNRESOLVED
            )
            prov = Provenance(
                source_artifact_id=artifact.source_id,
                source_sha256=artifact.sha256,
                member_name=member_name,
                member_sha256=member_sha256,
                xml_locator=c_loc,
                parser=PARSER_NAME,
                parser_version=PARSER_VERSION,
            )
            comp_ops = comp.findall("OperativaDerivados")
            coverage.append(CompartmentDerivativeCoverage(
                compartment_key=key,
                fund_key=fund_key(tipo, nreg),
                entity_type=tipo,
                numero_registro=nreg,
                numero_compartimento=ncomp,
                codigo_divisa_iic=divisa_iic,
                n_operations=len(comp_ops),
                registry_state=reg_state,
                period=period,
                provenance=prov,
            ))
            for k, op in enumerate(comp_ops, start=1):
                o_loc = f"{c_loc}/OperativaDerivados[{k}]"
                desc = required_text(op, "Descripcion", FAMILY, o_loc)
                side, underlier = _descripcion(desc, o_loc)
                objetivo = _objetivo(op, o_loc)
                ops.append(CompartmentDerivativeOperation(
                    entity_type=tipo,
                    numero_registro=nreg,
                    numero_compartimento=ncomp,
                    operation_index=k,
                    descripcion=desc,
                    side=side,
                    underlier_class=underlier,
                    subyacente=required_text(
                        op, "Subyacente", FAMILY, o_loc),
                    instrumento=required_text(
                        op, "Instrumento", FAMILY, o_loc),
                    importe=_importe(op, o_loc),
                    objetivo=objetivo,
                    codigo_divisa_iic=divisa_iic,
                    representation=(
                        DerivativeRepresentation.PARTIALLY_STRUCTURED),
                    registry_state=reg_state,
                    period=period,
                    provenance=Provenance(
                        source_artifact_id=artifact.source_id,
                        source_sha256=artifact.sha256,
                        member_name=member_name,
                        member_sha256=member_sha256,
                        xml_locator=o_loc,
                        parser=PARSER_NAME,
                        parser_version=PARSER_VERSION,
                    ),
                ))
    return ops, coverage
