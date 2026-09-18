# OpenFunds ES — final research report & verdict

Date: 2026-09-17 · Method: live CNMV downloads + code-level repo inspection.

## Executive conclusion: **BUILD** — under a different name

The project deserves to exist. The differentiating asset (historical,
position-level, provenance-preserving Spanish IIC holdings ledger built from
official CNMV dissemination files) is feasible, unserved by existing OSS or
open products, and small enough to be boring technology.

**Name:** rename to **`cnmv-iic`** (ADR-006). "OpenFunds ES" collides with the
openfunds.org standard/association.

## Evidence summary — what CNMV actually provides

- Public, unauthenticated, tokenized-URL ZIP downloads per month, **all months
  2012→present enumerated** via `?ejercicio=YYYY`.
- 11 XML families + XSDs + explanatory PDFs per ZIP. Monthly = registry + daily
  NAV/participants/patrimonio per class. **Full-cadence adds per-position
  portfolios (securities + derivatives), TER, official rentabilidad,
  vocación, P&L/patrimonio variation — quarterly through 2022, semiannual
  (June+December) from 2023.**
- 2025-12 fund portfolio file: 103,130 positions / 1,432 entities; 99.6%
  valid-format ISINs; issuer/coupon/maturity embedded in pipe-delimited text;
  ~5k derivative operations (free-text, verbatim-safe).
- SICAV mirror files (SOC*) identical in shape (Serie vs Clase).
- XSDs byte-identical across the entire sampled history — **one adapter
  generation**; real instances deviate from XSDs in enumerable, documented
  ways (optional-in-practice elements).

## Existing OSS — what can be reused

- **Aletheia (MIT, C#)**: reference implementation for acquisition hardening
  (size caps, redirect limits, ZIP ratio/entry caps, DTD-off XML, cache,
  fingerprint, provenance record). Port patterns, not code.
- **fundsxml/schema (MIT) + examples (Apache-2.0)**: interop vocabulary +
  future export target.
- **cnmv-xbrl (MIT, Python)**: prior art for CNMV-adjacent parsing (different
  surface: XBRL estados).
- ticker-lab (unlicensed): evidence of mechanics only. PDF scrapers
  (delaosash, afernandez119): DO_NOT_USE. qumundo/funds: proprietary.

## Missing layer

Everything between "raw tokenized ZIPs" and "queryable historical holdings
ledger": artifact registry, deviation-aware parsing, canonical identity model,
cross-fund security index, honest diffs, dataset fingerprinting. Nothing —
open or commercial-free — provides it.

## Legal constraints

- Software + manifests + hashes: publishable now (PROVEN/LIKELY).
- Raw archive redistribution: AMBIGUOUS → default NO (ship downloader).
- Bulk normalized dataset/API: LIKELY under PSI reuse conditions with
  attribution, but flagged REQUIRES_LEGAL_REVIEW before hosting.

## Canonical model (minimum correct)

`Institution(register_no)` · `Vehicle(tipo, register_no)` → `Compartment` →
`ShareClass|Series(isin)`; observations: `NavDaily`, `ClassQuarterFacts`,
`CompartmentFlow`, `PortfolioSnapshot{SecurityPosition, DerivativePosition}`.
All period- and artifact-stamped; names are attributes, never keys.

## Architecture (post-G0)

Python · lxml iterparse (DTD off, caps) · hardened acquisition
(Aletheia-pattern) · JSONL artifact ledger · Parquet per family/period ·
DuckDB query layer · Typer CLI. No services, no LLM, no guessing.

## G0 design & result

Preregistered criteria (docs/g0/preregistration.md) executed live:
**PASS on all checks** — acquisition reproducible, schema registry viable,
positions parseable, reconciliation measurable (254 exact / ~1007 <0.1% /
171 divergent entities — reported, never forced), provenance-by-design,
code publishable without data. Codified probe: `tools/g0_probe.py`.

## Risks (top)

Publication-surface change (R1), normalized-data legal ambiguity (R2),
reconciliation gap semantics (R3), ISIN masking/gaps (R4), derivative
free-text (R5). Full register: risks.md.

## Estimated complexity

Genuinely moderate: ~11 narrow adapters on a single frozen schema generation,
GB-scale data, no infra. Bulk of effort = correctness machinery (provenance,
deviation registry, quality reporting), not scale. A disciplined G1 (vertical
slice: acquire→parse→Parquet→`holdings`+`funds-holding` CLI) is a reasonable
next gate.

## Explicit non-goals

Fund scoring/recommendations, NAV for foreign IICs, pension plans (DGSFP),
beneficial-ownership claims, transaction inference, web UI (phase ≥2),
real-time data, redistributing CNMV bytes.
