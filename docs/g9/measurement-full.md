# G9-A2 measurement — full FONDREGISTRO series

Executed: 2026-09-18 after `cnmv-iic backfill --from 2012-01 --to 2026-05`.
Scripts: `.research/g9a2_inventory.py`, `.research/g9a_measure_full.py`
→ evidence `.research/g9a2_inventory.json`, `g9a2_backfill.json`,
`g9a_measurement_full.json` (local, gitignored).

Measurement fingerprint: `1de46aaf15ee31c09bb57589b7f85d98fada517e9115b41216f09317118b0fe4`
(identical across two runs; second backfill run = 0 network requests).

## 1. Source inventory

```text
expected monthly periods (official index):   173   (2012-01 .. 2026-05)
years enumerated without failure:             15
already local before backfill:                 4
downloaded this run:                         169
failed:                                        0
periods without FONDREGISTRO member:           0
```

`missing_locally` and `source_missing` are both empty — the CNMV
monthly series is **complete** for the whole span, not sampled.

## 2. Registry series

```text
observed months:            173 / 173
missing expected months:      0
adjacent observed pairs:    172
contiguous pairs:           172  (all of them)
non-contiguous pairs:         0
```

## 3. Fund-key census

```text
distinct fund_keys ever observed:      3,961
left-censored (present at 2012-01):    2,336
right-censored (present at 2026-05):   1,438
present in ALL 173 months:               572
```

Conservation (exact, not approximate):

```text
2,336 left-censored + 1,625 appeared  = 3,961 distinct keys
1,438 right-censored + 2,523 disappeared = 3,961
```

## 4. Candidates (contiguous pairs only)

```text
FUND_APPEARED        1,625
FUND_DISAPPEARED     2,523
```

### By year

| year | appeared | disappeared | | year | appeared | disappeared |
|-----:|---------:|------------:|-|-----:|---------:|------------:|
| 2012 |      106 |         237 | | 2020 |       71 |         151 |
| 2013 |      147 |         309 | | 2021 |       76 |         139 |
| 2014 |      150 |         244 | | 2022 |      143 |         111 |
| 2015 |      100 |         289 | | 2023 |      108 |          96 |
| 2016 |      167 |         179 | | 2024 |       98 |         102 |
| 2017 |      123 |         195 | | 2025 |       80 |         134 |
| 2018 |      101 |         160 | | 2026*|       57 |          57 |
| 2019 |       98 |         120 | |      |          |             |

*2026 is a partial year (through 2026-05).

Disappearance peaks cluster at reporting-period boundaries:
`2013-09` (56), `2015-07` (50), `2012-07`/`2013-07` (46 each),
`2015-12` (41). Appearance peak: `2016-07` (33). July/September
concentration is consistent with merger/liquidation waves settling at
semester closes — an observation for G9-B sampling, not a claim.

### By entity type

```text
FI: appeared 1,625 / disappeared 2,523
FHF / SICAV / SHF: not present in FONDREGISTRO at all (see §6)
```

Compartment deltas measured separately throughout (not mixed into
fund-level denominators).

## 5. Temporal pathologies (observed, not adjudicated)

```text
reappeared same fund_key after absence:      0
one-month absences:                          0
multi-month absences:                        0
single-observation funds:                   44
short-lived (<= 6 observed months):        235
```

**The strongest structural finding**: across 173 months, no `fund_key`
ever returns after disappearing. `fund_key` behaves as a true
one-shot vehicle identity — disappearance is final at this grain.
G9-B can therefore treat every FUND_DISAPPEARED as a terminal
observational event (not a gap artifact), and needs no
"reappearance reconciliation" logic.

## 6. Entity-universe finding

FONDREGISTRO contains **only FI** across all 173 months — this is a
corpus fact, not a filter. The same monthly artifacts also carry the
SICAV families (`SOCREGISTRO`, `SOCCART`, `SOCTRIM`, `SOCDERI`,
`SOCPATRIMDISVAR`), which are stored raw but never parsed by
`update_period`. Extending lifecycle coverage to SICAV/SHF is a
parsing extension over already-acquired artifacts — no new downloads
needed. Deferred as an explicit G9 extension decision.

## 7. Backfill mechanics

New: `ingest.backfill_periods` + `cnmv-iic backfill --from --to`.

- `update_period` refactored: network part (`list_months` +
  `download_zip` + `store.put`) split from `export_artifact`
  (parse + write, no network).
- Per period exactly one of: `already_complete` (manifest +
  artifact present, zero network), `exported_from_local` (artifact
  stored, export incomplete — no download), `downloaded`.
- `list_months` memoized per year (`_IndexCachingClient`).
- `request_delay` honored between downloads.
- Per-period `CnmvIicError` isolated into `failed` entries — 0 occurred.
- Second run: 173 × `already_complete`, 0 network requests.

Tests: `tests/test_backfill.py` (5) — download-only-missing,
failure isolation + retry-only-failed, export-from-local without
network, index caching, month range.

## 8. G1–G8 regression

```text
fingerprints changed: none
  2012-03 dataset 5359949a / registry fa5cf9cd / daily e161aa3b — intact
  2025-12 dataset f53e607d / daily f9f8eebc                    — intact
tests: 271 passed (266 + 5 backfill)
ruff:  clean
mypy:  clean
```

## 9. Verdict vs the G9-A2 gate

| gate | result |
|------|--------|
| exact official month inventory known | **yes — 173, zero enum failures** |
| all available months acquired or explicit failure reason | **yes — 169 downloaded, 0 failed** |
| contiguous pairs correctly identified | **yes — 172/172** |
| candidates reproducible | **yes — fingerprint stable ×2** |
| gaps distinguished from events | **yes — zero gaps exist; all pairs contiguous** |
| deterministic measurement fingerprint | **yes — `1de46aaf…`** |

**G9-A2 gate: PASS.** The observational base for G9-B now exists:
4,148 real candidates (1,625 appeared / 2,523 disappeared) over a
complete 14.4-year monthly series.

## 10. Implications for G9-B design (not decided here)

- The disappearance workload (~2.5k) is concentrated in 2012–2017
  (~64%) — a chronological bulletin spine would cover most candidates;
  per-fund hechos-relevantes lookups may suffice for the tail.
- Zero reappearances means no temporal-overlap edge cases — the
  candidate model stays simple.
- 44 single-observation + 235 short-lived funds are a distinct
  stratum for the gold corpus (registered-but-brief vehicles).
- July/September disappearance clustering gives the stratified sample
  natural seasonal strata.
