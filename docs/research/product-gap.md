# Product gap analysis

## What the source uniquely enables (verified)

From live inspection of FONDCART/SOCCART/FONDDERI/SOCDERI (2012 & 2025):

- **Position-level holdings with ISINs** for every Spanish IIC: ~103k positions
  in 2025-12 funds file alone, ~99.6% valid-format ISINs, ~148 CNMV-masked
  (`XXXXXXXXXXXX`). 2012 files have lower coverage (~94%) — still useful.
- Semi-structured instrument descriptors (`TIPO|ISSUER|COUPON|MATURITY`) stable
  since 2012 → issuer-name extraction possible as OBSERVED text (not resolved
  identity).
- Derivatives: ~5k operations per period, fields = category/underlying/
  instrument/amount/objective — verbatim-representable, not typed.
- Fund/compartment/class hierarchy + manager/depositary register numbers
  enable institutional aggregation and history.
- Official TER (RatioTotalGastos, 4 quarters), official rentabilidad,
  VocacionInversora, comisiones — fund reference data from the regulator,
  not a vendor.
- Patrimonio/variation block gives reconciliation anchors
  (TotalPatrimonio, CarteraInterior/Exterior, DPInversionesFinancieras).

## What does NOT exist (verified gap)

1. An open pipeline that turns these files into a queryable historical store.
2. Any free access to **historical** position-level holdings (Finect = current
   top-N; Morningstar/VDOS = paid; CNMV UI = per-fund PDF reports).
3. Security→funds reverse lookup across history.
4. Issuer-level exposure aggregation.
5. Snapshot-to-snapshot portfolio diff with honest (non-transactional)
   semantics.
6. Any reproducibility/provenance layer at all.

## Honest limitations (coverage doc material)

- Cadence is **semiannual from 2023** (June+December), quarterly before.
- Foreign IICs marketed in Spain appear in other CNMV registers, not in these
  files → no holdings for them.
- Beneficial ownership: not represented ("top-holders" means "funds reporting
  this position", never shareholder-register).
- No transactions, no intra-period changes, no prices — only period-end
  market values.
- Derivatives are free-text; exposure aggregation over them is a later,
  flagged-as-derived feature.
- `Importe` in FONDDERI semantics (notional vs market value) must be checked
  against the explanatory PDF before exposure math — until then: store
  verbatim, do not aggregate into exposure.

## Verdict on product boundary

Build the **regulatory holdings ledger**: acquisition → verified parsing →
canonical model → provenance-complete normalized store → CLI/SQL queries.
Skip: ratings, scoring, recommendations, portfolio analytics beyond diffs,
web UI (phase 2+ at most).
