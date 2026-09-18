"""Deterministic Parquet export + canonical dataset fingerprint.

Determinism contract (user gate 6):
- Rows are emitted in a canonical sort order:
  (entity_type, numero_registro, numero_compartimento, position_seq).
- ``dataset_fingerprint`` = SHA-256 over a canonical text serialization of
  every row of both tables — independent of Parquet metadata, so identical
  logical content fingerprints identically even if the byte stream varies.
- OBSERVED money is decimal128(38,2) — exact (source is always scale-2).
- DERIVED values (weight, rel_diff) are decimal128(38,18), ROUND_HALF_EVEN —
  deterministic, documented as derived.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal
from hashlib import sha256
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from cnmv_iic.domain import (
    CompartmentPatrimonySnapshot,
    FundRecord,
    PortfolioSnapshot,
    ShareClassDailyObservation,
    ShareClassQuarterlyMetrics,
)

Q18 = Decimal(1).scaleb(-18)
DERIVED_QUANT = Q18

POSITIONS_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("fund_key", pa.string()),
    ("position_seq", pa.int32()),
    ("kind", pa.string()),
    ("clase_if", pa.string()),
    ("descripcion_if", pa.string()),
    ("descripcion_valor", pa.string()),
    ("divisa", pa.string()),
    ("reported_market_value", pa.decimal128(38, 2)),
    ("derived_weight", pa.decimal128(38, 18)),
    ("isin_raw", pa.string()),
    ("isin_state", pa.string()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("member_name", pa.string()),
    ("member_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

FUNDS_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("fund_key", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("denominacion", pa.string()),
    ("etf", pa.string()),
    ("gestora_numero_registro", pa.string()),
    ("gestora_denominacion", pa.string()),
    ("gestora_tipo", pa.string()),
    ("grupo_gestora_numero", pa.string()),
    ("grupo_gestora_denominacion", pa.string()),
    ("depositario_numero_registro", pa.string()),
    ("depositario_denominacion", pa.string()),
    ("grupo_depositario_numero", pa.string()),
    ("grupo_depositario_denominacion", pa.string()),
    ("n_compartments", pa.int32()),
    ("n_share_classes", pa.int32()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

COMPARTMENTS_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("compartment_key", pa.string()),   # = portfolio_owner_key in FONDCART
    ("fund_key", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("denominacion", pa.string()),
    ("n_classes", pa.int32()),
    ("source_artifact_id", pa.string()),
])

SHARE_CLASSES_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("share_class_key", pa.string()),
    ("fund_key", pa.string()),
    ("compartment_key", pa.string()),   # portfolio_owner_key
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("numero_clase", pa.string()),
    ("isin_raw", pa.string()),
    ("isin_state", pa.string()),
    ("denominacion_clase", pa.string()),
    ("denominacion_compartimento", pa.string()),
    ("source_artifact_id", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

DAILY_SCHEMA = pa.schema([
    ("period", pa.string()),                 # observed_period YYYY-MM
    ("share_class_key", pa.string()),
    ("compartment_key", pa.string()),
    ("fund_key", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("numero_clase", pa.string()),
    ("isin_raw", pa.string()),
    ("isin_state", pa.string()),
    ("observation_date", pa.date32()),
    ("day_index", pa.int32()),
    ("nav", pa.decimal128(38, 4)),           # NULL unless nav_state=observed
    ("nav_raw", pa.string()),
    ("nav_state", pa.string()),
    ("aum", pa.decimal128(38, 2)),
    ("aum_raw", pa.string()),
    ("aum_state", pa.string()),
    ("investors", pa.int64()),
    ("investors_raw", pa.string()),
    ("investors_state", pa.string()),
    ("registry_state", pa.string()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("member_name", pa.string()),
    ("member_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

QUARTERLY_SCHEMA = pa.schema([
    ("period", pa.string()),                 # observed_period YYYY-MM
    ("share_class_key", pa.string()),
    ("compartment_key", pa.string()),
    ("fund_key", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("numero_clase", pa.string()),
    ("isin_raw", pa.string()),
    ("isin_state", pa.string()),
    # class metadata (verbatim enums)
    ("codigo_divisa", pa.string()),          # unit of monetary fields
    ("periodicidad_calculo_vl", pa.string()),
    ("base_calculo_comision_gestion", pa.string()),
    ("sistema_imputacion_comisiones", pa.string()),
    # stock metrics — monetary, class currency (measured scales)
    ("patrimonio", pa.decimal128(38, 2)),
    ("valor_liquidativo", pa.decimal128(38, 4)),
    ("numero_participaciones", pa.decimal128(38, 2)),
    ("numero_participes", pa.int64()),
    ("beneficio_dividendo_bruto", pa.decimal128(38, 4)),
    # fees — % accrued in period (signed; negatives observed)
    ("comision_gestion", pa.decimal128(38, 2)),
    ("comision_depositario", pa.decimal128(38, 2)),
    ("comision_suscripcion_minima", pa.decimal128(38, 2)),
    ("comision_suscripcion_maxima", pa.decimal128(38, 2)),
    ("comision_reembolso_minima", pa.decimal128(38, 2)),
    ("comision_reembolso_maxima", pa.decimal128(38, 2)),
    ("comision_descuento_favor_fondo_minima", pa.decimal128(38, 2)),
    ("comision_descuento_favor_fondo_maxima", pa.decimal128(38, 2)),
    # official CNMV returns — non-annualized %, T/T-1/T-2/T-3
    ("official_return_t", pa.decimal128(38, 2)),
    ("official_return_t_1", pa.decimal128(38, 2)),
    ("official_return_t_2", pa.decimal128(38, 2)),
    ("official_return_t_3", pa.decimal128(38, 2)),
    # operating-expense ratio — % of avg daily patrimonio (NOT "TER")
    ("ratio_total_gastos_t", pa.decimal128(38, 2)),
    ("ratio_total_gastos_t_1", pa.decimal128(38, 2)),
    ("ratio_total_gastos_t_2", pa.decimal128(38, 2)),
    ("ratio_total_gastos_t_3", pa.decimal128(38, 2)),
    # historical NAV volatility — %
    ("volatilidad_vl_t", pa.decimal128(38, 2)),
    ("volatilidad_vl_t_1", pa.decimal128(38, 2)),
    ("volatilidad_vl_t_2", pa.decimal128(38, 2)),
    ("volatilidad_vl_t_3", pa.decimal128(38, 2)),
    # compartment/entity-level attributes (denormalized, verbatim)
    ("vocacion_inversora", pa.string()),
    ("clase_fondo", pa.string()),
    ("codigo_divisa_iic", pa.string()),
    ("registry_state", pa.string()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("member_name", pa.string()),
    ("member_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

PATRIMONY_SCHEMA = pa.schema([
    ("period", pa.string()),                 # observed_period YYYY-MM
    ("compartment_key", pa.string()),        # = portfolio_owner_key
    ("fund_key", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("codigo_divisa_iic", pa.string()),      # unit of the stock fields
    # ratios (turnover index)
    ("indice_rotacion_cartera_actual", pa.decimal128(38, 2)),
    ("indice_rotacion_cartera_anterior", pa.decimal128(38, 2)),
    # stock — monetary, IIC currency
    ("dp_inversiones_financieras", pa.decimal128(38, 2)),
    ("cartera_interior", pa.decimal128(38, 2)),
    ("cartera_exterior", pa.decimal128(38, 2)),
    ("intereses_cartera", pa.decimal128(38, 2)),
    ("inversiones_dudosas", pa.decimal128(38, 2)),
    ("liquidez", pa.decimal128(38, 2)),
    ("resto", pa.decimal128(38, 2)),
    ("total_patrimonio", pa.decimal128(38, 2)),
    ("patrimonio_fin_periodo_anterior", pa.decimal128(38, 2)),
    ("patrimonio_fin_periodo_actual", pa.decimal128(38, 2)),
    # flow — SIGNED % over avg daily patrimonio (NOT money)
    ("suscripciones_reembolsos_netos", pa.decimal128(38, 2)),
    ("beneficios_brutos_distribuidos", pa.decimal128(38, 2)),
    ("rendimientos_netos", pa.decimal128(38, 2)),
    ("rendimientos_gestion", pa.decimal128(38, 2)),
    ("intereses", pa.decimal128(38, 2)),
    ("dividendos", pa.decimal128(38, 2)),
    ("resultados_renta_fija", pa.decimal128(38, 2)),
    ("resultados_renta_variable", pa.decimal128(38, 2)),
    ("resultados_depositos", pa.decimal128(38, 2)),
    ("resultados_derivados", pa.decimal128(38, 2)),
    ("resultados_iic", pa.decimal128(38, 2)),
    ("otros_resultados", pa.decimal128(38, 2)),
    ("otros_rendimientos", pa.decimal128(38, 2)),
    ("gastos_repercutidos", pa.decimal128(38, 2)),
    ("comision_gestion", pa.decimal128(38, 2)),
    ("comision_depositario", pa.decimal128(38, 2)),
    ("gastos_servicios_exteriores", pa.decimal128(38, 2)),
    ("otros_gastos_gestion", pa.decimal128(38, 2)),
    ("otros_gastos_repercutidos", pa.decimal128(38, 2)),
    ("ingresos", pa.decimal128(38, 2)),
    ("comisiones_descuento", pa.decimal128(38, 2)),
    ("comisiones_retrocedidas", pa.decimal128(38, 2)),
    ("otros_ingresos", pa.decimal128(38, 2)),
    ("registry_state", pa.string()),
    ("source_artifact_id", pa.string()),
    ("source_sha256", pa.string()),
    ("member_name", pa.string()),
    ("member_sha256", pa.string()),
    ("xml_locator", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])

QUALITY_SCHEMA = pa.schema([
    ("period", pa.string()),
    ("entity_type", pa.string()),
    ("numero_registro", pa.string()),
    ("numero_compartimento", pa.string()),
    ("metric", pa.string()),
    ("cart_sum", pa.decimal128(38, 2)),
    ("pdv_sum", pa.decimal128(38, 2)),
    ("abs_diff", pa.decimal128(38, 2)),
    ("rel_diff", pa.decimal128(38, 18)),
    ("tolerance", pa.decimal128(38, 6)),
    ("state", pa.string()),
    ("note", pa.string()),
    ("source_artifact_id", pa.string()),
    ("parser", pa.string()),
    ("parser_version", pa.string()),
])


def _quant(v: Decimal | None, q: Decimal = DERIVED_QUANT) -> Decimal | None:
    return v.quantize(q, rounding=ROUND_HALF_EVEN) if v is not None else None


def position_rows(snaps: list[PortfolioSnapshot]) -> list[dict]:
    rows = []
    for snap in snaps:
        for seq, p in enumerate(snap.positions, start=1):
            rows.append({
                "period": snap.period,
                "entity_type": snap.identity.entity_type,
                "numero_registro": snap.identity.numero_registro,
                "numero_compartimento": snap.identity.numero_compartimento,
                "fund_key": snap.identity.key,
                "position_seq": seq,
                "kind": p.kind.value,
                "clase_if": p.clase_if,
                "descripcion_if": p.descripcion_if,
                "descripcion_valor": p.descripcion_valor,
                "divisa": p.divisa,
                "reported_market_value": p.reported_market_value,
                "derived_weight": _quant(p.derived_weight),
                "isin_raw": p.isin_raw,
                "isin_state": p.isin_state.value,
                "source_artifact_id": p.provenance.source_artifact_id,
                "source_sha256": p.provenance.source_sha256,
                "member_name": p.provenance.member_name,
                "member_sha256": p.provenance.member_sha256,
                "xml_locator": p.provenance.xml_locator,
                "parser": p.provenance.parser,
                "parser_version": p.provenance.parser_version,
            })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6), int(str(r["position_seq"])),
    ))
    return rows


def quality_rows(snaps: list[PortfolioSnapshot]) -> list[dict]:
    rows = []
    for snap in snaps:
        for q in snap.quality:
            rows.append({
                "period": snap.period,
                "entity_type": snap.identity.entity_type,
                "numero_registro": snap.identity.numero_registro,
                "numero_compartimento": snap.identity.numero_compartimento,
                "metric": q.metric,
                "cart_sum": q.cart_sum,
                "pdv_sum": q.pdv_sum,
                "abs_diff": q.abs_diff,
                "rel_diff": _quant(q.rel_diff),
                "tolerance": q.tolerance,
                "state": q.state,
                "note": q.note,
                "source_artifact_id": snap.positions[0].provenance.source_artifact_id
                if snap.positions else None,
                "parser": snap.positions[0].provenance.parser
                if snap.positions else None,
                "parser_version": snap.positions[0].provenance.parser_version
                if snap.positions else None,
            })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6), str(r["metric"]),
    ))
    return rows


def fund_rows(records: list[FundRecord]) -> list[dict]:
    rows = []
    for r in records:
        n_classes = sum(len(c.classes) for c in r.compartments)
        rows.append({
            "period": r.period,
            "fund_key": r.key,
            "entity_type": r.entity_type,
            "numero_registro": r.numero_registro,
            "denominacion": r.denominacion,
            "etf": r.etf,
            "gestora_numero_registro": r.gestora.numero_registro,
            "gestora_denominacion": r.gestora.denominacion,
            "gestora_tipo": r.gestora.tipo,
            "grupo_gestora_numero": r.gestora.grupo_numero,
            "grupo_gestora_denominacion": r.gestora.grupo_denominacion,
            "depositario_numero_registro": r.depositario.numero_registro,
            "depositario_denominacion": r.depositario.denominacion,
            "grupo_depositario_numero": r.depositario.grupo_numero,
            "grupo_depositario_denominacion": r.depositario.grupo_denominacion,
            "n_compartments": len(r.compartments),
            "n_share_classes": n_classes,
            "source_artifact_id": r.provenance.source_artifact_id,
            "source_sha256": r.provenance.source_sha256,
            "xml_locator": r.provenance.xml_locator,
            "parser": r.provenance.parser,
            "parser_version": r.provenance.parser_version,
        })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12)))
    return rows


def compartment_rows(records: list[FundRecord]) -> list[dict]:
    rows = []
    for r in records:
        for c in r.compartments:
            rows.append({
                "period": r.period,
                "compartment_key": (
                    f"{r.entity_type}:{r.numero_registro}:"
                    f"{c.numero_compartimento}"
                ),
                "fund_key": r.key,
                "entity_type": r.entity_type,
                "numero_registro": r.numero_registro,
                "numero_compartimento": c.numero_compartimento,
                "denominacion": c.denominacion,
                "n_classes": len(c.classes),
                "source_artifact_id": r.provenance.source_artifact_id,
            })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6)))
    return rows


def share_class_rows(records: list[FundRecord]) -> list[dict]:
    rows = []
    for r in records:
        for j, c in enumerate(r.compartments, start=1):
            ck = f"{r.entity_type}:{r.numero_registro}:{c.numero_compartimento}"
            for k, cl in enumerate(c.classes, start=1):
                rows.append({
                    "period": r.period,
                    "share_class_key": f"{ck}:{cl.numero_clase}",
                    "fund_key": r.key,
                    "compartment_key": ck,
                    "entity_type": r.entity_type,
                    "numero_registro": r.numero_registro,
                    "numero_compartimento": c.numero_compartimento,
                    "numero_clase": cl.numero_clase,
                    "isin_raw": cl.isin_raw,
                    "isin_state": cl.isin_state.value,
                    "denominacion_clase": cl.denominacion,
                    "denominacion_compartimento": c.denominacion,
                    "source_artifact_id": r.provenance.source_artifact_id,
                    "xml_locator": (
                        f"{r.provenance.xml_locator}"
                        f"/Compartimento[{j}]/Clase[{k}]"
                    ),
                    "parser": r.provenance.parser,
                    "parser_version": r.provenance.parser_version,
                })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6),
        str(r["numero_clase"]).zfill(6)))
    return rows


def daily_rows(obs: list[ShareClassDailyObservation]) -> list[dict]:
    rows = []
    for o in obs:
        p = o.provenance
        rows.append({
            "period": o.period,
            "share_class_key": o.share_class_key,
            "compartment_key": o.compartment_key,
            "fund_key": o.fund_key,
            "entity_type": o.entity_type,
            "numero_registro": o.numero_registro,
            "numero_compartimento": o.numero_compartimento,
            "numero_clase": o.numero_clase,
            "isin_raw": o.isin_raw,
            "isin_state": o.isin_state.value,
            "observation_date": date.fromisoformat(o.observation_date),
            "day_index": o.day_index,
            "nav": o.nav.value if isinstance(o.nav.value, Decimal) else None,
            "nav_raw": o.nav.raw,
            "nav_state": o.nav.state.value,
            "aum": o.aum.value if isinstance(o.aum.value, Decimal) else None,
            "aum_raw": o.aum.raw,
            "aum_state": o.aum.state.value,
            "investors": (
                int(o.investors.value)
                if o.investors.value is not None else None
            ),
            "investors_raw": o.investors.raw,
            "investors_state": o.investors.state.value,
            "registry_state": o.registry_state.value,
            "source_artifact_id": p.source_artifact_id,
            "source_sha256": p.source_sha256,
            "member_name": p.member_name,
            "member_sha256": p.member_sha256,
            "xml_locator": p.xml_locator,
            "parser": p.parser,
            "parser_version": p.parser_version,
        })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6),
        str(r["numero_clase"]).zfill(6), int(str(r["day_index"]))))
    return rows


def quarterly_rows(rows_in: list[ShareClassQuarterlyMetrics]) -> list[dict]:
    rows = []
    for m in rows_in:
        p = m.provenance
        rows.append({
            "period": m.period,
            "share_class_key": m.share_class_key,
            "compartment_key": m.compartment_key,
            "fund_key": m.fund_key,
            "entity_type": m.entity_type,
            "numero_registro": m.numero_registro,
            "numero_compartimento": m.numero_compartimento,
            "numero_clase": m.numero_clase,
            "isin_raw": m.isin_raw,
            "isin_state": m.isin_state.value,
            "codigo_divisa": m.codigo_divisa,
            "periodicidad_calculo_vl": m.periodicidad_calculo_vl,
            "base_calculo_comision_gestion": m.base_calculo_comision_gestion,
            "sistema_imputacion_comisiones": m.sistema_imputacion_comisiones,
            "patrimonio": m.patrimonio,
            "valor_liquidativo": m.valor_liquidativo,
            "numero_participaciones": m.numero_participaciones,
            "numero_participes": m.numero_participes,
            "beneficio_dividendo_bruto": m.beneficio_dividendo_bruto,
            "comision_gestion": m.comision_gestion,
            "comision_depositario": m.comision_depositario,
            "comision_suscripcion_minima": m.comision_suscripcion_minima,
            "comision_suscripcion_maxima": m.comision_suscripcion_maxima,
            "comision_reembolso_minima": m.comision_reembolso_minima,
            "comision_reembolso_maxima": m.comision_reembolso_maxima,
            "comision_descuento_favor_fondo_minima":
                m.comision_descuento_favor_fondo_minima,
            "comision_descuento_favor_fondo_maxima":
                m.comision_descuento_favor_fondo_maxima,
            "official_return_t": m.official_return_t,
            "official_return_t_1": m.official_return_t_1,
            "official_return_t_2": m.official_return_t_2,
            "official_return_t_3": m.official_return_t_3,
            "ratio_total_gastos_t": m.ratio_total_gastos_t,
            "ratio_total_gastos_t_1": m.ratio_total_gastos_t_1,
            "ratio_total_gastos_t_2": m.ratio_total_gastos_t_2,
            "ratio_total_gastos_t_3": m.ratio_total_gastos_t_3,
            "volatilidad_vl_t": m.volatilidad_vl_t,
            "volatilidad_vl_t_1": m.volatilidad_vl_t_1,
            "volatilidad_vl_t_2": m.volatilidad_vl_t_2,
            "volatilidad_vl_t_3": m.volatilidad_vl_t_3,
            "vocacion_inversora": m.vocacion_inversora,
            "clase_fondo": m.clase_fondo,
            "codigo_divisa_iic": m.codigo_divisa_iic,
            "registry_state": m.registry_state.value,
            "source_artifact_id": p.source_artifact_id,
            "source_sha256": p.source_sha256,
            "member_name": p.member_name,
            "member_sha256": p.member_sha256,
            "xml_locator": p.xml_locator,
            "parser": p.parser,
            "parser_version": p.parser_version,
        })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6),
        str(r["numero_clase"]).zfill(6)))
    return rows


def patrimony_rows(rows_in: list[CompartmentPatrimonySnapshot]) -> list[dict]:
    rows = []
    for m in rows_in:
        p = m.provenance
        rows.append({
            "period": m.period,
            "compartment_key": m.compartment_key,
            "fund_key": m.fund_key,
            "entity_type": m.entity_type,
            "numero_registro": m.numero_registro,
            "numero_compartimento": m.numero_compartimento,
            "codigo_divisa_iic": m.codigo_divisa_iic,
            "indice_rotacion_cartera_actual": m.indice_rotacion_cartera_actual,
            "indice_rotacion_cartera_anterior":
                m.indice_rotacion_cartera_anterior,
            "dp_inversiones_financieras": m.dp_inversiones_financieras,
            "cartera_interior": m.cartera_interior,
            "cartera_exterior": m.cartera_exterior,
            "intereses_cartera": m.intereses_cartera,
            "inversiones_dudosas": m.inversiones_dudosas,
            "liquidez": m.liquidez,
            "resto": m.resto,
            "total_patrimonio": m.total_patrimonio,
            "patrimonio_fin_periodo_anterior":
                m.patrimonio_fin_periodo_anterior,
            "patrimonio_fin_periodo_actual": m.patrimonio_fin_periodo_actual,
            "suscripciones_reembolsos_netos": m.suscripciones_reembolsos_netos,
            "beneficios_brutos_distribuidos": m.beneficios_brutos_distribuidos,
            "rendimientos_netos": m.rendimientos_netos,
            "rendimientos_gestion": m.rendimientos_gestion,
            "intereses": m.intereses,
            "dividendos": m.dividendos,
            "resultados_renta_fija": m.resultados_renta_fija,
            "resultados_renta_variable": m.resultados_renta_variable,
            "resultados_depositos": m.resultados_depositos,
            "resultados_derivados": m.resultados_derivados,
            "resultados_iic": m.resultados_iic,
            "otros_resultados": m.otros_resultados,
            "otros_rendimientos": m.otros_rendimientos,
            "gastos_repercutidos": m.gastos_repercutidos,
            "comision_gestion": m.comision_gestion,
            "comision_depositario": m.comision_depositario,
            "gastos_servicios_exteriores": m.gastos_servicios_exteriores,
            "otros_gastos_gestion": m.otros_gastos_gestion,
            "otros_gastos_repercutidos": m.otros_gastos_repercutidos,
            "ingresos": m.ingresos,
            "comisiones_descuento": m.comisiones_descuento,
            "comisiones_retrocedidas": m.comisiones_retrocedidas,
            "otros_ingresos": m.otros_ingresos,
            "registry_state": m.registry_state.value,
            "source_artifact_id": p.source_artifact_id,
            "source_sha256": p.source_sha256,
            "member_name": p.member_name,
            "member_sha256": p.member_sha256,
            "xml_locator": p.xml_locator,
            "parser": p.parser,
            "parser_version": p.parser_version,
        })
    rows.sort(key=lambda r: (
        str(r["entity_type"]), str(r["numero_registro"]).zfill(12),
        str(r["numero_compartimento"]).zfill(6)))
    return rows


def canonical_fingerprint(*row_sets: list[dict]) -> str:
    """SHA-256 over canonical row serialization — parquet-metadata independent."""
    h = sha256()
    for rows in row_sets:
        for row in rows:
            h.update("|".join("" if v is None else str(v)
                              for v in row.values()).encode("utf-8"))
            h.update(b"\n")
        h.update(b"\x00")
    return h.hexdigest()


def _write_table(rows: list[dict], schema: pa.Schema, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema), path, compression="zstd"
    )


def write_period(
    dataset_root: Path | str,
    snaps: list[PortfolioSnapshot],
    *,
    period: str,
    artifact_id: str,
    records: list[FundRecord] | None = None,
    daily: list[ShareClassDailyObservation] | None = None,
    quarterly: list[ShareClassQuarterlyMetrics] | None = None,
    patrimony: list[CompartmentPatrimonySnapshot] | None = None,
) -> dict:
    """Write period-partitioned parquet tables; return manifest.

    ``dataset_fingerprint`` covers positions+quality only (G1 semantics —
    unchanged). ``registry_fingerprint`` covers the identity tables.
    ``daily_fingerprint`` covers the FONDMENS daily-observation table.
    ``quarterly_fingerprint`` covers the FONDTRIM quarterly-metrics table.
    ``patrimony_fingerprint`` covers the FONDPATRIMDISVAR table.
    """
    root = Path(dataset_root)

    prow, qrow = position_rows(snaps), quality_rows(snaps)
    if prow:
        _write_table(prow, POSITIONS_SCHEMA,
                     root / "positions" / f"period={period}" / "part-0.parquet")
    if qrow:
        _write_table(qrow, QUALITY_SCHEMA,
                     root / "quality" / f"period={period}" / "part-0.parquet")
    fingerprint = canonical_fingerprint(prow, qrow)

    manifest: dict = {
        "period": period,
        "source_artifact_id": artifact_id,
        "positions": len(prow),
        "quality_rows": len(qrow),
        "fondcart_present": bool(prow),
        "dataset_fingerprint": fingerprint,
    }

    if records is not None:
        frow = fund_rows(records)
        crow = compartment_rows(records)
        srow = share_class_rows(records)
        _write_table(frow, FUNDS_SCHEMA,
                     root / "funds" / f"period={period}" / "part-0.parquet")
        _write_table(crow, COMPARTMENTS_SCHEMA,
                     root / "compartments" / f"period={period}" / "part-0.parquet")
        _write_table(srow, SHARE_CLASSES_SCHEMA,
                     root / "share_classes" / f"period={period}" / "part-0.parquet")
        manifest.update({
            "funds": len(frow),
            "compartments": len(crow),
            "share_classes": len(srow),
            "registry_fingerprint": canonical_fingerprint(frow, crow, srow),
        })

    if daily is not None:
        drow = daily_rows(daily)
        if drow:
            _write_table(
                drow, DAILY_SCHEMA,
                root / "daily" / f"period={period}" / "part-0.parquet")
        manifest.update({
            "daily_observations": len(drow),
            "fondmens_present": bool(drow),
            "daily_fingerprint": canonical_fingerprint(drow),
        })

    if quarterly is not None:
        trow = quarterly_rows(quarterly)
        if trow:
            _write_table(
                trow, QUARTERLY_SCHEMA,
                root / "quarterly" / f"period={period}" / "part-0.parquet")
        manifest.update({
            "quarterly_metrics": len(trow),
            "fondtrim_present": bool(trow),
            "quarterly_fingerprint": canonical_fingerprint(trow),
        })

    if patrimony is not None:
        vrow = patrimony_rows(patrimony)
        if vrow:
            _write_table(
                vrow, PATRIMONY_SCHEMA,
                root / "patrimony" / f"period={period}" / "part-0.parquet")
        manifest.update({
            "patrimony_records": len(vrow),
            "fondpatrimdisvar_present": bool(vrow),
            "patrimony_fingerprint": canonical_fingerprint(vrow),
        })

    (root / "manifests").mkdir(parents=True, exist_ok=True)
    with open(root / "manifests" / f"{period}.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return manifest


def read_period_fingerprint(dataset_root: Path | str, period: str) -> str | None:
    """Recompute the canonical fingerprint of a stored period."""
    root = Path(dataset_root)
    mpath = root / "manifests" / f"{period}.json"
    if not mpath.exists():
        return None
    fp = json.loads(mpath.read_text(encoding="utf-8")).get("dataset_fingerprint")
    return str(fp) if fp is not None else None
