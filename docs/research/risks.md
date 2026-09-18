# Risk register (ranked by impact)

| # | Risk | Evidence | Impact | Mitigation |
|---|---|---|---|---|
| R1 | CNMV changes/removes publication surface | Page format already changed once (quarterly→semiannual cadence ~2023; filename casing varies); nota legal reserves right to modify/suspend | High — kills acquisition | Immutable artifact store pins what we have; fail-closed acquisition reports structural changes; manifest hashes detect silent edits |
| R2 | Legal ambiguity on bulk normalized redistribution | licensing.md — CNMV claims copyright; PSI law likely permits with attribution | High for dataset publishing, low for code | Default architecture: ship downloader, not data. Legal review before hosting a public normalized dump/API |
| R3 | Reconciliation gaps in portfolio sums | 2025-12: ~12% of entities off ≥0.1% vs CarteraInterior+Exterior+Dudosas (max 30.4M); reasons unknown (accrued interest, in-flight settlement, reporting error) | Medium — limits "certified totals" claims | Reconciliation is *reported*, never forced; per-entity reconciliation status field |
| R4 | ISIN gaps/masking | `XXXXXXXXXXXX` placeholders (148 in 2025-12), deposits without ISIN, ~6% missing in 2012 | Medium — incomplete reverse lookup | Resolution state per position (`ISIN/MASKED/ABSENT`); coverage reported per period |
| R5 | Derivative free-text ambiguity | Subyacente/Instrumento are unnormalized strings | Medium — exposure math unsafe | Store verbatim; classify only by Objetivo; derived parsing flagged DERIVED, versioned |
| R6 | Identity drift (renames, mergers, liquidations) | Register numbers are stable keys; names demonstrably change (denominacion strings vary) | Medium | Entity = (Tipo, NumeroRegistro); names are period-stamped attributes, never keys |
| R7 | Tokens/URLs rot | Tokens are opaque; page is ASP.NET-era | Low-Medium | Manifest records period→sha256 not token→file; re-scrape per run; keep page-parsing resilient (month-title mapping, ES/CA/GL/EU labels per Aletheia) |
| R8 | Silent schema change inside stable XSD | XSD identical 2012–2025 but instances deviate from it already | Medium | Fail-closed unknown-element detection; per-artifact XSD hash check |
| R9 | Scale miscalculation | Estimated ≤4 GB raw total → trivial | Low | Still benchmark before choosing indexes |
| R10 | Project-name collision | openfunds.org is an active registered initiative + CC BY-ND standard | Medium | Rename before any public release (ADR-006) |

## Stop conditions monitored

- If a future period arrives with a new XSD hash → adapter review gate, not silent parse.
- If CNMV tokenizes behind auth or adds ToS click-through → acquisition BLOCKED, escalate.
- If legal review rejects normalized redistribution → product stays "downloader + local pipeline" — still viable OSS.
