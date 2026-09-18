# G8-R results — coverage measurement and go/no-go adjudication

## Preregistered verdict criteria (fixed before measurement)

```text
current-period, resolved/valid_isin:
  >= 90%   -> GO strong
  70–90%   -> GO_WITH_COVERAGE_DISCLOSURE
  < 70%    -> scope reduction or another source needed

corroborated: no fixed threshold — it measures strength, not usability
historical periods: no universal threshold — every query must report
its own coverage
```

## Measured verdict

| metric                              | 2012-03 | 2025-12 |
|-------------------------------------|--------:|--------:|
| resolved / all_reported             | 12.02%  | 72.20%  |
| resolved / security                 | 13.08%  | 72.59%  |
| resolved / valid_isin               | 13.08%  | 73.02%  |
| corroborated / valid_isin           |  6.63%  | 39.01%  |
| ISIN-count resolution (comparison)  |   ~29%  |   ~86%  |

**Verdict: GO_WITH_COVERAGE_DISCLOSURE** for the current period.
73% of valid-ISIN value resolves to an issuer LEI — inside the
70–90% band, so issuer aggregation is useful but every output must
disclose coverage and evidence strength. Nearly half of resolved
value (34 of 73 points) is `single_source`, not corroborated —
strength must travel with the money.

**Historical period (2012-03): 13%** — issuer exposure over early
history is weak. This is not a reason to reduce current scope; it is
a reason every historical query must surface `coverage_ratio` so the
consumer can judge usability per question.

## Preregistered gate checklist

```text
1  value-weighted coverage measurable without heuristic identity   PASS
2  all FONDCART value conserves into explicit buckets              PASS
     (0 violations across 2,271 + 1,644 owners)
3  resolved exposure separable by evidence_strength                PASS
4  current-period coverage high enough to be useful                PASS
     (73.02% → GO_WITH_COVERAGE_DISCLOSURE band)
5  historical degradation measurable + explicitly surfaced         PASS
     (13.08% in 2012-03, per-period coverage contract)
6  duplicate-ISIN rows aggregate without violating source grain    PASS
     (position-row grain throughout)
7  conflict rows stay excluded from issuer totals                  PASS
     (€6.67bn in 2025-12 conflict value, excluded by construction)
8  issuer -> security -> fund reverse traversal deterministic      PASS
     (measured: top issuer 96 ISINs -> 784 reporting funds)
9  fund-of-funds exact-match rate measurable                       PASS
     (14.1% of 2025 IIC value expands domestically)
10 look-through graph constructs without fuzzy matching            PASS
     (1,610 edges, 0 self-loops, 0 cycles, depth 1)
```

## What the numbers actually say

1. **Value coverage < ISIN coverage** in both periods — the unresolved
   residue is *value-concentrated*, not diffuse.
2. **The residue is structural**: 2012 gap = Spanish public debt
   (Govt sector, ES0000012* ISINs, absent from GLEIF and FIRDS
   evidence); 2025 gap = foreign mutual-fund share classes (LU/IE,
   `Mutual Fund` type) + short-dated public debt.
3. **No adjudication fix exists** for the residue — G7 already
   consulted GLEIF, FIRDS, OpenFIGI, Level-2. Improvement is a
   provider question (e.g. Tesoro Público debt register, foreign
   fund-of-funds portfolio sources), not a rules question.
4. **Look-through is optional, not blocking**: 21.8% of 2025 value is
   fund-of-funds, but only 14% of that expands via exact domestic
   identity; the graph is a depth-1 DAG with zero cycles.
5. **The product shape that is now justified**:
   `issuer LEI -> ISINs -> FONDCART rows -> reporting funds`
   with `corroborated_value / single_source_value /
   conflict_excluded_value` decomposition and per-query
   `coverage_ratio` — never a bare euro figure.

## Explicit non-goals confirmed

- No `exposure --issuer` CLI yet — G8-R only measured cardinality.
- No Level-2 "group" aggregation — issuer / direct-parent /
  ultimate-parent stay separate universes.
- No transaction inference, no fuzzy matching, no conflict
  participation in issuer totals.
- No new providers in G8-R; the residual gap is documented for a
  future provider decision.
