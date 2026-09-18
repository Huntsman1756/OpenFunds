# G8-R0 — OSS reuse review: exposure aggregation, look-through, reverse holdings

Scope: G8 needs issuer-exposure aggregation over CNMV position rows.
Reviewed for proven patterns worth adapting — no code copied, DuckDB
already provides the mechanics. What is reused is *query semantics*.

## Findings

### FundsXML examples (fundsxml/examples, MIT)

`XQuery_Examples/` contains the three canonical patterns:

- **aggregate-by-assettype.xq** — `Position → AssetMasterData/Asset`
  join via shared `UniqueID`, `group by AssetType`, grand total
  emitted for reconciliation. This is exactly the canonical
  `position row → identity master → aggregate → reconcile` shape.
  **ADAPT PATTERN**: position row → `security_resolution` → group,
  always emit a reconciling total.

- **top-holdings.xq** — N largest holdings by *observed* value,
  asset name resolved through the same UniqueID join.
  **ADAPT PATTERN**: ranking on reported value, identity via join.

- **look-through.xq** — positions whose asset is a share class (`SC`)
  are flagged as look-through *candidates*; the query reports
  `LookThroughWeight` vs `DirectlyHeldWeight` and explicitly does NOT
  expand nested portfolios (they are rarely in the same file).
  **ADAPT SEMANTICS**: identify candidates first, expand only when the
  target portfolio exists in our own data — never pretend a fund
  position is a final holding, never invent its contents.

### 13f.info / edgartools (web service + OSS)

- **13f.info** — the reverse-holdings navigation:
  `security → every manager reporting it`,
  `manager → full holding history`. Cardinality-first reporting.
  **ADAPT QUERY PATTERN**: `issuer LEI → resolved ISINs → FONDCART
  rows → reporting funds`. Measure cardinality in G8-R before any CLI.

- **edgartools** holdings history — view/API concepts for holder
  timelines. **REFERENCE** — useful vocabulary, nothing to copy.

- **13F transaction/change inference** — several tools infer buys/
  sells from snapshot diffs. **REJECT** — G6 already established that
  inferring transactions from snapshots is unsound; out of scope.

### What is NOT needed

- No provider SDK, no aggregation framework, no graph library —
  DuckDB `GROUP BY` + recursive CTE (if ever needed) suffice.
- No fuzzy matching library — identity resolution is already closed
  in G7; G8 consumes `resolved_lei`, it never re-resolves.

## Reuse decision table

| source | disposition | what is reused |
|---|---|---|
| FundsXML aggregate-by-assettype | ADAPT PATTERN | group + reconcile-total shape |
| FundsXML top-holdings | ADAPT PATTERN | value-ranked holdings view |
| FundsXML look-through | ADAPT SEMANTICS | candidates-first, expand-if-known |
| 13f.info reverse holders | ADAPT QUERY PATTERN | issuer→ISIN→fund traversal |
| edgartools holdings views | REFERENCE | API vocabulary only |
| 13F transaction inference | REJECT | unsound, excluded by G6 |

## Consequence for G8 design

1. Grain is the **position row**, never `unique ISIN` — two rows
   sharing an ISIN contribute separately to issuer totals.
2. Every aggregate carries a **reconciling total** and an
   `excluded` bucket — no row may vanish silently.
3. Look-through is **candidates-first**: `fund/share-class` positions
   are measured as candidates; expansion only happens when the target
   fund's own FONDCART snapshot exists (exact ISIN match to a CNMV
   share class — never fuzzy).
4. Evidence strength travels with the money: every issuer aggregate
   is decomposed into `corroborated / single_source / unresolved`.
