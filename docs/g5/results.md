# G5 — FONDDERI evidence ledger: adjudication

**Scope:** FONDDERI adapter as a verbatim evidence ledger — NOT a
derivatives normalization engine. `CompartmentDerivativeOperation`
(compartment → repeatable operations) → `derivatives` table;
`CompartmentDerivativeCoverage` (every declaring compartment,
including explicit zero-operation reporters) → `derivative_coverage`
table; `derivatives_fingerprint`; coverage reconciliation;
`cnmv-iic derivatives` CLI.

Observed-source contract documented before implementation:
`docs/g5/contract.md`. Reuse survey: `docs/g5/oss-review.md` —
FINOS CDM / OpenGamma Strata / FpML = REFERENCE_ONLY (semantic
oracle, not a mold); FundsXML vocabulary reviewed; QuantLib =
NO_USE. No derivative parser exists in the OSS space for this file;
own adapter over reused generic tooling.

**Verdict: proposed PASS** — every gate verified on live CNMV data at
both historical extremes; the model stores only source-observed
structure and never infers derivative semantics from free text.

## Evidence

### Ingestion (live)

| Period   | operations | coverage rows | zero-op compartments | unresolved | derivatives fp    | G1–G4 fps |
|----------|-----------:|--------------:|---------------------:|-----------:|-------------------|-----------|
| 2012-03  | 7,233      | 2,299         | 809                  | 0          | `be1e65ae53b4…`   | unchanged |
| 2025-12  | 4,965      | 1,668         | 772                  | 0          | `7a66583b6636…`   | unchanged |

`dataset_fingerprint` (2025-12 `f53e607d7c7b…` — byte-identical to G1),
`registry_fingerprint`, `daily_fingerprint`, `quarterly_fingerprint`,
`patrimony_fingerprint` all unchanged on every re-export. Idempotent
re-runs return `exported: false` with unchanged fingerprint.
Non-cadence periods (2025-03, 2025-04) record `fondderi_present`
absent — honest cadence semantics like FONDCART.

### Measured contract (docs/g5/contract.md)

- **Grain:** `Entidad → Compartimento → OperativaDerivados` — no
  `Clase` element; compartment is the portfolio owner, matching PDV.
- **14 element paths**, identical across all 8 sampled publishing
  periods (2012-03 → 2025-12). Zero drift.
- **Closed official enums, verified across the whole series:**
  `Descripcion` = obligation/right × underlier class (8 combinations,
  decomposed to `side` + `underlier_class`); `Objetivo` = cobertura /
  inversion / objetivo_concreto_de_rentabilidad (3 values).
- **`Importe`:** documented as committed nominal in EUR — stored as
  `importe_eur` `decimal128(38,2)`, sign preserved (55 negatives live
  in 2012-03, kept verbatim).
- **`Subyacente` / `Instrumento`:** officially "campo texto no
  normalizado" — stored verbatim; never parsed into underlier/strike/
  expiry/counterparty.

### Representation (the structural-classification gate)

All 12,198 live operations → `representation: partially_structured`:

> the source itself supplies structured facets (side, underlier
> class, objective, committed nominal in EUR) while the instrument
> identity remains official free text.

Zero rows are `structured` (CNMV never supplies machine-readable
underlier/expiry/counterparty) and zero are `verbatim_only` (the
facets are always present). This is an honest ceiling: **no
CDM-compatible exact fields exist for product type, expiry, underlier
identifier, strike, or counterparty** — an `export --format cdm`
would require inference the project has refused since G0. REFERENCE_ONLY
verdict confirmed by measurement, not assumption.

### Reconciliation (docs/g5/contract.md §reconciliation)

`cnmv-iic reconcile` now carries a `derivatives` section:

- **Coverage joins (legitimate):** DERI declaring universe ≡ PDV
  declaring universe — `2025-12: 1,668 match`, `2012-03: 2,299 match`;
  `missing_in_patrimony` surfaced honestly when a compartment is
  absent from PDV (synthetic test).
- **`not_comparable` × 3, declared not hidden:**
  - `Importe` (committed nominal, EUR **stock**) vs
    `ResultadosDerivados` (signed **% flow** over avg daily patrimonio)
  - DERI vs FONDTRIM — class grain, no derivative stock field
  - DERI vs FONDCART — `ClaseIF` is geographic, not derivative class
- **Informational aggregates** (op count, `sum(importe_eur)`,
  objective spread) carry an explicit "no counterpart field exists"
  note — never presented as reconciliation.

### Query surface (live, 2025-12)

```
cnmv-iic derivatives FI:9:0 --as-of 2025-12
 → exact_compartment → 1 operation
 → side obligacion / underlier_class renta_fija / objetivo inversion
 → instrumento "C/ FUTURO BOBL MAR 26"  (verbatim, official text)
 → subyacente  "BO. NOCIONAL 6% 5YR"   (verbatim, official text)
 → importe_eur 14594930.00             (committed nominal, signed)
 → representation partially_structured
 → provenance → artifact + XML locator

cnmv-iic derivatives ES0138841038 --as-of 2025-12
 → exact_share_class → owner compartment FI:9:0 (same as holdings)

cnmv-iic derivatives FI:100:0 --as-of 2025-12
 → reporting_state reported_no_derivatives — explicit source state,
   not absent data

cnmv-iic derivatives FI:9:0 --as-of 2025-03
 → compartments_rows [] — non-cadence period, honest absence
```

### Forbidden-by-design (verified absent)

No regex → derivative type; no parsed underlier/strike/expiry/
counterparty; no pricing/greeks/notional-exposure; no QuantLib,
Strata, or CDM runtime dependency; no LLM extraction; no issuer
resolution; no look-through. Deliberately absent CLI verbs:
`options`, `futures`, `swaps`, `underlying`, `delta`,
`notional-exposure` — CNMV does not supply those concepts
authoritatively.

## Gates

- `pytest` — 140 passed (21 FONDDERI tests: enums/facets, invalid
  values fail-closed, negatives verbatim, registry joins,
  zero-operation coverage, provenance, Parquet roundtrip,
  representation, coverage reconciliation, accessor resolution,
  `reported_no_derivatives`, not_comparable declarations,
  missing-table fail-closed).
- `ruff check src tests` — clean.
- `mypy src` — clean.
- `Decimal` for all source numerics; no floats in canonical storage.
- Fail-closed: unknown `Descripcion`/`Objetivo` values raise
  ParseError; missing coverage table → `NotFoundError`; unresolved
  identifier → `not_found`; non-cadence period → honest empty result.

## Commits

```
4d754ff G5-R: reuse review + measured contract for FONDDERI
adb0b3e G5-A/B: FONDDERI evidence ledger adapter
5fc450e G5-C/D: derivative coverage reconciliation + minimal CLI
```
