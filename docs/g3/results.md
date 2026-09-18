# G3 — Daily share-class observations (FONDMENS): adjudication

**Scope:** FONDMENS adapter → `ShareClassDailyObservation` canonical model
(one row per `share_class_key × observation_date`) → `daily` Parquet table +
`daily_fingerprint` → `nav` / `aum` / `investors` / `class` CLI.

Observed-source contract documented before implementation:
`docs/g3/contract.md`.

**Verdict: proposed PASS** — every gate below verified on live CNMV data
across four periods including both historical extremes and a 30-day month.

## Evidence

### Ingestion (live)

| Period   | Classes | Daily rows | Month len | Daily fingerprint | G1/G2 fingerprints |
|----------|---------|------------|-----------|-------------------|--------------------|
| 2012-03  | 2,484   | 77,004     | 31        | `e161aa3b5641…`   | unchanged          |
| 2025-03  | 3,101   | 96,131     | 31        | `6c9b49023e5b…`   | unchanged          |
| 2025-04  | 3,128   | 93,840     | **30**    | `bbb9ccf3b923…`   | unchanged          |
| 2025-12  | 3,102   | 96,162     | 31        | `f9f8eebc1329…`   | unchanged          |

`dataset_fingerprint` and `registry_fingerprint` are **byte-identical** to
their G1/G2 values on every re-exported period — the daily surface is a
separate, additive fingerprint.

Aggregate states over all ingested periods: **1,038,361 observed**,
**46,916 source_zero_sentinel**, **4,134 missing**, 0 invalid.

### Longitudinal registry reconciliation (live)

| Period   | Registered | In FONDMENS | Matched | Missing | Orphans |
|----------|-----------|-------------|---------|---------|---------|
| 2012-03  | 2,484     | 2,484       | 2,484   | 0       | 0       |
| 2025-03  | 3,101     | 3,101       | 3,101   | 0       | 0       |
| 2025-04  | 3,128     | 3,128       | 3,128   | 0       | 0       |
| 2025-12  | 3,102     | 3,102       | 3,102   | 0       | 0       |

Zero `unresolved_registry_reference` rows in live data; the state exists
and is exercised by synthetic tests.

### Query surface (live, 2025-12)

```
cnmv-iic nav ES0138841038 --from 2025-12-15 --to 2025-12-20
 → resolved_as: exact_share_class → share_class_key FI:9:0:1
 → 30.4632, 30.4786, 30.4715, 30.4844, 30.4591, 30.4599 (EUR, observed)
 → FondMens/Entidad[1]/Compartimento[1]/Clase[1] + artifact SHA
```

Grain contract — sibling classes of FI:9:0 keep distinct series
(inverse of the G2 holdings dedup):

```
ES0138841038 → FI:9:0:1 → 30.4632 / 30.4786
ES0138841004 → FI:9:0:2 → 10.4332 / 10.4386
ES0138841012 → FI:9:0:3 → 10.4564 / 10.4618
```

`nav FI:9` fails closed: `does not resolve to a single share class:
exact_fund`.

Sentinel + missing semantics (live):

```
nav ES0184976043 (all-zero class)   → value null, state source_zero_sentinel, raw '0'
nav ES0124525009 (missing blocks)   → value null, state missing, raw null
aum FI:5904:0:1 (negative patrimonio) → observed: -0.88 … -9.71
```

`class ES0138841038` → 92 rows over 2025-03/2025-04/2025-12, all observed,
`unresolved_days: 0`.

## Gate-by-gate

1. **FONDMENS only** — one new adapter; no other source touched.
2. **Observed values** — `nav`/`aum`/`investors` are source-verbatim;
   nothing computed anywhere in the path.
3. **Decimal** — `nav` `decimal128(38,4)`, `aum` `decimal128(38,2)`
   (measured max scales), `investors` `int64`. Never float.
4. **Zero semantics verified, not assumed** — 0 interior zeros across
   ~2.6M cells in 2025-12; zeros are boundary-only (12 leading, 4 trailing,
   137 all-zero classes) and appear on impossible days. Per-metric
   independence measured (90 cells VL=0/par≠0; 285 inverse). Implemented
   per-field as `source_zero_sentinel`; the *reason* is never inferred.
5. **Deterministic dates** — `observation_date` = `FechaDatos` month +
   `DiaN` for N ≤ `monthrange`; April's `Dia31='0'` rejected as padding
   (max emitted date 2025-04-30). No weekend/holiday interpolation.
6. **No forward-fill** — sentinel/missing cells emit NULL value, never a
   carried value.
7. **No fabricated NAV** — `value` is NULL unless `state=observed`; `raw`
   preserves the lexical source.
8. **Exact registry join** — same-period FONDREGISTRO class keys; live
   coverage is 100% in all four periods; non-matching keys become
   `unresolved_registry_reference` (tested synthetically), never fuzzy.
9. **Historical extremes + key-change period** — 2012-03 and 2025-12
   through identical code; class renumbering between them lives in G2
   events and does not corrupt the per-period key space.
10. **Unique (class, date)** — duplicate class key raises `ParseError`
    (tested); uniqueness verified live (0 dup keys, 0 dup ISINs).
11. **Revisions** — artifact versioning unchanged; identical bytes →
    `exported: false` with same `daily_fingerprint` (verified live).
12. **Independent fingerprint** — `daily_fingerprint` added;
    `dataset_fingerprint`/`registry_fingerprint` byte-identical to G1/G2.
13. **Quality states** — `observed` / `source_zero_sentinel` / `missing` /
    `invalid` per metric + `registry_state` per row. `invalid` preserves
    non-numeric raws verbatim (tested).
14. **CLI** — `nav` / `aum` / `investors` (identifier + `--from`/`--to`),
    `class` (identity + coverage). `--json` everywhere.
15. **No derived returns** — none computed; FONDTRIM reconciliation is G4.
16. **Missing-block classes** — 12 classes in 2025-12 carry key+ISIN with
    all three blocks absent → `missing` on every metric/day, verbatim.

## Findings recorded in the contract

- `NumeroClase=0` is the fund-level grain (2,158/2,484 classes in 2012-03) —
  a first-class key, not an absence marker.
- VL/patrimonio are officially EUR (explanatory PDF); FONDTRIM may differ
  by class currency — a G4 note, not reconciled here.
- Negative patrimonio is a real observed value (FI:5904:0:1); never
  reclassified.
- The all-zero-class phenomenon is modern: 2012-03 has none.

## Limits (honest)

- Sentinel semantics are measured and boundary-consistent, but CNMV does
  not state the rule explicitly; `raw` is preserved so any later correction
  is re-derivable without re-ingestion.
- `nav`/`aum`/`investors` resolve through the latest registry ≤ `--to`;
  a class absent from all ingested registry snapshots resolves only by
  full `FI:r:c:k` key.
- `daily_series` is per-share-class by construction; aggregated fund-level
  series are deliberately not offered (the source is class-grained).

## Checks

`pytest`: **73 passed** (20 new G3 tests, all synthetic fixtures).
`ruff`: clean. `mypy`: clean.
