# CNMV source map — official data surface for Spanish IIC

Status: verified empirically 2026-09-17 (live downloads + XML/XSD inspection).
Raw evidence: `.research/cnmv/` (local only, never committed).

## Publication surface

| Item | Value |
|---|---|
| Download page | `https://www.cnmv.es/portal/Publicaciones/Descarga-Informacion-Individual.aspx?ejercicio={YYYY}&lang=es` (301 → `internet.cnmv.es/portal/publicaciones/descarga-informacion-individual`) |
| Year parameter | `ejercicio` (dropdown offers 2012–2026) |
| Download URL pattern | `https://www.cnmv.es/webservices/verdocumento/ver?e={OPAQUE_TOKEN}` — **tokenized, non-deterministic**. Must scrape the listing page HTML (`grdDescargas` table, `title` attribute = Spanish month name) |
| Auth | none (public) |
| Rate limit | undocumented; use polite pacing (~1 req/1.5s) and identifiable User-Agent |
| Token stability | tokens are opaque and may rotate; treat URL as ephemeral — pin content by SHA-256, not by URL |
| Regulatory basis | Circular 4/2008 CNMV (informes trimestrales/semestral/anual + estado de posición) |
| Description doc | `https://www.cnmv.es/DocPortal/Estadisticas/Descarga-Informacion-Individual/Periodicidad-Descripcion.pdf` (SHA-256 b9098720…, retrieved 2026-09-17) |

## Verified coverage & cadence

Periods probed live: every year 2012–2026 (all 12 months listed each year).

| Period range | Monthly ZIP contents |
|---|---|
| 2012-01 … 2022-12 | Every month: FONDREGISTRO + FONDMENS. **Quarter months (03/06/09/12): full 11-family set** (~10 MB compressed) |
| 2023-01 … present | Every month: FONDREGISTRO + FONDMENS only (~2 MB). **Full set only in June and December** (~8 MB) |

Verified ZIP contents (N = XML families present):

| Period | XML families |
|---|---|
| 2012-03, 2014-03, 2016-03, 2018-03, 2020-03, 2022-03 | 11 (all FOND* + SOC*) |
| 2022-06, 2022-09, 2022-12 | 11 |
| 2023-03, 2023-09, 2024-03, 2024-09, 2025-03, 2025-09, 2026-03 | 2 (FONDMENS + FONDREGISTRO) |
| 2023-06, 2023-12, 2024-06, 2024-12, 2025-06, 2025-12 | 11 |

**Consequence:** public portfolio detail is quarterly 2012–2022, **semiannual (June/December) from 2023**. `portfolio-diff` granularity post-2022 is H1/H2. The web page still claims quarterly detail — documentation is stale relative to actual publication.

## File families (per ZIP)

| Family | Entity scope | Grain | Content (from XSD + instance inspection) |
|---|---|---|---|
| FONDREGISTRO | FI/FHF/SICAV/SHF | entity → compartimento → clase | Denominacion, ETF flag, per-class ISIN, Gestora (tipo, nº registro, denominación, grupo), Depositario (nº registro, denominación, grupo) |
| FONDMENS | same | entity → compartimento → clase → day | VL_Dia1..31, Participes_Dia1..31, Patrimonio_Dia1..31; non-business days = 0 |
| FONDTRIM | FI/FHF | entity → compartimento → clase | ClaseFondo, VocacionInversora, ISIN, CodigoDivisa, NumeroParticipaciones, NumeroParticipes, dividendo, Patrimonio, VL, ComisionGestion (+base), ComisionDepositario, SistemaImputacion, comisiones suscripción/reembolso/descuento min-max, Rentabilidad (T actual + T-1..T-3), PeriodicidadCalculoVL, Volatilidad (4T), RatioTotalGastos=TER (4T) |
| FONDPATRIMDISVAR | FI/FHF | entity → compartimento | IndiceRotacionCartera, DPInversionesFinancieras, CarteraInterior/Exterior, InteresesCartera, InversionesDudosas, Liquidez, Resto, TotalPatrimonio, PatrimonioFinPeriodoAnterior, Suscripciones/Reembolsos netos, BeneficiosBrutosDistribuidos, desglose rendimientos (gestión, intereses, dividendos, RF, RV, depósitos, derivados, IIC, otros), desglose gastos (gestión, depositario, servicios ext., otros), ingresos (comisiones descuento/retrocedidas), PatrimonioFinPeriodoActual |
| FONDCART | FI/FHF (+SICAV listed?) | entity → compartimento → position | ClaseIF (INTERIOR/EXTERIOR/DUDOSAS), DescripcionIF (12 asset-class labels), CodigoISIN, DescripcionValor (pipe-delimited `TIPO|EMISOR|CUPON|VENCIMIENTO`), Divisa, ValorMercado |
| FONDDERI | FI/FHF | entity → compartimento → operation | CodigoDivisaIIC (entity level), Descripcion, Subyacente, Instrumento, Importe, Objetivo (Cobertura/Inversión/Objetivo Concreto de Rentabilidad) — all free text except Importe |
| SOCREGISTRO | SICAV/SHF | entity → compartimento → serie | same as FONDREGISTRO but `Serie/NumeroSerie` instead of `Clase/NumeroClase` |
| SOCTRIM | SICAV | entity → compartimento → serie | ClaseSociedad, VocacionInversora, NumeroAcciones, NumeroAccionistas, dividendo, Patrimonio, VL, Rentabilidad 4T, TER 4T. **No ISIN in SOCTRIM** (ISIN lives in SOCREGISTRO) |
| SOCPATRIMDISVAR | SICAV | entity → compartimento | same fields as FONDPATRIMDISVAR |
| SOCCART | SICAV | entity → compartimento → position | same fields as FONDCART |
| SOCDERI | SICAV | entity → compartimento → operation | same fields as FONDDERI |

Each ZIP also contains per-family `.xsd` and `*_Documento Explicativo.pdf`.

## Volume observations (real downloads)

| Metric | Value |
|---|---|
| Full-cadence ZIP | ~8–10.9 MB compressed, ~110 MB uncompressed (SOCCART is the largest XML, ~34–55 MB) |
| Monthly-only ZIP | ~1.7–2.3 MB |
| FONDCART 2025-12 | 38.7 MB XML, 103,130 positions, 1,432 unique entities (1,668 `Entidad` elements — entity block repeats per compartment) |
| FONDDERI 2025-12 | 4,965 derivative operations |
| FONDMENS 2025-11 (ticker-lab measurement) | ~15.3 MB XML, ~3,112 ISINs, ~68k daily observations/month |
| Entities (FONDREGISTRO 2025-11) | ~1,441 |
| Full history estimate | ~170 monthly + ~54 full-cadence artifacts ≈ 3–4 GB raw — trivially workstation-scale |

## Key entity/identity facts

- Natural key everywhere: `(Tipo ∈ {FI,FHF,SICAV,SHF}, NumeroRegistro, NumeroCompartimento, NumeroClase|NumeroSerie)`.
- ISIN exists at class/series level (FONDREGISTRO/SOCREGISTRO) and in FONDMENS/FONDTRIM; **absent in SOCTRIM** and in FONDCART/FONDDERI (portfolio files key by entity+compartment only).
- `NumeroCompartimento`/`NumeroClase` = 0 is the homogeneous-structure placeholder when the concept doesn't exist officially (documented in XSD).
- Gestora/Depositario carry official register numbers + group register numbers → stable institution identity is available.
- No LEI, no NIF in these files. Institution identity = CNMV register number + name history.

## Data quality observations (2025-12, 2012-03)

- FONDCART ISIN coverage: 99.6% valid-format in 2025-12 (148 `XXXXXXXXXXXX` masked placeholders); 94% in 2012-03 (~3.5k positions missing the element, mostly `Depositos` which legitimately have no ISIN).
- `DescripcionValor` pipe format `TIPO|ISSUER|COUPON|MATURITY` stable across 2012 and 2025.
- FONDDERI underlyings are free text (`AC.BANCO SANTANDER SA`, `FUT. S AND P500 EMINI 03/26`…) — representable verbatim, **not** reliably machine-identifiable.
- Real instances systematically deviate from published XSD (missing optional-in-practice elements). See schema-history.md.
