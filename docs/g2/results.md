# G2 — Regulatory identity layer (FONDREGISTRO): adjudication

**Scope:** FONDREGISTRO adapter → canonical identity model (Fund /
Compartment / ShareClass / Institution) → deterministic registry tables →
fail-closed resolution → ISIN-aware `holdings` + `fund` / `share-class` /
`manager` / `depositary` / `fund-events` CLI.

**Verdict: PASS** — every gate below verified on live CNMV data at both
historical extremes plus a non-cadence month.

## Evidence

### Ingestion (live)

| Period   | Funds | Compartments | Share classes | Registry fingerprint | Notes |
|----------|-------|--------------|---------------|----------------------|-------|
| 2012-03  | 2,306 | 2,306        | 2,484         | `fa5cf9cdbc65…`      | oldest extreme |
| 2025-03  | 1,473 | 1,709        | 3,101         | `0c7a745d90c3…`      | registry-only month (no FONDCART) |
| 2025-12  | 1,438 | 1,674        | 3,102         | `71a77a5cc1ee…`      | newest extreme |

`dataset_fingerprint` (positions scope) is **byte-identical to G1** on both
extremes: `f53e607d…` (2025-12), `5359949a…` (2012-03).

### Resolution + join provenance (live, 2025-12)

```
cnmv-iic holdings ES0138841038
 → resolved_as: exact_share_class
 → share_class_key: FI:9:0:1        (CLASE A)
 → portfolio_owners: [FI:9:0]
 → registry_artifact_id: cnmv-iic-zip/2025-12/5f05feda…
 → registry_locator: FondRegistro/Entidad[1]/Compartimento[1]/Clase[1]
 → 111 positions, each with FondCart/Entidad[1]/… locator
   + source_artifact_id cnmv-iic-zip/2025-12/5f05feda…
```

Both sides of the join are exposed: FONDREGISTRO artifact + class locator on
the resolution side; FONDCART artifact + position locators on the ledger side.

### Gate-by-gate

1. **FONDREGISTRO adapter (small, verbatim)** — extracts only type, registro,
   denominacion, ETF, gestora/grupo, depositario/grupo, compartments,
   classes, ISIN. No speculative fields. Element paths registered from real
   2012-03/2025-12 inventories; unknown paths still fail closed.
2. **Canonical keys** — `fund_key=FI:9`, `compartment_key=FI:9:0`,
   `share_class_key=FI:9:0:1`, `share_class_isin=ES0138841038`. ISIN is a
   functional alias, never the internal key.
3. **Exact join with G1** — resolution targets the same `fund_key`
   compartment keys FONDCART reports; no name matching anywhere.
4. **Conservative temporality** — registry rows carry `observed_period` +
   `source_artifact_id`; no `valid_from`/`valid_to` claims.
5. **Identity history (mechanical)** — `fund-events` emits NAME_CHANGED,
   MANAGER_CHANGED, DEPOSITARY_CHANGED, ETF_CHANGED, SHARE_CLASS_ADDED/
   REMOVED, ISIN_CHANGED, COMPARTMENT_ADDED/REMOVED. Classes inside an
   added/removed compartment also emit class events (complete at both
   levels). Whole-fund add/remove is documented out-of-scope. No cause
   attribution. Live FI:9 2012→2025: manager rename (registro 190
   unchanged), depositary change (10→211), class renumbering (0 removed;
   1,2,3 added). Whole-dataset span: 2,375 events.
6. **ISIN validation parity** — share-class ISINs use the same ISO 6166/
   Luhn check as holdings. Synthetic test: invalid official ISIN preserved
   verbatim (`isin_state=invalid`), never corrected.
7. **Fail-closed resolution** — kinds: exact_share_class / exact_compartment
   / exact_fund / ambiguous / not_found. An ISIN present but not `valid`
   state → `ambiguous`, never resolved silently. Unknown ISIN → `not_found`.
   No approximate/name matching exists in the code path.
8. **No portfolio duplication** — `holdings ES0138841038`,
   `…1004`, `…1012` all return the identical 111-position snapshot of
   `FI:9:0` (verified row-equal live). Positions are keyed by compartment,
   never materialized per class.
9. **Join provenance** — see evidence block above; both artifacts and both
   locator chains in one response.
10. **Historical extremes + complex cases** — 2012-03 and 2025-12 both
    ingested; multi-compartment case verified: `FI:5669` GVC GAESCO
    CROSSOVER, FI — 19 compartments, 70 share classes; `holdings FI:5669`
    → `exact_fund`, 19 owners, 816 positions. As-of works: same ISIN
    resolved at 2012-03 → 63 positions.
11. **Determinism + idempotence** — separate `registry_fingerprint`
    (canonical rows, Parquet-independent); second `update` →
    `exported: false`, identical fingerprints. G1 `dataset_fingerprint`
    scope unchanged.
12. **Backward compatibility** — `holdings FI:9:0` returns row-identical
    output to the ISIN path and to G1; `dataset_fingerprint` values
    unchanged on both periods. Key-based resolution against positions is
    preserved when FONDREGISTRO lacks an entity FONDCART reports
    (exact match only — no fuzzy fallback).

### New behavior worth noting

- **Registry-only months.** FONDREGISTRO ships monthly even when FONDCART
  doesn't. `update --period 2025-03` now exports identity tables with
  `fondcart_present: false` and no phantom positions partition — the G1
  "clean failure" became a clean partial export, which is the honest
  semantics: the month isn't broken, it just has no portfolio disclosure.
- **`funds-holding` enrichment** — rows now include `denominacion` from
  FONDREGISTRO at the same period (22/22 named on live data). Semantics
  label unchanged: "reported portfolio positions (not beneficial
  ownership)".

### Verification status

- `pytest tests/` — **49 passed** (22 new G2 tests: adapter, resolution,
  diff, end-to-end joins, determinism; all synthetic fixtures).
- `ruff check src tests` — clean.
- `mypy src` — clean (19 files).
- Live: 2012-03, 2025-03, 2025-12 ingested via real acquisition path;
  idempotent re-run verified.

### Explicit non-goals honored

No FONDMENS / FONDTRIM / FONDPATRIMDISVAR (beyond the existing G1
reconciliation read) / FONDDERI parsing, no issuer resolution, no
corporate-group exposure, no portfolio-diff, no look-through, no REST API,
no frontend, no FundsXML export.

### Known limits

- Share-class resolution is per-period: an ISIN resolves at the latest
  registry observation ≤ as-of; registry history itself is not yet
  queryable as intervals (deliberate — observed-period semantics only).
- Whole-fund addition/removal between snapshots is not yet an event kind
  (documented out-of-scope; candidates for G3+).
- `funds` parquet stores institution denominacion verbatim per fund —
  institutions are not yet a first-class entity table.

## Post-adjudication contract tightening

Two findings were raised at adjudication and fixed immediately after the
`g2-identity-pass` tag (commit follows the tag):

1. **Fallback must never look contemporaneous.** `holdings` and
   `funds-holding` now always emit `requested_as_of`, `portfolio_period`,
   `resolution_mode` (`latest_available_before_or_on` | `exact`) and
   `stale` (`true` when the returned snapshot predates the requested
   as-of month). New `--exact` flag fails when no snapshot exists at the
   as-of month — no silent fallback. Verified live:
   `holdings ES0138841038 --as-of 2025-10-31` →
   `portfolio_period: 2012-03, stale: true`;
   `--exact` at 2025-10 → `no positions snapshot exactly at 2025-10`.
2. **Resolution vocabulary.** `invalid_identifier` added between
   `exact_*` and `ambiguous`: masked/malformed/bad-check-digit ISINs are
   invalid identifiers, not ambiguities. `ambiguous` is now reserved for
   >1 plausible resolutions (e.g. one ISIN on two share classes).
   Verified: `ES0138841039` → `invalid_identifier`; duplicated-ISIN
   fixture → `ambiguous`.
