# G7-R — OSS / provider reuse review

Objective: resolve the issuer/legal-entity identity and instrument metadata of
FONDCART positions **without building a proprietary security master**. Three
open public infrastructures cover the space; `cnmv-iic` only builds the
evidence-preserving adjudication layer between them.

## Provider candidates

| Provider | Surface used | License | Format | Verdict |
|---|---|---|---|---|
| GLEIF/ANNA ISIN→LEI relationship files | ISIN → LEI | CC0 | Daily full-snapshot CSV in ZIP (~33 MB zip / 318 MB csv) | ADOPT — primary issuer evidence |
| GLEIF LEI-CDF 3.1 concatenated file | legal entity Level-1 record | CC0 | XML ~513 MB zip | ADOPT — entity metadata (G7-B) |
| GLEIF RR-CDF 2.1 concatenated file | Level-2 relationships | CC0 | XML ~38 MB zip / 1.1 GB xml | ADOPT — official relationship types |
| GLEIF Reporting Exceptions 2.1 | declared absence of parent data | CC0 | XML ~50 MB zip / 1.9 GB xml | ADOPT — first-class states |
| ESMA FIRDS FULINS (weekly, per CFI letter) | ISIN → issuer LEI + CFI + names | ESMA public register | ZIP+XML ~180 MB/snapshot (C,D,E,F,H,I,J,O) | ADOPT — corroboration/fallback |
| OpenFIGI `/v3/mapping` | ISIN → FIGI + instrument metadata | FIGI dedicated to public domain; API free | JSON API, 10 jobs/req unauthenticated | ADOPT — instrument enrichment only |

## Library candidates

| Library | Lang | License | Maintenance | Verdict |
|---|---|---|---|---|
| `pyopenfigi` (tlouarn) | Python | MIT | PyPI 0.1.0 (2023-04); GitHub active 2026-05 | REFERENCE_ONLY — thin POST wrapper; our jobs-batching need is ~30 LOC and must handle pacing/checkpointing anyway |
| `esma_data_py` (ESMA official) | Python | EUPL-1.2 | active (pushed 2025-11); not on PyPI | REFERENCE_ONLY — file-list Solr query is 15 LOC; avoids a git dependency |
| `pyfirds` (bunburya) | Python | MIT | GitHub only, 0 stars | REFERENCE_ONLY — full FIRDS dataclass parsing is more than needed; we extract 4 fields |
| `gleifr` (R) | R | MIT | CRAN mirror | REFERENCE_ONLY — confirms the isin-lei file is a full snapshot, not a delta |

## What we verified about each provider (measured, not assumed)

### GLEIF ISIN→LEI (`isin-lei-20260918T071512.zip`, sha256 f75c6668…)

- 9,343,190 ISIN→LEI rows; 98,941 distinct LEIs.
- **Strictly functional**: 0 ISINs map to >1 LEI.
- Coverage is NNA-program-bound: only ISINs declared through participating
  national numbering agencies appear. XS (ICSD-issued) = 0%. LU = 0%.
  Confirmed against the live API: 8/8 uncovered samples → 404, so the bulk
  file coverage is the true coverage, not a file artifact.
- Daily files are **full snapshots** (verified: latest file alone contains
  all rows), enabling reproducible `provider_snapshot_date` + sha256.

### ESMA FIRDS FULINS (`2026-09-12`, CFI families C,D,E,F,H,I,J,O)

- 3,461,932 distinct ISINs; **0 ISINs with >1 issuer LEI**.
- One `RefData` record per (ISIN, trading venue) — same ISIN repeats with
  identical `Issr`; multiplicity is venue-level, not issuer-level.
- `Issr` is a sibling of `FinInstrmGnlAttrbts` inside `RefData`;
  `ClssfctnTp` = CFI code; `FullNm`/`ShrtNm` available.
- Covers what GLEIF misses structurally (XS Eurobonds, IE/LU UCITS shares)
  because its universe is "instruments reported to EU venues", not
  NNA-declared ISINs.
- Files listed via Solr: `registers.esma.europa.eu/solr/
  esma_registers_firds_files` with `file_name`, `download_link`, `checksum`.
- FULINS is a **current snapshot** — terminated instruments drop out;
  historical resolution of 2012-era ISINs is systematically survivor-biased
  (must be declared, not hidden).

### GLEIF RR-CDF (`20260918`, 669,742 records)

Measured relationship vocabulary (closed set):

```text
IS_ULTIMATELY_CONSOLIDATED_BY   197,328
IS_FUND-MANAGED_BY              193,004
IS_DIRECTLY_CONSOLIDATED_BY     188,836
IS_SUBFUND_OF                    86,367
IS_INTERNATIONAL_BRANCH_OF        2,239
IS_FEEDER_TO                      1,968
```

Statuses: `ACTIVE` 485,471 / `INACTIVE` 126,721 / `NULL` 57,550.
The vocabulary is richer than "accounting parent": fund-management,
umbrella/subfund and feeder relationships are first-class — directly usable
for LU/IE fund-share resolution without inventing semantics.

### GLEIF Reporting Exceptions (`20260918`, 3,109,795 entities)

Measured closed vocabulary — categories × reasons:

```text
{NON_CONSOLIDATING, NO_KNOWN_PERSON, NATURAL_PERSONS, NO_LEI, NON_PUBLIC}
  x {DIRECT_ACCOUNTING_CONSOLIDATION_PARENT,
     ULTIMATE_ACCOUNTING_CONSOLIDATION_PARENT}
```

These are *officially declared* reasons a parent cannot be reported —
first-class resolution states, never "missing data" to paper over.

### OpenFIGI `/v3/mapping`

- ISIN resolves to **multiple FIGIs**: one per venue + composite +
  share-class FIGI (verified live: Santander, Apple → venue list;
  XS bond → single FIGI; LU fund → found as `Open-End Fund`).
- Some identifiers genuinely absent: `ES0505130841` (Spanish T-bill) →
  `{"warning": "No identifier found."}` — `not_covered` is a real outcome.
- No API key needed for measurement (10 jobs/request, ~25 req/min);
  a key raises both limits but adds an operational secret for no
  contract-level benefit.

## Deliberately excluded

- **No issuer-name fuzzy matching** anywhere in the chain — the GLEIF API's
  `fuzzycompletions`/`fulltext` endpoints exist but are explicitly not used:
  resolution is exact-identifier only.
- **OpenFIGI never decides issuer identity**: FIGI is instrument symbology;
  `securityDescription`/ticker are metadata, not legal-entity evidence.
- **No renaming of GLEIF semantics**: `IS_*_CONSOLIDATED_BY` is the
  accounting consolidating parent, not "corporate group"; fund relationships
  keep their official names.

See `contract.md` for the measured coverage numbers this review produced.
