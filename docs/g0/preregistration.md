# G0 preregistration — Quarterly Regulatory Data Viability

Written BEFORE fixing anything discovered; results recorded in results.md.

## Hypotheses (from brief §47)

H1 instrument-level portfolio data usable; H2 finite schema adapters;
H3 OSS reuse substantial; H4 no existing complete solution; H5 gap =
holdings-history/cross-fund queries; H6 publishable without problematic
redistribution; H7 identity stable; H8 ISINs sufficient; H9 derivatives
representable safely; H10 local Parquet/DuckDB sufficient.

## Preregistered sample

- Periods (schema generations): 2012-03, 2014-03, 2016-03, 2018-03, 2020-03,
  2022-03 (early quarterly era) + 2023-06, 2025-12 (post-change semiannual era)
  + monthly-only 2024-03, 2025-03, 2026-03 (cadence check).
- Structures: multi-compartment funds (observed: FI 241 w/ 4 compartments in
  2025-12), multi-class funds (FONMARCH 2 classes), SICAVs (SOCTRIM serie
  model), bond-heavy (FI 9 all-debt), fund-of-funds (DescripcionIF=IIC
  positions exist), derivatives users (4,965 FONDDERI ops).

## PASS/FAIL criteria (preregistered)

G0 passes only if ALL hold:

- A: all target families obtainable for sampled periods — via reproducible
  scrape+download.
- B: instance files either validate under published XSD OR deviations are
  enumerable and documented (strict validation is NOT required to pass —
  CNMV's own data defines reality).
- C: parser can be written so zero unknown elements are silently ignored.
- D: identity reconstructed deterministically from
  (Tipo, NºRegistro, Compartimento, Clase|Serie).
- E: portfolio positions representable without destructive flattening;
  reconciliation is measured and reported (any discrepancy rate is PASS as
  long as it is *measurable*, since we never force totals).
- F: ≥3 materially different historical periods ingest through identical code
  path.
- G: re-ingest of identical bytes → identical canonical state.
- H: identical bytes + parser version → identical output fingerprint.
- I: every row traces to artifact sha256 + member + period.
- J: code publishable as OSS without shipping CNMV data.

Outcomes per check: PASS / FAIL / INCONCLUSIVE / BLOCKED.
A FAIL is a valid result — criteria are NOT weakened post hoc.
