"""FONDCART adapter — XML instance -> canonical PortfolioSnapshots.

Security (fail-closed):
- DOCTYPE rejected outright (no DTD processing ever)
- lxml parser: no entity resolution, no network, no XInclude
- every element path must be in the registry (assert_structure)
- all leaf elements required EXCEPT CodigoISIN (registered deviation:
  absent on deposit positions)

Semantics:
- ValorMercado parsed with Decimal, never float
- DescripcionValor kept verbatim — never split or re-interpreted
- only DescripcionIF == 'Depositos' -> PositionKind.CASH; every other
  (including unrecognized future labels) -> SECURITY with raw label
- derived_weight computed over the snapshot's reported total
"""

from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Literal

from lxml import etree

from cnmv_iic import __version__
from cnmv_iic.domain import (
    FundIdentity,
    PortfolioSnapshot,
    Position,
    PositionKind,
    Provenance,
    QualityObservation,
    classify_isin,
)
from cnmv_iic.errors import ParseError, UnsupportedSchemaError
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondcart"
PARSER_VERSION = __version__
FAMILY = "FONDCART"

RECON_TOLERANCE = Decimal("0.001")  # 0.1% relative, per G0 criteria


def _secure_parse(xml: bytes) -> etree._Element:
    head = xml[:2048].lstrip()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise ParseError("DOCTYPE/ENTITY declarations rejected")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        recover=False,
        huge_tree=False,
    )
    try:
        return etree.parse(io.BytesIO(xml), parser).getroot()
    except etree.XMLSyntaxError as exc:
        raise ParseError(f"XML syntax error: {exc}") from exc


def _text(el: etree._Element, tag: str) -> str | None:
    child = el.find(tag)
    if child is None or child.text is None:
        return None
    v = child.text.strip()
    return v or None


def _required(el: etree._Element, tag: str, locator: str) -> str:
    if el.find(tag) is None:
        raise UnsupportedSchemaError(
            f"{FAMILY}: required element {tag} absent at {locator}"
        )
    v = _text(el, tag)
    if v is None:
        raise ParseError(f"{FAMILY}: empty {tag} at {locator}")
    return v


def _decimal(el: etree._Element, tag: str, locator: str) -> Decimal:
    raw = _required(el, tag, locator)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ParseError(f"{FAMILY}: non-decimal {tag}={raw!r} at {locator}") from exc


def parse_fecha_datos(root: etree._Element) -> str:
    raw = _text(root, "FechaDatos")
    if raw is None or len(raw) != 6 or not raw.isdigit():
        raise ParseError(f"FONDCART: bad FechaDatos {raw!r}")
    month = int(raw[4:6])
    if not 1 <= month <= 12:
        raise ParseError(f"FONDCART: bad FechaDatos month {raw!r}")
    return f"{raw[:4]}-{raw[4:6]}"


def parse_fondcart(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
) -> list[PortfolioSnapshot]:
    """Parse one FONDCART member into per-compartimento snapshots."""
    root = _secure_parse(xml)
    assert_structure(FAMILY, root)
    period = parse_fecha_datos(root)

    snapshots: list[PortfolioSnapshot] = []
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondCart/Entidad[{i}]"
        tipo = _required(ent, "Tipo", e_loc)
        nreg = _required(ent, "NumeroRegistro", e_loc)
        for j, comp in enumerate(ent.findall("Compartimento"), start=1):
            c_loc = f"{e_loc}/Compartimento[{j}]"
            ncomp = _required(comp, "NumeroCompartimento", c_loc)
            identity = FundIdentity(tipo, nreg, ncomp)
            positions: list[Position] = []
            for k, inv in enumerate(
                comp.findall("InversionesFinancieras"), start=1
            ):
                p_loc = f"{c_loc}/InversionesFinancieras[{k}]"
                clase = _required(inv, "ClaseIF", p_loc)
                desc_if = _required(inv, "DescripcionIF", p_loc)
                desc_val = _text(inv, "DescripcionValor")
                divisa = _text(inv, "Divisa")
                if inv.find("DescripcionValor") is None:
                    raise UnsupportedSchemaError(
                        f"{FAMILY}: required element DescripcionValor "
                        f"absent at {p_loc}"
                    )
                # Divisa absence: registered deviation (17 obs., 2012-03 only)
                vm = _decimal(inv, "ValorMercado", p_loc)
                isin_raw = _text(inv, "CodigoISIN")
                kind = (PositionKind.CASH if desc_if == "Depositos"
                        else PositionKind.SECURITY)
                positions.append(Position(
                    kind=kind,
                    clase_if=clase,
                    descripcion_if=desc_if,
                    descripcion_valor=desc_val,
                    divisa=divisa,
                    reported_market_value=vm,
                    isin_raw=isin_raw,
                    isin_state=classify_isin(isin_raw),
                    provenance=Provenance(
                        source_artifact_id=artifact.source_id,
                        source_sha256=artifact.sha256,
                        member_name=member_name,
                        member_sha256=member_sha256,
                        xml_locator=p_loc,
                        parser=PARSER_NAME,
                        parser_version=PARSER_VERSION,
                    ),
                ))
            total = sum(
                (p.reported_market_value for p in positions
                 if p.reported_market_value is not None),
                Decimal(0),
            )
            if total != 0:
                positions = [
                    Position(
                        kind=p.kind, clase_if=p.clase_if,
                        descripcion_if=p.descripcion_if,
                        descripcion_valor=p.descripcion_valor, divisa=p.divisa,
                        reported_market_value=p.reported_market_value,
                        isin_raw=p.isin_raw, isin_state=p.isin_state,
                        provenance=p.provenance,
                        derived_weight=(p.reported_market_value / total
                                        if p.reported_market_value is not None
                                        else None),
                    )
                    for p in positions
                ]
            snapshots.append(PortfolioSnapshot(
                identity=identity,
                period=period,
                positions=tuple(positions),
            ))
    return snapshots


def reconcile(
    snaps: list[PortfolioSnapshot],
    pdv_xml: bytes | None,
) -> None:
    """Attach QualityObservations reconciling cart sum vs FONDPATRIMDISVAR.

    Reconciliation is at entity level (Tipo+NumeroRegistro), matching the
    G0 methodology: sum of (CarteraInterior+CarteraExterior+
    InversionesDudosas) across the entity's compartimentos.
    Divergent entities are kept — the state is data.
    """
    if pdv_xml is None:
        return
    root = _secure_parse(pdv_xml)
    assert_structure("FONDPATRIMDISVAR", root)
    pdv_totals: dict[tuple[str, str], Decimal] = {}
    for ent in root.iter("Entidad"):
        key = (ent.findtext("Tipo") or "", ent.findtext("NumeroRegistro") or "")
        total = Decimal(0)
        for comp in ent.findall("Compartimento"):
            for tag in ("CarteraInterior", "CarteraExterior", "InversionesDudosas"):
                v = comp.findtext(tag)
                if v:
                    total += Decimal(v.strip())
        pdv_totals[key] = pdv_totals.get(key, Decimal(0)) + total

    cart_totals: dict[tuple[str, str], Decimal] = {}
    for snap in snaps:
        key = (snap.identity.entity_type, snap.identity.numero_registro)
        cart_totals[key] = cart_totals.get(key, Decimal(0)) + snap.reported_total

    obs_by_key: dict[tuple[str, str], QualityObservation] = {}
    for key, cart_sum in cart_totals.items():
        pdv_sum = pdv_totals.get(key)
        if pdv_sum is None:
            obs_by_key[key] = QualityObservation(
                metric="fondcart_vs_patrimdisvar",
                cart_sum=cart_sum, pdv_sum=Decimal(0),
                abs_diff=cart_sum, rel_diff=None,
                tolerance=RECON_TOLERANCE,
                state="unreconcilable",
                note="entity absent from FONDPATRIMDISVAR",
            )
            continue
        diff = abs(cart_sum - pdv_sum)
        rel = diff / abs(pdv_sum) if pdv_sum != 0 else None
        state: Literal["exact", "within_tolerance", "divergent"]
        if diff == 0:
            state = "exact"
        elif rel is not None and rel < RECON_TOLERANCE:
            state = "within_tolerance"
        else:
            state = "divergent"
        obs_by_key[key] = QualityObservation(
            metric="fondcart_vs_patrimdisvar",
            cart_sum=cart_sum, pdv_sum=pdv_sum, abs_diff=diff,
            rel_diff=rel, tolerance=RECON_TOLERANCE, state=state,
        )
    for idx, snap in enumerate(snaps):
        key = (snap.identity.entity_type, snap.identity.numero_registro)
        if key in obs_by_key:
            snaps[idx] = PortfolioSnapshot(
                identity=snap.identity, period=snap.period,
                positions=snap.positions, quality=(obs_by_key[key],),
            )
