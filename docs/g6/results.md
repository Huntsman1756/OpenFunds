# G6 — Historical portfolio change semantics: adjudication

**Scope:** snapshot-diff layer over the G1 FONDCART ledger — a
*change ledger*, never inferred transactions. `portfolio_diff` /
`position_history` / `portfolio_history` in `query.py`; CLI
`portfolio-diff` / `position-history` / `portfolio-history`.

Contract measured before implementation: `docs/g6/contract.md`.
Reuse survey: `docs/g6/oss-review.md` — FundsXML `delta_diff`
pattern adapted (exact identity → added/removed/changed,
streaming); edgartools + rust-sec-fetcher REFERENCE_ONLY; 13F
transaction-verb semantics rejected for CNMV.

**Verdict: proposed PASS** — matching is two-phase (identity, then
change), every gate verified synthetically and live; the measured
identity contract is enforced, not assumed.

## Evidence

### The measured contract (docs/g6/contract.md)

- Valid ISIN: 94.1% → 99.6% of rows across 8 snapshots; `masked`
  (`XXXXXXXXXXXX`) appears 2023-06+ (10 → 148).
- ISIN is NOT a row key: 0.6–1.8% of valid rows share an ISIN inside
  the same portfolio — structural (repos, lots, same ISIN two roles),
  never noise.
- Descriptor churn 18–30% between snapshots for the same
  `(portfolio, ISIN)` pair — descriptors are change *output*, never
  match *input*.
- Verbatim-signature matches for non-valid rows: 3–4 per snapshot
  pair — the basis exists, honestly rare.

### Live verification (.tmp-live: FONDCART 2012-03 + 2025-12)

```
cnmv-iic portfolio-diff FI:9:0 2012-03 2025-12
 → explicit_periods | elapsed 5,023 days | both artifacts recorded
 → 63 old / 111 new — 0 matched (13.75y: no ISIN persists)
 → conservation: holds=true both sides
 → official_patrimony_variation: flows -4.88, yield +2.15,
   mgmt -0.95 (context only — no causal attribution)

cnmv-iic portfolio-diff FI:9:0 --as-of 2025-12 --previous
 → error: previous_published_snapshot_not_loaded=2025-06
   — run `cnmv-iic update --period 2025-06` first
   (never silently jumps to the only loaded snapshot, 2012-03;
   post-2023 June+December cadence is measured — the published
   previous is 2025-06 and it is absent locally)

cnmv-iic portfolio-diff FI:4209:0 2012-03 2025-12
 → 5 old / 102 new, conservation holds
   (owner carries dup ISINs in BOTH eras — unpaired rows stay
   unresolved-capable; none shared across the 13.75y gap)

cnmv-iic portfolio-diff FI:9:0 2025-03 2025-12
 → error: no FONDCART data for 2025-03 — not a published snapshot

cnmv-iic position-history FI:9:0 ES0000012F76
 → reported value history — observed values, derived weights
   flagged, dup rows flagged not collapsed

cnmv-iic portfolio-history FI:9:0
 → per-snapshot n_positions / totals / cash-security split
```

### Change vocabulary (strict)

`added_position` / `removed_position` / `unchanged_position` /
`market_value_changed` / `weight_changed` /
`market_value_and_weight_changed` / `source_metadata_changed` /
`unresolved`. Forbidden verbs (`BOUGHT`, `SOLD`, `NET_FLOW`,
`TURNOVER`, …) appear nowhere — snapshot differences prove state
change only.

`weight` fields carry `derived` / `derived_from_derived` states;
`market_value` deltas are `observed_delta` over `Decimal`.

### Gates (user-preregistered)

| # | Gate | Evidence |
|---|------|----------|
| 1 | Deterministic snapshot selection | `--previous` never silently skips a measured published snapshot — fails `previous_published_snapshot_not_loaded=2025-06` (live + tested); outside the measured window, dataset-local previous (tested 2018-03→2020-03) |
| 2 | No comparisons vs unavailable periods | `NotFoundError` — "not a published snapshot" (both directions tested) |
| 3 | Exact identifier matching measured | G6-R §2 — 98.2–99.4% unique-in-portfolio |
| 4 | Duplicate identifiers documented | `unresolved` groups w/ both sides' rows preserved — never summed |
| 5 | Masked/invalid never authoritative | `identifier_authority=none` on every non-valid path |
| 6 | No fuzzy matching | descriptors excluded from match keys by construction |
| 7 | No transaction verbs | vocabulary enumerated in code; asserted in tests |
| 8 | Decimal for all deltas | `Decimal` arithmetic throughout |
| 9 | Derived weights marked | `derived` / `derived_from_derived` states on every weight field |
| 10 | Both artifacts preserved | `from_artifact`/`to_artifact` + per-row provenance both sides |
| 11 | Deterministic diff fingerprint | two identical calls → identical sha256 (tested) |
| 12 | A→B / B→A symmetry | added↔removed symmetric (tested) |
| 13 | A→A = zero changes | all `unchanged_position` (tested) |
| 14 | G1–G5 fingerprints unchanged | no ingest code touched; manifests verified live |
| 15 | 2012 + 2025 cadence live | diff verified on both era extremes |
| 16 | Empty/absent owner semantics | `owner_absent` → honest all-added/all-removed (tested) |
| 17 | Derivatives excluded from matching | `individual_position_diff: unavailable` + reason, always emitted |

Conservation gate: `matched + added + unresolved_new = count(new)`,
`matched + removed + unresolved_old = count(old)` — reported per side
with `holds` flag; never "fixed" by heuristic.

### Quality

- `pytest` — 155 passed (15 G6 tests).
- `ruff check src tests` — clean.
- `mypy src` — clean.

## Commits

```
afc3147 G6-R: OSS reuse review + measured identity contract
3736c90 G6-A..D: portfolio change ledger over published snapshots
```
