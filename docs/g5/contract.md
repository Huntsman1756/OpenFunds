# G5-R — FONDDERI measured contract

Measured on real CNMV artifacts: 2012-03, 2014-03, 2016-03, 2020-03,
2022-03, 2023-06, 2025-06, 2025-12 (all publishing periods in the
research corpus). Official semantics from
`FONDDERI_Documento Explicativo.pdf` shipped inside each ZIP.

## 1. File identity

- Root: `FondDeri`; header `FechaDatos` (`YYYYMM`).
- Member naming varies by era (`FONDDERI_201203.XML`, `FONDDERI.XML`,
  `FONDDERI_202512.xml`) — match case-insensitively.
- XML encoding UTF-8 (declared and verified on raw bytes).
- XSD fingerprint `abeccc345799fa9d…` already registered.
- Cadence: same as TRIM/PDV — quarter months ≤2022, June+December
  from 2023; absent from non-cadence artifacts (2025-03/04 ship no
  FONDDERI member).

## 2. Schema

**14 paths**, identical across all 8 sampled periods — zero drift:

```
FondDeri
├── FechaDatos
└── Entidad                                   1..N
    ├── Tipo
    ├── NumeroRegistro
    ├── CodigoDivisaIIC                       optional (287 absent, 2025-12)
    └── Compartimento                         1..N per entity
        ├── NumeroCompartimento
        └── OperativaDerivados                0..N per compartment
            ├── Descripcion
            ├── Subyacente
            ├── Instrumento
            ├── Importe
            └── Objetivo
```

Grain: **`(compartment_key, operation_ordinal)`** — compartment-level,
no `Clase` elements ever. One `OperativaDerivados` row per reported
derivative operation.

## 3. Cardinality (measured)

| Period   | Compartments | w/o ops | Ops total | Max ops/comp |
|----------|--------------|---------|-----------|--------------|
| 2012-03  | 2,299        | 809     | 7,233     | 104          |
| 2025-12  | 1,668        | 772     | 4,965     | 151          |

- A compartment with zero `OperativaDerivados` is an **explicitly
  reported zero-derivatives state** — DERI compartment key set is
  EXACTLY the PDV/registry universe (1,668 = 1,668, 0 orphans vs
  FONDREGISTRO). Absence-of-ops and absence-of-report are different
  facts; both must be representable.
- Zero duplicate compartment keys; every entity has ≥1 compartment.

## 4. Field semantics (official PDF + measurement)

| Element | Type | Official semantics | Measured |
|---------|------|--------------------|----------|
| `Descripcion` | **closed enum (8)** | composite: derecho/obligación × underlier class {renta fija, renta variable, tipo de cambio, otros} | exactly one value-set across all 8 periods: `Derechos/Obligaciones en renta fija·renta variable·tipos de cambio` + `Otras Obligaciones` + `Otros Derechos` |
| `Subyacente` | free text | "campo texto **no normalizado** que muestra información sobre el activo subyacente" | 1,300–1,982 distinct values; mixes generic categories ("Valor de renta variable"), names ("DJ EURO STOXX 50") and pipe-delimited codes ("EU3M FUTURO\|LIFFE LC EURIBOR-M2\|") |
| `Instrumento` | free text | "campo texto **no normalizado** que muestra información sobre el producto derivado" | 1,693–2,758 distinct; mixes categorical labels ("Futuros comprados"), `C/`-prefixed contract codes (927/1,693 distinct, 2025-12), pipe-delimited text ("FUTURO\|EUR/USD\|125000\|FÍSICA") |
| `Importe` | decimal | "**importe nominal comprometido** expresado en **euros**" | scale 2 always; **signed** — 55 negatives in 2012-03, 0 in 2025-12 |
| `Objetivo` | **closed enum (3)** | coded field: 01 Cobertura / 02 Inversión / 03 Objetivo concreto de rentabilidad | exactly one value-set across all periods: `Cobertura`, `Inversión`, `Objetivo Concreto de Rentabilidad`; **1 absent value** in 2014-03 (only missing cell in 49,522 ops) |
| `CodigoDivisaIIC` | ISO currency | entity denomination | all EUR in 2012-03; 1 USD + **287 absent** in 2025-12 (same gap as FONDTRIM) |

## 5. Model implications

- **Evidence ledger, not normalization.** `Subyacente` and
  `Instrumento` are officially non-normalized → store verbatim, never
  regex-parse into underlier/expiry/strike. The pipe-delimited and
  `C/`-prefixed shapes are *observable* structure, not *authoritative*
  structure.
- `Descripcion` is a source-proven composite enum — the two facets
  (right/obligation side; underlier class) may be stored as observed
  enum fields because the official document defines the composition.
  This is decomposition of a documented code, not inference.
- `Objetivo` enum verbatim; the single absent value → NULL.
- `Importe` = committed nominal **in EUR** per the official document
  (not `CodigoDivisaIIC`). Keep `importe_eur` semantics documented;
  `codigo_divisa_iic` preserved separately as the IIC's denomination.
- Representation per row is `partially_structured` by construction:
  enums + amount structured by source; identity of the instrument
  verbatim-only.
- `NumeroCompartimento` grain — never invent share-class rows.
- Compartments with zero ops: representable as "reported, no
  operations" (coverage-level fact), not fabricated op rows.

## 6. Inference-free mapping coverage (CDM/FundsXML gate)

Fields CNMV supplies authoritatively vs. what a CDM product/trade
record expects:

| CDM-ish field | Source support |
|---------------|----------------|
| amount/notional | `Importe` — "nominal comprometido", EUR (documented) |
| currency | fixed EUR for `Importe`; `CodigoDivisaIIC` for the IIC |
| position side (derecho/obligación) | `Descripcion` facet (official) |
| underlier asset class | `Descripcion` facet (official, 4 classes) |
| purpose | `Objetivo` (official, 3 values) |
| product type (future/option/swap) | **not supplied** — only free text |
| underlier identifier | **not typed** — free text only |
| expiry/strike/size | **not supplied** — embedded in free text at best |
| counterparty | **absent entirely** |

Verdict: the file can never populate a CDM `Trade`/`Product` record
without inference. An `export --format cdm` is premature; revisit only
if a later version of the source adds structured fields.

## 7. Reconciliation surface (G5-C preview)

- `Importe` (nominal committed stock, EUR) vs PDV
  `ResultadosDerivados` (signed % flow over average daily patrimonio):
  different semantics → expected `NOT_COMPARABLE`. Do not build an
  equation because the numbers look adjacent.
- Legitimate checks: DERI compartment coverage vs registry/PDV
  universe (exact key join, already measured 1,668 = 1,668), and
  sum-of-`Importe` per compartment as an informational aggregate with
  no counterpart claim.
- FONDCART `ClaseIF` carries only INTERIOR/EXTERIOR/DUDOSAS — FONDCART
  cannot corroborate derivative-ness; DERI is the sole authoritative
  derivative surface.

## 8. Deviations to register

- `CodigoDivisaIIC` absent on 287 entities (2025-12).
- `Objetivo` absent on 1 operation (2014-03).
- Compartment elements present with zero `OperativaDerivados`
  children (809 in 2012-03; 772 in 2025-12) — observed empty state.
- Negative `Importe` values exist (55 in 2012-03).
