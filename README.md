# cnmv-iic

Open, reproducible, provenance-preserving data infrastructure for Spanish
collective investment schemes (IIC), built on official CNMV dissemination
files.

**Status:** G0 viability research **PASS** (`docs/g0/results.md`) →
G1 FONDCART holdings ledger **PASS** (`docs/g1/results.md`, tag
`g1-holdings-pass`) → G2 FONDREGISTRO regulatory identity layer **PASS**
(`docs/g2/results.md`, tag `g2-identity-pass`) → G3 FONDMENS daily
share-class observations implemented: NAV/AUM/investors per
`(share_class_key, observation_date)` with explicit observation states.

## What this is (and isn't)

- IS: a fail-closed pipeline from CNMV XML/ZIP publications to a canonical,
  queryable, historically complete position-level ledger (Parquet + DuckDB),
  with row-level provenance back to the source artifact's SHA-256.
- ISN'T: a fund comparison site, a ratings product, or a data dump — raw
  CNMV bytes are never redistributed (`docs/research/licensing.md`).

## Install

```bash
pip install -e ".[dev]"
```

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

# funds reporting a position in an instrument
# (REPORTED PORTFOLIO POSITIONS — not beneficial ownership)
cnmv-iic funds-holding ES0113900J37 --as-of 2025-12-31

cnmv-iic dataset-info
cnmv-iic source <artifact-id-or-sha-prefix>
```

Every command accepts `--json` and `--data-dir` (default `~/.cnmv-iic`,
or `$CNMV_IIC_DATA_DIR`).

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
- **Determinism** — canonical row order + `dataset_fingerprint` (positions),
  `registry_fingerprint` (identity tables) and `daily_fingerprint`
  (FONDMENS), all SHA-256 over canonical rows, independent of Parquet bytes.
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
  cli.py         typer CLI
tests/           synthetic fixtures only — no CNMV bytes
docs/research/   landscape, source map, schema history, licensing, gaps, risks
docs/architecture/ principles, canonical model, provenance, temporal, storage
docs/decisions/  ADRs (001-006)
docs/g0,g1,g2/   milestone adjudication reports
tools/g0_probe.py  reproducible CNMV probe
.research/       local evidence — gitignored, never published
```

## Current scope limits (deliberate non-goals)

No FONDTRIM/FONDPATRIMDISVAR/FONDDERI adapters yet, no web/API,
no issuer resolution, no corporate-group exposure, no portfolio-diff,
no look-through, no typed derivatives, no FundsXML export, no bulk public
dataset, no derived returns (official returns belong to FONDTRIM — G4).
Identity history is mechanical (WHAT changed) — fund
additions/removals as whole events and cause attribution are out of scope.
FONDMENS `'0'` is recorded as a sentinel, never reinterpreted; the reason
for absence is not inferred.
