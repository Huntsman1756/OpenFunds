"""FONDMENS adapter — XML instance -> ShareClassDailyObservation rows.

G3 scope (docs/g3/contract.md): verbatim daily VL / patrimonio / participes
per share class. The grain is (share_class_key, observation_date) — never
collapsed to the compartment portfolio owner.

Observed-source semantics implemented here:

- ``FechaDatos`` is YYYYMM; ``observation_date`` = year-month + DiaN for
  N <= calendar month length. Day elements beyond the month length are
  impossible days (serialized as '0') and are REJECTED — not emitted.
- ``'0'`` on a valid day is a no-observation sentinel (zero interior zeros
  measured across ~2.6M cells; boundary-only pattern). It is preserved
  verbatim in ``raw`` with state ``source_zero_sentinel`` and a NULL clean
  value. The reason for absence is never inferred.
- A missing day element or a wholly missing metric block yields state
  ``missing`` with NULL value and NULL raw.
- A present but non-numeric value yields state ``invalid`` — the raw text
  is preserved, the value stays NULL. (Structural violations still fail
  closed via ``assert_structure``.)
- Patrimonio may be negative (observed in 2025-12): kept as ``observed``.
- ``registry_state`` records whether the class key exists in the
  same-period FONDREGISTRO snapshot — ``unresolved_registry_reference``
  when it does not. No fuzzy matching, ever.
"""

from __future__ import annotations

import calendar
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
    MetricObservation,
    ObservationState,
    Provenance,
    RegistryJoinState,
    ShareClassDailyObservation,
    classify_isin,
    share_class_key,
)
from cnmv_iic.errors import ParseError
from cnmv_iic.schemas.registry import assert_structure

if TYPE_CHECKING:
    from cnmv_iic.artifacts.store import SourceArtifact

PARSER_NAME = "cnmv_iic.adapters.fondmens"
PARSER_VERSION = __version__
FAMILY = "FONDMENS"

_METRICS = (
    # (block element, day element prefix)
    ("VLDiario", "VL_Dia"),
    ("PatrimonioDiario", "Patrimonio_Dia"),
    ("ParticipesDiario", "Participes_Dia"),
)


def _metric(block: etree._Element | None, prefix: str, day: int,
            *, integer: bool) -> MetricObservation:
    if block is None:
        return MetricObservation(value=None, raw=None,
                                 state=ObservationState.MISSING)
    raw = text_of(block, f"{prefix}{day}")
    if raw is None:
        return MetricObservation(value=None, raw=None,
                                 state=ObservationState.MISSING)
    if raw == "0":
        return MetricObservation(value=None, raw=raw,
                                 state=ObservationState.SOURCE_ZERO_SENTINEL)
    try:
        value: Decimal | int = int(raw) if integer else Decimal(raw)
    except (InvalidOperation, ValueError):
        return MetricObservation(value=None, raw=raw,
                                 state=ObservationState.INVALID)
    return MetricObservation(value=value, raw=raw,
                             state=ObservationState.OBSERVED)


def parse_fondmens(
    xml: bytes,
    *,
    artifact: SourceArtifact,
    member_name: str,
    member_sha256: str,
    registry_keys: frozenset[str] | None = None,
) -> list[ShareClassDailyObservation]:
    """Parse one FONDMENS member into per-day share-class observations.

    ``registry_keys``: share-class keys from the same-period FONDREGISTRO
    snapshot (exact join). ``None`` = no registry data ingested; every row
    is then marked ``unresolved_registry_reference`` honestly rather than
    pretending a join happened.
    """
    root = secure_parse(xml, FAMILY)
    assert_structure(FAMILY, root)
    period = parse_period(root, FAMILY)
    year, month = int(period[:4]), int(period[5:7])
    month_len = calendar.monthrange(year, month)[1]

    rows: list[ShareClassDailyObservation] = []
    seen: set[str] = set()
    for i, ent in enumerate(root.iter("Entidad"), start=1):
        e_loc = f"FondMens/Entidad[{i}]"
        tipo = required_text(ent, "Tipo", FAMILY, e_loc)
        nreg = required_text(ent, "NumeroRegistro", FAMILY, e_loc)
        for j, comp in enumerate(ent.findall("Compartimento"), start=1):
            c_loc = f"{e_loc}/Compartimento[{j}]"
            ncomp = required_text(comp, "NumeroCompartimento", FAMILY, c_loc)
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
                blocks = {
                    prefix: cl.find(block) for block, prefix in _METRICS
                }
                for day in range(1, month_len + 1):
                    rows.append(ShareClassDailyObservation(
                        entity_type=tipo,
                        numero_registro=nreg,
                        numero_compartimento=ncomp,
                        numero_clase=nclase,
                        isin_raw=isin_raw,
                        isin_state=classify_isin(isin_raw),
                        observation_date=f"{year:04d}-{month:02d}-{day:02d}",
                        day_index=day,
                        nav=_metric(blocks["VL_Dia"], "VL_Dia", day,
                                    integer=False),
                        aum=_metric(blocks["Patrimonio_Dia"],
                                    "Patrimonio_Dia", day, integer=False),
                        investors=_metric(blocks["Participes_Dia"],
                                          "Participes_Dia", day,
                                          integer=True),
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
