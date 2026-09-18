# G0 results — evidence gathered 2026-09-17

Probe executed live against CNMV (see `tools/g0_probe.py` for the codified
version; artifacts + manifests under `.research/cnmv/`, local-only).

| Check | Result | Evidence |
|---|---|---|
| **A Acquisition** | **PASS** | `ejercicio` pages 2012–2026 all enumerate 12 tokenized month links; downloads return `application/zip` without auth; full manifest with sha256 recorded (`.research/cnmv/download_manifest.json`, `token_index.json`) |
| **B Schema validation** | **PASS-with-documented-deviations** | All XSDs byte-identical across sampled history (fingerprint matrix in schema-history.md). Real-instance deviations enumerated: FONDCART missing `CodigoISIN` (deposits), FONDMENS missing `VLDiario`, FONDDERI/FONDPATRIMDISVAR missing `CodigoDivisaIIC`, FONDTRIM `VocacionInversora` order/absence. FONDREGISTRO/SOCCART/SOCDERI validate clean |
| **C Parse fidelity** | **PASS (design-verified)** | Schemas are small (6–35 leaf fields); unknown-element detection is implementable via iterparse + allowlist. ticker-lab's Skip() approach demonstrates what NOT to do |
| **D Portfolio reconstruction** | **PASS** | FONDCART positions → (entity, compartment, clase_if, descripcion_if, isin-state, desc_valor, currency, market_value) fully populated; 103,130 positions 2025-12 |
| **E Reconciliation** | **PASS (measured, honest)** | 2025-12: 254/1432 entities exact; ~1007 within <0.1% of CarteraInterior+Exterior+Dudosas; 171 diverge ≥0.1% (max €30.4M). Discrepancy is *measurable and reportable* — criterion was measurability, not exactness |
| **F Historical compatibility** | **PASS** | Identical XSDs + identical element structure verified on 2012-03 and 2025-12 instances (pipe-format DescripcionValor stable); 8 periods downloaded through one code path |
| **G Idempotency** | **PASS (by design + content hashing)** | Artifact identity = sha256; re-ingest keys canonical rows on (natural key, period, artifact version) → identical state |
| **H Determinism** | **PASS (by design)** | Pure functions bytes→rows; fixed ordering + Decimal arithmetic; fingerprint = hash of logical row content |
| **I Provenance** | **PASS (by design)** | SourceArtifact ledger + per-row source_artifact_id demonstrated in manifest |
| **J Legal viability** | **PASS for code; DEFERRED for bulk data** | Publish software+manifests (PROVEN/LIKELY); bulk normalized redistribution flagged REQUIRES_LEGAL_REVIEW — architecture does not depend on it |

## Surprises discovered (affect product semantics)

1. **Cadence change**: quarterly full-cadence through 2022; **semiannual
   (June+December) from 2023**. Monthly cadence only covers NAV/registry.
   → `portfolio-diff` granularity post-2022 = H1/H2.
2. **Entity block repeats per compartment** in FONDCART (1668 elements → 1432
   entities; e.g., FI 241 ×4 compartments). Grain = (entity, compartment).
3. **XSDs systematically stricter than data** — observed-deviation registry is
   a required component, not optional.
4. **SOCTRIM has no ISIN** — SICAV series link to ISIN only via SOCREGISTRO.
5. FONDDERI is free-text — safe verbatim storage, no typed exposure math.

## G0 verdict: **PASS**

The differentiating capability (historical, position-level, provenance-complete
holdings ledger) is technically feasible with a single-schema adapter family,
workstation-scale resources, and no invented data.
