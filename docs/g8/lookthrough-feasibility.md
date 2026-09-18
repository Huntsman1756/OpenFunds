# G8-R5 — look-through feasibility probe (measured, not implemented)

FundsXML semantics adapted: identify candidates first, expand only
when the target portfolio exists in our own data. No recursion, no
weight multiplication — a feasibility measurement only.

## Candidate universe

CNMV `descripcion_if = 'IIC'` positions — funds holding other funds.

| period   | IIC rows | IIC abs value | % of all value |
|----------|---------:|--------------:|---------------:|
| 2012-03  |   6,101 | €10,574,211,968 | 8.6% |
| 2025-12  |  11,754 | €94,910,429,627 | 21.8% |

Fund-of-funds exposure is economically large and growing.

## Exact-match classification

A look-through candidate is *expandable* only if its ISIN matches a
CNMV share class exactly (`share_classes.isin_raw`, isin_state=valid)
— meaning the target fund's own FONDCART portfolio exists in our data.

| period   | state | rows | abs value | % IIC value |
|----------|-------|-----:|----------:|------------:|
| 2012-03  | EXACT_DOMESTIC_FUND_MATCH |   879 |  €3,779,520,219 | 35.7% |
|          | EXTERNAL/UNRESOLVED       | 5,215 |  €6,792,336,767 | 64.2% |
|          | (non-valid ISIN)          |     7 |      €2,354,982 |  0.02% |
| 2025-12  | EXACT_DOMESTIC_FUND_MATCH |   802 | €13,361,942,645 | 14.1% |
|          | EXTERNAL/UNRESOLVED       |10,947 | €81,463,203,350 | 85.8% |
|          | (non-valid ISIN)          |     5 |     €85,283,632 |  0.09% |

Interpretation: most IIC value points to *foreign* funds (LU/IE share
classes) whose portfolios we do not hold — exact-match domestic
expansion could look through only €13.4bn (14%) of 2025 IIC value.
Full look-through of foreign targets is out of scope; it would
require foreign fund-of-funds portfolio sources.

## Fund→fund graph (exact edges only)

Built from `IIC position → share_classes` exact ISIN join:

```text
edges (distinct holder→target fund pairs): 1,610
holder funds with fund positions:            540
self_loops:   0
cycles:       0
max_depth:    1   — every edge lands on a target with no
                    further domestic fund positions detected
```

The graph is a DAG with depth 1: no `A→A`, no `A→B→A`, no nested
domestic chains. A future look-through expansion needs only a
single-level substitution with a `max_depth=1` guard — no cycle
policy is currently exercised, but the guard stays in the contract.

## Measured verdict

```text
lookthrough_candidate_weight (2025-12):  21.8% of all reported value
resolvable_lookthrough_weight:            14.1% of IIC value (exact
                                          domestic match only)
unresolvable_fund_weight:                 85.8% of IIC value (foreign
                                          targets, no portfolio data)
```

Look-through is feasible *as a bounded, exact-match, depth-1
expansion* — and even then it re-labels only ~3% of total portfolio
value. It is an optional layer, not a prerequisite for issuer
aggregation.
