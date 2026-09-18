# cnmv-iic

Open, reproducible, provenance-preserving data infrastructure for Spanish
collective investment schemes (IIC), built on official CNMV dissemination
files.

**Status:** G0 viability research **PASS** (`docs/g0/results.md`) →
G1 vertical slice implemented: acquisition → FONDCART adapter → canonical
positions → Parquet → DuckDB → CLI.

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

# positions reported by a fund (CNMV key: <tipo>:<numero_registro>:<compartimento>)
cnmv-iic holdings FI:9:0 --as-of 2025-12-31
cnmv-iic holdings 9 --as-of 2025-12-31        # numero_registro, FI default

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
- **Determinism** — canonical row order + `dataset_fingerprint` (SHA-256 of
  canonical rows, independent of Parquet bytes).
- **Idempotent updates** — identical bytes → no-op; changed bytes → new
  artifact version linked via `supersedes`, never overwritten.
- **Quality as data** — per-snapshot reconciliation vs FONDPATRIMDISVAR:
  abs/rel diff, state (`exact`/`within_tolerance`/`divergent`/
  `unreconcilable`), tolerance. Divergent entities are kept.
- **Provenance to the row** — every position carries artifact id, artifact
  and member SHA-256, XML locator, parser name+version.

## Cadence caveat (discovered in G0)

Full-cadence families (FONDCART etc.) ship in quarter-month ZIPs through
2022, but only in **June + December** ZIPs from 2023 — CNMV moved portfolio
disclosure to semiannual while the page text still says quarterly.
`update` on a month without FONDCART fails cleanly.

## Layout

```
src/cnmv_iic/
  acquisition/   hardened CNMV client (redirect cap, ZIP limits, XXE-off)
  artifacts/     immutable content-addressed store + JSONL ledger
  schemas/       XSD fingerprint registry + known-deviation catalog
  adapters/      FONDCART adapter (only adapter in G1)
  domain.py      minimal canonical model (Decimal, fail-closed identity)
  storage.py     deterministic Parquet + canonical fingerprint
  query.py       DuckDB read layer
  cli.py         typer CLI
tests/           synthetic fixtures only — no CNMV bytes
docs/research/   landscape, source map, schema history, licensing, gaps, risks
docs/architecture/ principles, canonical model, provenance, temporal, storage
docs/decisions/  ADRs (001-006)
docs/g0/         preregistered viability criteria + results
tools/g0_probe.py  reproducible CNMV probe
.research/       local evidence — gitignored, never published
```

## G1 scope limits (deliberate non-goals)

No FONDMENS/FONDTRIM/FONDDERI adapters yet, no web/API, no issuer
resolution, no portfolio-diff, no typed derivatives, no FundsXML export,
no bulk public dataset. Fund share-class ISIN lookup needs FONDREGISTRO
(post-G1) — use the CNMV key for `holdings` meanwhile.
