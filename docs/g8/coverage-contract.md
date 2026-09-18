# G8 coverage contract — denominators, grain, sign, conservation

G8 aggregates money, not identifiers. This contract fixes the
denominators and invariants before any coverage percentage is quoted.

## Grain: the position row — never `unique ISIN`

Two FONDCART rows reporting the same ISIN contribute independently to
issuer totals. G6's unresolved temporal matching (cannot assert
`rowA(t1) == rowA(t2)`) is a *different* problem: for a point-in-time
exposure snapshot both rows contribute to `issuer LEI` without
collapsing source rows.

```text
Position(market_value, owner, period, isin)
    -> exact join -> security_resolution(state, resolved_lei)
    -> LegalEntity
```

## Value policy: absolute as primary, signed preserved

`reported_market_value` sign distribution, measured:

```text
2012-03: 1 negative row (−€49,795.95)  delta(abs−signed) = €99,592
2025-12: 4 negative rows (−€24,972)    delta = €49,944
```

Cancellation is negligible but nonzero. Contract: coverage metrics
use `abs(reported_market_value)`; the signed value is always stored
alongside and never overwritten.

## Denominator vocabulary (never a single denominator)

```text
all_reported_market_value        every position row incl. cash
security_market_value            kind='security'
valid_isin_market_value          security rows with isin_state='valid'
issuer_resolved_market_value     corroborated + gleif_only + firds_only
corroborated_market_value        evidence_strength='corroborated'
single_source_market_value       gleif_only + firds_only
conflict_market_value            state='conflict' (excluded from issuer)
multiple_candidates_market_value state='multiple_candidates'
no_authoritative_market_value    state='no_authoritative_match'
invalid_masked_no_isin           security rows without usable ISIN
cash_market_value                kind='cash' (deposits)
```

## Conservation invariant (per period AND per owner)

```text
resolved + conflict + multiple + no_authoritative
  + invalid_masked_no_isin + cash
= all_reported_market_value
```

Measured live: **0 violations across 2,271 owners (2012-03) and
1,644 owners (2025-12)**. Any aggregate output must include
`included_value`, `excluded_value`, `excluded_reasons`,
`coverage_ratio` — a row may be excluded, never lost.

## Evidence strength travels with the money

Every issuer aggregate decomposes:

```text
corroborated_value    two independent official sources agree
single_source_value   one source only — weaker, disclosed separately
conflict_value        NEVER inside issuer totals (NULL resolved_lei)
```

`evidence_strength` is the frozen G7-F derived field; G8 consumes it,
never re-derives strength from state names.

## Temporal semantics

Coverage is computed **per period, never blended**: provider evidence
is current enrichment (2026), so historical coverage reflects
"resolvable as known today", not "known in 2012". Every coverage
figure is quoted per period with this caveat.
