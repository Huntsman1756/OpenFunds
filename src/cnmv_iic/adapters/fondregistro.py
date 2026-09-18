"""FONDREGISTRO adapter — XML instance -> FundRecords (regulatory identity).

G2 scope: verbatim registry identity only — type, registro, denominacion,
ETF flag, gestora/grupo, depositario/grupo, compartimentos, share classes
with ISINs. Nothing inferred, nothing forward-filled.

Required elements: Tipo, NumeroRegistro, NumeroCompartimento, NumeroClase.
All denominaciones / institution numbers may be absent (recorded as None);
no deviation of that kind was observed in 2012-03 or 2025-12 but they are
not identity keys, so absence is preserved rather than rejected.
ISIN absence is also preserved (isin_state=absent) — never synthesized.
"""

from __future__ import annotations

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
    Compartment,
    FundRecord,
    Institution,
    Provenance,
    ShareClass,
    classify_isin,
)
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondregistro"
PARSER_VERSION = __version__
FAMILY = "FONDREGISTRO"


def _institution(el: etree._Element, kind: str) -> Institution:
    return Institution(
        numero_registro=text_of(el, f"NumeroRegistro{kind}"),
        denominacion=text_of(el, f"Denominacion{kind}"),
        tipo=text_of(el, f"Tipo{kind}"),
        grupo_numero=text_of(el, f"Grupo{kind}/NumeroGrupo{kind}"),
        grupo_denominacion=text_of(el, f"Grupo{kind}/DenominacionGrupo{kind}"),
    )


def parse_fondregistro(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
) -> list[FundRecord]:
    """Parse one FONDREGISTRO member into per-entity FundRecords."""
    root = secure_parse(xml, FAMILY)
    assert_structure(FAMILY, root)
    period = parse_period(root, FAMILY)

    records: list[FundRecord] = []
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondRegistro/Entidad[{i}]"
        tipo = required_text(ent, "Tipo", FAMILY, e_loc)
        nreg = required_text(ent, "NumeroRegistro", FAMILY, e_loc)
        prov = Provenance(
            source_artifact_id=artifact.source_id,
            source_sha256=artifact.sha256,
            member_name=member_name,
            member_sha256=member_sha256,
            xml_locator=e_loc,
            parser=PARSER_NAME,
            parser_version=PARSER_VERSION,
        )
        comps: list[Compartment] = []
        for j, comp in enumerate(ent.findall("Compartimento"), start=1):
            c_loc = f"{e_loc}/Compartimento[{j}]"
            ncomp = required_text(
                comp, "NumeroCompartimento", FAMILY, c_loc
            )
            classes: list[ShareClass] = []
            for k, cl in enumerate(comp.findall("Clase"), start=1):
                k_loc = f"{c_loc}/Clase[{k}]"
                nclase = required_text(cl, "NumeroClase", FAMILY, k_loc)
                isin_raw = text_of(cl, "ISIN")
                classes.append(ShareClass(
                    numero_clase=nclase,
                    isin_raw=isin_raw,
                    isin_state=classify_isin(isin_raw),
                    denominacion=text_of(cl, "DenominacionClase"),
                ))
            comps.append(Compartment(
                numero_compartimento=ncomp,
                denominacion=text_of(comp, "DenominacionCompartimento"),
                classes=tuple(classes),
            ))
        gest = ent.find("Gestora")
        dep = ent.find("Depositario")
        records.append(FundRecord(
            entity_type=tipo,
            numero_registro=nreg,
            denominacion=text_of(ent, "Denominacion"),
            etf=text_of(ent, "ETF"),
            gestora=_institution(gest, "Gestora") if gest is not None
            else Institution(None, None),
            depositario=_institution(dep, "Depositario") if dep is not None
            else Institution(None, None),
            compartments=tuple(comps),
            period=period,
            provenance=prov,
        ))
    return records
