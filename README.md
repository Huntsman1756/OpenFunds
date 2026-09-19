# cnmv-iic

Open, reproducible, traceable infrastructure to reconstruct the registry,
time series, portfolios, exposures, and historical lifecycle of Spanish
collective investment schemes (IIC) from official CNMV evidence.

**Status:** G0 viability research **PASS** (`docs/g0/results.md`) →
G1 FONDCART holdings ledger **PASS** (`docs/g1/results.md`, tag
`g1-holdings-pass`) → G2 FONDREGISTRO regulatory identity layer **PASS**
(`docs/g2/results.md`, tag `g2-identity-pass`) → G3 FONDMENS daily
share-class observations **PASS** (`docs/g3/results.md`, tag
`g3-daily-pass`) → G4 FONDTRIM + FONDPATRIMDISVAR implemented: quarterly
class-level metrics/fees/official returns and compartment patrimony +
variation, with informational cross-family reconciliation → G5 FONDDERI
implemented as a verbatim evidence ledger: compartment-level derivative
operations with official facet enums decomposed, instrument text preserved
verbatim, explicit `representation` state — never normalized, never
inferred → G6 portfolio change ledger implemented: published-snapshot
diffs with measured identity matching, strict change vocabulary (no
transaction verbs), unresolved ambiguous groups, conservation checks.

## What this is (and isn't)

- IS: a fail-closed pipeline from CNMV XML/ZIP publications to a canonical,
  queryable, historically complete position-level ledger (Parquet + DuckDB),
  with row-level provenance back to the source artifact's SHA-256.
- ISN'T: a fund comparison site, a ratings product, or a data dump — raw
  CNMV bytes are never redistributed (`docs/research/licensing.md`).

## Install

```bash
pip install cnmv-iic          # or: pip install -e ".[dev]" from a clone
```

## Five-minute value test

```bash
cnmv-iic update --period 2025-12        # one real CNMV period (~minutes)
cnmv-iic holdings ES0138841038          # a fund's reported portfolio
cnmv-iic funds-holding ES0000012F76     # funds reporting a position
cnmv-iic nav ES0138841038               # daily NAV series (FONDMENS)
cnmv-iic verify                         # re-derive fingerprints offline
```

A full `sync --from 2012-01` rebuilds the whole history: roughly a day of
polite CNMV downloads (~4k requests, ~1.5 GB raw artifacts, ~0.6 GB RAM
peak per period) yielding ~0.6 GB of Parquet.

## Use

```bash
# download one publication period, verify, store, export
cnmv-iic update --period 2025-12

# positions reported by a fund — by share-class ISIN or CNMV key
cnmv-iic holdings ES0138841038 --as-of 2025-12
cnmv-iic holdings FI:9:0 --as-of 2025-12
cnmv-iic holdings FI:9 --as-of 2025-12        # all compartments
cnmv-iic holdings 9 --as-of 2025-12           # numero_registro, FI default

# regulatory identity (FONDREGISTRO)
cnmv-iic fund ES0138841038                    # resolves to the fund record
cnmv-iic fund FI:9
cnmv-iic share-class ES0138841038

# institutions
cnmv-iic manager 190                          # gestora summary
cnmv-iic manager 190 --funds                  # + funds it manages
cnmv-iic depositary 211 --funds

# mechanical identity diff between two observed snapshots
cnmv-iic fund-events --from 2012-03 --to 2025-12
cnmv-iic fund-events --from 2012-03 --to 2025-12 --fund FI:9

# daily share-class observations (FONDMENS) — EUR, observed values only
cnmv-iic nav ES0138841038
cnmv-iic nav ES0138841038 --from 2025-01-01 --to 2025-12-31
cnmv-iic aum ES0138841038 --from 2025-01-01 --to 2025-12-31
cnmv-iic investors ES0138841038 --from 2025-01-01 --to 2025-12-31
cnmv-iic class ES0138841038                   # identity + observation coverage

# quarterly share-class metrics (FONDTRIM) — verbatim fields by unit basis
cnmv-iic metrics ES0138841038 --as-of 2025-12
cnmv-iic fees ES0138841038 --as-of 2025-12      # fee block, pct verbatim
cnmv-iic official-returns ES0138841038         # official CNMV returns

# compartment patrimony + variation (FONDPATRIMDISVAR)
cnmv-iic allocation FI:9:0 --as-of 2025-12      # stock (monetary) + flow (pct)

# derivative operations (FONDDERI) — verbatim evidence, never normalized
cnmv-iic derivatives FI:9:0 --as-of 2025-12
cnmv-iic derivatives ES0138841038 --as-of 2025-12   # class → owner compartment

# portfolio change ledger — published snapshots, never transactions
cnmv-iic portfolio-diff FI:9:0 2025-06 2025-12
cnmv-iic portfolio-diff FI:9:0 --as-of 2025-12 --previous  # prior snapshot
cnmv-iic position-history FI:9:0 ES0113900J37    # reported values, not buys
cnmv-iic portfolio-history FI:9:0                # per-snapshot aggregates

# informational cross-family comparison (equality never required)
cnmv-iic reconcile 2025-12
cnmv-iic reconcile 2025-12 --tolerance 0.005

# funds reporting a position in an instrument
# (REPORTED PORTFOLIO POSITIONS — not beneficial ownership)
cnmv-iic funds-holding ES0113900J37 --as-of 2025-12-31

cnmv-iic dataset-info
cnmv-iic source <artifact-id-or-sha-prefix>

# lifecycle: what happened to a fund (G9 derived read model)
cnmv-iic lifecycle-fund FI:5534                 # adjudication + edges
cnmv-iic predecessors-of FI:2359                # funds absorbed by it

# reproducible local build: backfill + lifecycle + offline verify
cnmv-iic sync --from 2012-01                    # --with-hr for the HR crawl
cnmv-iic verify                                 # re-derive all fingerprints
```

Every command accepts `--json` and `--data-dir` (default `~/.cnmv-iic`,
or `$CNMV_IIC_DATA_DIR`).

The supported Python surface is `cnmv_iic.api` (`open_dataset()` →
`Dataset`) — see `docs/releases/public-api-v0.1.md` for the frozen
contract, `docs/releases/user-guide-v0.1.md` for real examples, and
`docs/releases/distribution-policy.md` for what is redistributed.

## Compatibility

Frozen at v0.1 (`cnmv_iic.versions.contract()`, also in every manifest):
`dataset_schema_version=1`, `canonical_model_version=0.1.0`,
`lifecycle_engine_version=g9e-v1`, `parser_version=0.1.0`. A breaking
change to any layer requires bumping that version or an explicit
migration — never a silent semantic change under the same version.
`verify` reports `SAME_SOURCE_SET_SAME_DATASET` /
`SOURCE_REVISION_DETECTED` / `LOCAL_DERIVATION_MISMATCH` /
`MISSING_SOURCE_ARTIFACT`, so a CNMV republished ZIP is distinguishable
from a local reproducibility failure.

## Design guarantees

- **Exact semantics** — `Decimal` for all source values; observed
  (`reported_market_value`) and derived (`derived_weight`) fields separate.
- **Fail-closed identity** — CNMV keys only; masked (`XXXXXXXXXXXX`),
  absent, and malformed ISINs preserved explicitly via `isin_state`.
- **Fail-closed resolution** — an identifier resolves to
  `exact_share_class` / `exact_compartment` / `exact_fund`, or it fails
  (`ambiguous` / `not_found`). Never name-similarity matching.
- **No portfolio duplication** — N share classes of one compartment resolve
  to the same FONDCART portfolio owner; positions are never materialized
  per class.
- **Determinism** — canonical row order + independent SHA-256 fingerprints
  per family: `dataset_fingerprint` (positions), `registry_fingerprint`
  (identity), `daily_fingerprint` (FONDMENS), `quarterly_fingerprint`
  (FONDTRIM), `patrimony_fingerprint` (FONDPATRIMDISVAR),
  `derivatives_fingerprint` (FONDDERI).
- **Units never conflated** — monetary fields keep their denomination
  currency (`codigo_divisa` per class / `codigo_divisa_iic` per IIC);
  PDV flow fields are signed percentages over average daily patrimonio,
  kept rigidly apart from monetary stock fields. `RatioTotalGastos` is
  verbatim, never "TER"; official returns are verbatim, never recomputed.
- **Explicit observation states** — FONDMENS `'0'` is a no-observation
  sentinel (boundary-only, measured never interior). Every daily metric
  carries `observed` / `source_zero_sentinel` / `missing` / `invalid`, the
  verbatim `raw`, and NULL clean value unless observed. No forward-fill,
  no fabricated NAV, impossible calendar days rejected.
- **Class grain preserved** — NAV/AUM/investors are per share class and
  never deduplicated to the compartment (inverse of the holdings rule);
  `nav FI:9` fails closed.
- **Idempotent updates** — identical bytes → no-op; changed bytes → new
  artifact version linked via `supersedes`, never overwritten.
- **Quality as data** — per-snapshot reconciliation vs FONDPATRIMDISVAR:
  abs/rel diff, state (`exact`/`within_tolerance`/`divergent`/
  `unreconcilable`), tolerance. Divergent entities are kept.
- **Provenance to the row** — every position carries artifact id, artifact
  and member SHA-256, XML locator, parser name+version. An ISIN-resolved
  `holdings` response exposes the join: FONDREGISTRO artifact+locator →
  compartment key → FONDCART artifact+positions.
- **Conservative temporality** — registry rows carry `observed_period` and
  `source_artifact_id`; no `valid_from`/`valid_to` claims are derived yet.
  `fund-events` reports WHAT changed between two snapshots, never WHY.
- **Provenance-preserving lifecycle** (G9) — disappearance candidates are
  measured against a source-assertion ledger (weekly registry bulletins,
  relevant-information histories, FONDREGISTRO markers), never inferred
  from absence alone. Multi-party acts are normalized as
  `assertion_participants` with source-evidence roles (`ABSORBED`,
  `ABSORBING`, `SUBJECT`, …). A frozen 7-rule engine (`g9e-v1`) emits one
  adjudication per candidate — `ADJUDICATED_ABSORBED_BY`,
  `ADJUDICATED_LIQUIDATED`, `INDETERMINATE_*`, or `UNKNOWN_EXIT` — and
  only `ADJUDICATED_ABSORBED_BY` derives `lineage/edges` rows
  (`evidence_state=ADJUDICATED`, full assertion provenance). No invented
  effective dates, no confidence scores, no multi-successor
  auto-resolution, `unresolved` identity never promotes to exact.

## Cadence caveat (discovered in G0)

Full-cadence families (FONDCART etc.) ship in quarter-month ZIPs through
2022, but only in **June + December** ZIPs from 2023 — CNMV moved portfolio
disclosure to semiannual while the page text still says quarterly.
FONDREGISTRO and FONDMENS ship monthly, so `update` on a non-portfolio
month exports identity + daily tables only (`fondcart_present: false`);
`holdings` then falls back to the latest observed portfolio period ≤
as-of (exposed via `stale`/`resolution_mode`, or rejected with `--exact`).

## Layout

```
src/cnmv_iic/
  acquisition/   hardened CNMV client (redirect cap, ZIP limits, XXE-off)
  artifacts/     immutable content-addressed store + JSONL ledger
  schemas/       XSD fingerprint registry + known-deviation catalog
  adapters/      FONDCART (G1), FONDREGISTRO (G2), FONDMENS (G3),
                 shared XML helpers
  domain.py      canonical model (Decimal, fail-closed identity + keys)
  identity.py    resolution (fail-closed) + mechanical registry diff
  storage.py     deterministic Parquet + canonical fingerprints
  query.py       DuckDB read layer (positions + registry joins)
  lifecycle*.py  G9: source-assertion ledger, participants, evidence
                 profiles, frozen adjudication engine (g9e-v1),
                 derived read model
  api.py         stable public API (Dataset) — the supported contract
  verify.py      offline fingerprint re-derivation + invariant checks
  versions.py    compatibility contract (schema/model/engine/parser)
  cli.py         typer CLI
tests/           synthetic fixtures only — no CNMV bytes
docs/research/   landscape, source map, schema history, licensing, gaps, risks
docs/architecture/ principles, canonical model, provenance, temporal, storage
docs/decisions/  ADRs (001-006)
docs/g0..g9/     milestone adjudication reports
docs/releases/   versioned baselines
tools/g0_probe.py  reproducible CNMV probe
.research/       local evidence — gitignored, never published
```

## Current scope limits (deliberate non-goals)

No web/API, no corporate-group exposure graph, no look-through, no
typed/normalized derivatives
(FONDDERI stays a verbatim evidence ledger — no parsed underlier/strike/
expiry/counterparty, no pricing/greeks, no CDM/FpML/Strata/QuantLib
runtime), no FundsXML export, no bulk public dataset, no derived returns
(official returns belong to FONDTRIM — G4).
Issuer adjudication exists (G7/G8) but stays evidence-bounded: conflicts
are surfaced, never silently picked. Lifecycle adjudication (G9) covers
disappearance causes only (`ABSORBED_BY` / `LIQUIDATED` /
`INDETERMINATE_*` / `UNKNOWN_EXIT`) — it is not a general corporate-event
model, and identity episodes are not materialized yet.
FONDMENS `'0'` is recorded as a sentinel, never reinterpreted; the reason
for absence is not inferred.
