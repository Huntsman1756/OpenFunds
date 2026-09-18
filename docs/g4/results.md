# G4 — Quarterly metrics + compartment patrimony (FONDTRIM + FONDPATRIMDISVAR): adjudication

**Scope:** two new adapters over the measured contract —
`ShareClassQuarterlyMetrics` (FONDTRIM, class grain) → `quarterly`
table + `quarterly_fingerprint`; `CompartmentPatrimonySnapshot`
(FONDPATRIMDISVAR, compartment grain) → `patrimony` table +
`patrimony_fingerprint`; cross-family `reconcile`; CLI
`metrics` / `fees` / `official-returns` / `allocation`.

Observed-source contract documented before implementation:
`docs/g4/contract.md`. Reuse survey: `docs/g4/oss-review.md` — no
existing parser covers either family; own adapters over reused
generic tooling (lxml, Decimal, PyArrow, DuckDB, Typer).

**Verdict: proposed PASS** — every gate verified on live CNMV data at
both historical extremes; schema identical across all 8 sampled
publishing periods 2012→2025.

## Evidence

### Ingestion (live)

| Period   | Family members        | quarterly rows | patrimony rows | quarterly fp    | patrimony fp    | G1/G2/G3 fps |
|----------|-----------------------|----------------|----------------|-----------------|-----------------|--------------|
| 2012-03  | TRIM + PDV            | 2,476          | 2,299          | `62a9cbafc2a7…` | `badde5e6cbae…` | unchanged    |
| 2025-03  | neither (non-cadence) | —              | —              | —               | —               | unchanged    |
| 2025-04  | neither (non-cadence) | —              | —              | —               | —               | unchanged    |
| 2025-12  | TRIM + PDV            | 3,069          | 1,668          | `82b3c9bf2649…` | `b7a4b98dc822…` | unchanged    |

`dataset_fingerprint`, `registry_fingerprint`, `daily_fingerprint`
byte-identical to G1/G2/G3 on every re-exported period. Idempotent
re-runs return `exported: false` with unchanged fingerprints.

### Schema stability (measured, not assumed)

Complete fail-closed element catalogs registered: **45 FONDTRIM paths,
43 FONDPATRIMDISVAR paths** — identical across all 8 sampled publishing
periods (2012-03, 2014-03, 2016-03, 2018-03, 2020-03, 2022-03, 2023-06,
2025-12). Zero drift; the same code parses both era extremes.

### Registry join coverage (live)

100% `resolved` in both periods — 5,545 quarterly rows and 3,967
patrimony rows joined exactly on same-period regulatory keys; zero
`unresolved_registry_reference` (synthetic tests exercise the state).

### Query surface (live, 2025-12)

```
cnmv-iic metrics ES0138841038 --as-of 2025-12
 → exact_share_class → FI:9:0:1
 → stock: patrimonio 79517664.00, vl 30.5128 (EUR, codigo_divisa)
 → fees_pct: gestion 0.50, depositario 0.02
 → official_return_pct: t 0.19 / t-1 0.47 / t-2 1.19 / t-3 0.30

cnmv-iic allocation FI:9:0 --as-of 2025-12
 → monetary_in_iic_currency: TP 87,336,084.00 = IF 86,776,674
   + L 474,720 + R 84,690  (stock identity, exact)
 → pct_of_avg_daily_patrimonio: flows −4.88, yield +2.15, gestion −0.95
   (signed percentages — kept rigidly apart from monetary fields)

cnmv-iic metrics FI:9 --as-of 2025-12
 → fails closed: does not resolve to a single share class: exact_fund
```

### Cross-family reconciliation (live, informational)

```
cnmv-iic reconcile 2025-12 → 5,704 match / 8 diff /
                             576 skipped_currency / 117 skipped_missing
cnmv-iic reconcile 2012-03 → 7,054 match / 19 diff / 1 skipped_missing
```

Example: `FI:9:0:1` TRIM patrimonio 79,517,664.00 vs MENS month-end AUM
79,517,664.34 → match at rel 4.3e-9 (the '.00' vs cents cutoff).
`FI:9:0` PDV total 87,336,084.00 = TRIM class sum exactly.

Diffs are real source disagreements reported verbatim, never hidden:
dormant micro-classes (2012 patrimonio 6–10 EUR), classes reporting
`0.00` in TRIM while MENS shows residue, and one 6.4B-vs-1.36M
divergence (`FI:5601:6:2`). `skipped_currency` covers the 287 entities
without `CodigoDivisaIIC` plus non-EUR classes — no monetary value is
ever compared across unchecked currencies. `skipped_missing` covers
identity-only rows and missing counterpart observations.

## Gate-by-gate

1. **Contract first** — `oss-review.md` (reuse survey, all candidates
   REFERENCE_ONLY/REJECT) + `contract.md` (measured grains, units,
   scales, deviations) written before any adapter code.
2. **Grain measured, not assumed** — FONDTRIM is class-grained (3,069
   rows ≈ 3,102 registered classes); FONDPATRIMDISVAR is
   compartment-grained (zero `Clase` elements in either era). No
   artificial class rows from PDV; no collapsing TRIM to compartments.
3. **Decimal + measured scale** — `patrimonio`/`numero_participaciones`
   `decimal128(38,2)`, `valor_liquidativo`/`beneficio_dividendo_bruto`
   `decimal128(38,4)`, `numero_participes` `int64`, all PDV fields
   `decimal128(38,2)`. Never float.
4. **Units demonstrated** — official explanatory PDFs + instance
   verification: TRIM stock fields are in class `codigo_divisa`
   (USD classes preserved verbatim); PDV stock fields in IIC
   `codigo_divisa_iic`; PDV flow/result fields are **signed percentages
   over average daily patrimonio** — confirmed by the bridge
   `pat_anterior × (1 + flows% + yield%)` landing within −0.058% for
   FI:9, and by stock identities `DP = CI+CE+IC+ID`,
   `TP = DP+L+R` holding exactly.
5. **Official returns verbatim** — `Rentabilidad_*` kept as
   `official_return_*`; never recomputed from NAV, never mixed with a
   hypothetical derived-return column.
6. **No commission reinterpretation** — fees signed verbatim
   (negative `ComisionGestion` values preserved, −1.02 to +3.69 live);
   `RatioTotalGastos` never relabelled "TER"; each fee keeps its own
   name and documented basis.
7. **Missing ≠ zero** — absent fields → NULL; empty rolling blocks
   (insufficient history) → all four T-values NULL; identity-only
   rows preserved verbatim; `SistemaImputacionComisiones` absent on
   ~50% of rows kept absent.
8. **Exact registry join** — same-period FONDREGISTRO keys; 100% live
   coverage; no fuzzy matching anywhere.
9. **Reconciliation is derived and honest** — `match`/`diff`/
   `skipped_currency`/`skipped_missing` states; equality never
   required; currency checked before any monetary comparison.
10. **G1/G2/G3 fingerprints invariant** — verified on every
    re-exported period.
11. **2012 + 2025 same code** — zero schema drift across 8 periods;
    measured deviations (missing `CodigoDivisaIIC` on 287 entities,
    absent fee/rolling fields) registered in the contract.
12. **CLI after contract** — `metrics`/`fees`/`official-returns`/
    `allocation`/`reconcile`; grain contracts enforced (class-grained
    accessors fail closed on fund identifiers; allocation accepts
    fund/compartment/ISIN → portfolio-owner compartments).
13. **Deterministic storage** — ordered rows, independent
    `quarterly_fingerprint`/`patrimony_fingerprint`; provenance to
    artifact/member SHA + XML locator on every row.
14. **Cadence honest** — non-cadence periods record
    `fondtrim_present=false`/`fondpatrimdisvar_present=false`; absence
    is never fabricated.

## Findings recorded in the contract

- `Patrimonio` is in class currency units (EUR for EUR classes) in both
  eras — the secondary-source "miles de euros" claim does not hold for
  the sampled periods; `codigo_divisa` remains the authoritative basis.
- `NumeroClase=0` fund-level classes appear in TRIM as well; kept as
  first-class keys.
- `IndiceRotacionCarteraAnterior` absent for compartments without a
  prior period (46 in 2012-03, 51 in 2025-12) — documented optionality.
- One identity-only compartment row exists in 2025-12 PDV — preserved.

## Limits (honest)

- The `% over average daily patrimonio` basis is confirmed by the
  explanatory PDF and validated computationally on tested rows, but
  CNMV does not publish a machine-readable unit declaration; the
  `PDV_UNIT_BASIS` mapping is therefore a documented interpretation,
  not a source-quoted fact.
- Reconciliation diffs are surfaced verbatim without inferred causes —
  some (e.g. `FI:5601:6:2`) may reflect corporate events or reporting
  anomalies this layer deliberately does not explain.
- `official-returns` emits only `official_return_t` per period; the
  T-1/T-2/T-3 lookbacks are available verbatim via `metrics`.
- Resolution uses the latest registry ≤ `as-of`; a class absent from
  all ingested registry snapshots resolves only by full key.

## Checks

`pytest`: **119 passed** (46 new G4 tests: 17 TRIM, 15 PDV,
7 reconciliation, 7 query surface — synthetic fixtures incl. USD
currency, negative fees, empty rolling blocks, missing blocks,
duplicate keys, impossible joins).
`ruff`: clean. `mypy`: clean.
