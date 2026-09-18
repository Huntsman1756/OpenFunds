# G4 — measured contract: FONDTRIM + FONDPATRIMDISVAR

Evidence measured from real artifacts `2012-03` (`3e3d8c00…`) and
`2025-12` (`5f05feda…`) before any adapter code. Official semantics from
the explanatory PDFs bundled inside each ZIP (2017 edition).

## 1. Cadence and structure

| Family | Cadence | Root | Grain (measured) |
|--------|---------|------|------------------|
| FONDTRIM | quarter months ≤ 2022; Jun+Dec ≥ 2023 | `FondTrim` | `Entidad → Compartimento → Clase` — **class-level** |
| FONDPATRIMDISVAR | same | `FondPatrimDisVar` | `Entidad → Compartimento` — **compartment-level** (zero `Clase` elements both eras) |

Counts: FONDTRIM 2,476 classes / 2,299 entidades (2012-03) vs 3,069 /
1,668 (2025-12) — near-complete coverage of the same-period
FONDREGISTRO/FONDMENS class universe. PDV: 2,299 / 1,668 compartments.

**Schema stability (measured, not assumed):** the complete element-path
set is identical in every artifact that publishes the families — 45
FONDTRIM paths and 43 FONDPATRIMDISVAR paths, zero drift across 8
periods spanning 2012-03 → 2025-12 (201203, 201403, 201603, 201803,
202003, 202203, 202306, 202512). Fail-closed element catalogs below
are therefore definitive for this era range.

## 2. FONDTRIM — per-class observed fields

**Identity/metadata**

| Field | Type/enum | Semantics (official) |
|-------|-----------|----------------------|
| `NumeroClase` | int (0 = fund-level, as FONDMENS) | required |
| `ISIN` | optional | as in REGISTRO |
| `CodigoDivisa` | optional | **class denomination currency — the unit of Patrimonio/VL** |
| `PeriodicidadCalculoVL` | enum `Diaria/Semanal/Quincenal/Otros` | required |
| `BaseCalculo_ComisionGestion` | enum `Patrimonio/Resultados/Mixta` | required |
| `SistemaImputacionComisiones` | enum (`Al fondo`/`Individual`/…) | optional (~50% absent) |
| `NumeroParticipes` | int | required |
| `NumeroParticipaciones` | decimal (fractional allowed) | required |

**Stock metrics — monetary, class currency**

| Field | Semantics |
|-------|-----------|
| `Patrimonio` | end-of-period assets, **units of class currency** |
| `ValorLiquidativo` | end-of-period NAV, class currency |
| `Beneficio_Dividendo_Bruto` | optional (~6% absent) |

**Fees — % (all "efectivamente devengada/soportada durante el periodo")**

`ComisionGestion` (sum of patrimonio-based + results-based mgmt fees,
over avg daily patrimonio), `ComisionDepositario`,
`ComisionSuscripcionMinima/Maxima`, `ComisionReembolsoMinima/Maxima`,
`ComisionDescuentoFavorFondoMinima/Maxima` (min≠max when tiered).

**Rolling metric blocks — each has `_TrimestreActual`, `_T_1`, `_T_2`, `_T_3` (sub-elements optional)**

| Block | Official semantics |
|-------|--------------------|
| `Rentabilidad` | **official return, non-annualized**, %, per quarter T/T-1/T-2/T-3. Blank when insufficient history. |
| `RatioTotalGastos` | operating expenses as % of avg daily patrimonio — **do not label "TER"** |
| `Volatilidad_VL` | historical NAV volatility, % |

**Compartment-level**: `VocacionInversora`, `ClaseFondo` (optional in
2025: 171/3 compartments absent).
**Entity-level**: `CodigoDivisaIIC` (optional: 287/1,668 absent in 2025).

## 3. FONDPATRIMDISVAR — per-compartment observed fields

Two unit classes inside one record — **the central trap**:

**Stock fields — monetary units, IIC currency (`CodigoDivisaIIC`)**

`DPInversionesFinancieras` (= `CarteraInterior` + `CarteraExterior` +
`InteresesCartera` + `InversionesDudosas` — the invested-portfolio
total, already the G1 reconciliation basis), `Liquidez`, `Resto`,
`TotalPatrimonio` (= IF + L + R), `PatrimonioFinPeriodoAnterior`,
`PatrimonioFinPeriodoActual`.

**Flow/variation fields — % over avg daily patrimonio, SIGNED**
(verified: real values are small signed decimals, e.g. FI:9:0
`Suscripciones_Reembolsos_Netos = -4.88`, `ComisionGestion = -0.95` —
costs are negative contributions):

`Suscripciones_Reembolsos_Netos`, `BeneficiosBrutosDistribuidos`,
`RendimientosNetos`, `RendimientosGestion`, `Intereses`, `Dividendos`,
`ResultadosRentaFija/Variable/Depositos/Derivados/IIC`,
`OtrosResultados`, `OtrosRendimientos`, `GastosRepercutidos`,
`ComisionGestion`, `ComisionDepositario`, `GastosServiciosExteriores`,
`OtrosGastosGestion`, `OtrosGastosRepercutidos`, `Ingresos`,
`ComisionesDescuento`, `ComisionesRetrocedidas`, `OtrosIngresos`.

**Ratios**: `IndiceRotacionCarteraActual`, `IndiceRotacionCarteraAnterior`
(IRC = [(C+V)−(S+R)]/PMD; `Anterior` refers to the prior period —
semantics shift on odd quarters).

Approximate identity (verified on FI:9:0):
`PatFinActual ≈ PatFinAnterior × (1 + flows% + yield%)` —
89,734,787 × (1 − 0.0488 + 0.0215) ≈ 87.3M ✓.

## 4. Unit evidence — the G3 warning realized

- FONDTRIM `Patrimonio`/`ValorLiquidativo` are in **class currency**
  (`CodigoDivisa`), not universally EUR: 2025-12 has 3,067 EUR classes +
  **1 USD class** + 1 currency-absent; 2012-03: 2,475 EUR + 1 absent.
  Entity `CodigoDivisaIIC` similar (1 USD + 287 absent).
- FONDMENS patrimonio is officially EUR — **different unit semantics
  across families**. Cross-family comparisons need currency checks.
- No thousand-EUR unit break found: 2012-03 and 2025-12 FONDTRIM
  `Patrimonio` are EUR units (a secondary source claiming "miles de
  euros" for 2012-era data does not hold in sampled artifacts —
  recorded, not adopted).

## 5. Observed deviations / optional elements (both eras, same code)

- `CodigoDivisaIIC` absent on ~17% of entidades (already registered for
  PDV in G1's deviation set — same element in FONDTRIM).
- `SistemaImputacionComisiones` absent on ~50% of classes (both eras).
- `Beneficio_Dividendo_Bruto` absent on ~6%.
- Rolling-block sub-elements (`*_T_1/2/3`) individually absent — blank
  = insufficient history, preserved as missing, not zero.
- 1 class in 2025-12 has identity elements but no metric elements
  (like FONDMENS missing blocks).
- FONDTRIM `Patrimonio` ends `.00` and differs by cents from FONDMENS
  month-end (79,517,664.00 vs 79,517,664.34) — different cutoff
  semantics, observed not interpreted.

## 6. Model implications

- **FONDTRIM → class-grained quarterly record** keyed
  `(share_class_key, period)`; compartment-level `VocacionInversora` /
  `ClaseFondo` and entity-level `CodigoDivisaIIC` denormalize as
  attributes of the record, preserving their true source level in
  naming/documentation. Escape hatch: if a future artifact shows
  metric elements outside `Clase`, fail closed and re-measure.
- **FONDPATRIMDISVAR → compartment-grained record** keyed
  `(portfolio_owner_key, period)`; never share-class rows. Each column
  carries a documented unit class (`monetary_iic_currency` vs
  `pct_over_avg_daily_patrimonio`); signs preserved verbatim.
- `Rentabilidad_*` stays `official_return_*` — verbatim observed; no
  calculated returns in this milestone; never a column named `return`.
- No `TER` naming for `RatioTotalGastos`.
- Exact joins only: FONDTRIM class → same-period FONDREGISTRO class;
  PDV compartment → registry compartment. Orphans → unresolved state.
- Reconciliation (informational, non-blocking): PDV
  `PatrimonioFinPeriodoActual` vs FONDTRIM compartment-class-sum vs
  FONDMENS month-end — all already verified near-equal on samples;
  currency must match before comparing.
