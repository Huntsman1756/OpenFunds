# G1 adjudication — FONDCART holdings ledger vertical slice

**Verdict: PASS** — tagged `g1-holdings-pass` at commit `55c982a`.

## Gate-by-gate evidence

| # | Gate | Result | Evidence |
|---|------|--------|----------|
| 1 | Acquisition productionized | PASS | Origin allowlist, bounded redirects (off-origin rejected), ZIP magic, byte/entry/ratio caps, traversal rejection, DOCTYPE/ENTITY rejected, atomic writes, SHA-256 ledger (`artifacts.jsonl`), no raw bytes in repo |
| 2 | FONDCART only | PASS | Single adapter `cnmv_iic.adapters.fondcart`; no other family parsed |
| 3 | Minimal canonical model | PASS | `FundIdentity`, `PortfolioSnapshot`, `Position` (security/cash), `SourceArtifact`, `QualityObservation`, `Provenance` |
| 4 | Decimal semantics | PASS | `Decimal` end-to-end; `ValorMercado` verified always scale-2 (all sampled periods) → `decimal128(38,2)`; `derived_weight` separate, quantized `decimal128(38,18)` ROUND_HALF_EVEN |
| 5 | Fail-closed identity | PASS | CNMV keys `FI:9:0`; ISO 6166 checkdigit verified on real ISINs; `masked`/`absent`/`invalid` preserved verbatim |
| 6 | Deterministic Parquet | PASS | Canonical sort `(entity_type, numero_registro, compartimento, seq)`; `dataset_fingerprint` = SHA-256 over canonical row serialization, parquet-metadata independent |
| 7 | Quality metadata | PASS | Per-entity reconciliation vs FONDPATRIMDISVAR: abs/rel diff, state, tolerance 0.1%; divergent kept (255 in 2025-12) |
| 8 | CLI | PASS | `update`, `holdings`, `funds-holding`, `dataset-info`, `source`; `--json`, `--data-dir`, `CNMV_IIC_DATA_DIR` |
| 9 | Row-level provenance | PASS | artifact id + artifact/member SHA-256 + `FondCart/Entidad[i]/Compartimento[j]/InversionesFinancieras[k]` + parser name/version on every position |
| 10 | Historical extremes | PASS | Live `update`: 2012-03 → 59,748 positions; 2025-12 → 103,130 positions; identical fingerprints across independent runs |
| 11 | Idempotency | PASS | Identical bytes → `artifact_new_version:false`, `exported:false`; changed bytes → new version with `supersedes` |
| 12 | Public packaging | PASS | pyproject (3.11+), ruff+mypy clean, 27 tests, CI (3 OS × 3 Python), LICENSE, SECURITY, CONTRIBUTING, NOTICE |

## Live verification transcript (condensed)

```
update --period 2025-12 → artifact 5f05feda…(byte-identical to G0 research zip)
                        → 103,130 positions, fp f53e607d7c7b62f3…
update --period 2012-03 → artifact c878a610…
                        → 59,748 positions, fp 5359949a35b5847c…
update --period 2025-12 (repeat) → artifact_new_version:false, exported:false
update --period 2025-03 → clean error: "no FONDCART member"
                         (semiannual cadence ≥2023 surfaces as data, not bug)
holdings FI:9:0        → 111 positions, full provenance per row
funds-holding ES0000012F76 → 22 funds ("reported portfolio positions")
```

## Deviations discovered during G1 (registered)

- `FONDCART/…/Divisa` absent — 17 positions, **2012-03 only**; verified
  absent in all other sampled periods (2014→2025). Registered as
  `MISSING_REQUIRED_ELEMENT`; adapter allows absence → `divisa=None`.
- 2 official ISINs failing check digit in 2025-12 (`US09857L1080`,
  `US92826C8390`) — preserved verbatim as `isin_state=invalid`.
  Independently verified: genuine source data errors, not false positives.

## Known limits carried to G2

- `holdings` requires CNMV key (`FI:9:0`); share-class ISIN resolution
  needs FONDREGISTRO → **G2 scope**.
- No NAV/fees/derivatives yet (G3–G5).
- `funds-holding` output is key-level only until identity layer lands.
