# G7 — measured provider contract (G7-R)

Universe measured: **50,931 distinct valid ISINs** across the 8 FONDCART
snapshots (2012-03 … 2025-12). Only `isin_state=valid` enters resolvers;
`masked`/`invalid`/`absent` never leave the local dataset (gate 2-3).

## 1. Coverage measured (full corpus, not sampled)

| Provider | ISINs covered | % | Structural gaps |
|---|---|---|---|
| GLEIF ISIN→LEI (2026-09-18) | 11,651 | 22.9% | XS 0%, LU 0%, CA 0% — NNA-program-bound |
| ESMA FIRDS FULINS (2026-09-12) | 20,230 | 39.7% | current snapshot only — dead ISINs drop out |
| **issuer union** | **22,387** | **44.0%** | ES 27.5%, LU 23.4% still weak |
| OpenFIGI (sample n=3000, seed 42) | 87.0% instrument-level | — | 13% `No identifier found` |
| **3-provider union (sample)** | **88.1% instrument-level** | — | 11.9% unresolved by all |

GLEIF coverage grows monotonically with holding era (19.1% in 2012-03 →
42.5% in 2025-12): the mapping launched 2019 and backfill is partial.
FIRDS coverage also grows (25.1% → 75.1%) — survivor bias is structural:
**a current provider snapshot applied to a historical holding is an
enrichment, not as-of knowledge**. `holding_period` and
`provider_snapshot_date` are always separate fields (gate 11).

## 2. Multiplicity measured

- GLEIF ISIN→LEI: **strictly functional** — 0 of 9,343,190 ISINs with >1 LEI.
- FIRDS: **strictly functional** — 0 of 3,461,932 ISINs with >1 `Issr`
  (one RefData row per venue; Issr identical across venues).
- OpenFIGI: **one-to-many** — 652/2,609 found ISINs (25%) return >1 FIGI;
  521 return ≥10 (venue-level). One-to-many must be preserved (gate 9).

## 3. Agreement measured

9,494 corpus ISINs covered by both GLEIF and FIRDS:

```text
LEI agree      9,114  (96.0%)
LEI CONFLICT     380  ( 4.0%)
```

Conflicts are heterogeneous and semantically meaningful (verified by
resolving both candidate LEIs through `lei-records`):

- **umbrella vs subfund**: `IE00B42Z5J44` → GLEIF "ISHARES V PLC"
  (umbrella) vs FIRDS "iShares MSCI Japan EUR Hedged UCITS ETF" (subfund)
- **fund vs manager**: `ES0180660039` → GLEIF "BBVA CAPITAL PRIVADO FCR"
  vs FIRDS "BBVA ASSET MANAGEMENT SGIIC"
- **genuine issuer disagreement**: `NL0000852531` → Kendrion Finance B.V.
  vs Kendrion N.V.; `US78442P1066` → Navient vs Sallie Mae Bank
- **venue-submitted quality issue**: `US45818QAD16` → Inter-American
  Development Bank vs Bloomberg Trading Facility B.V.

=> `CONFLICT` is a first-class state carrying both candidates + entity
categories; never "pick first" (gate 7).

## 4. GLEIF Level-2 measured (RR-CDF 2026-09-18 + Repex)

Relationship vocabulary (closed, verbatim):

```text
IS_ULTIMATELY_CONSOLIDATED_BY   197,328
IS_FUND-MANAGED_BY              193,004
IS_DIRECTLY_CONSOLIDATED_BY     188,836
IS_SUBFUND_OF                    86,367
IS_INTERNATIONAL_BRANCH_OF        2,239
IS_FEEDER_TO                      1,968
status: ACTIVE 485,471 | INACTIVE 126,721 | NULL 57,550
```

Exception vocabulary (closed): categories
`{DIRECT_, ULTIMATE_}ACCOUNTING_CONSOLIDATION_PARENT` × reasons
`{NON_CONSOLIDATING, NO_KNOWN_PERSON, NATURAL_PERSONS, NO_LEI, NON_PUBLIC}`.

On our 10,974 resolved LEIs:

```text
with RR record        4,536  (41.3%)
with exception        9,656  (88.0%)
overlap (both)        3,218   — legal: RR on one category + exception on other
```

Our corpus's active relationships are fund-dominated:

```text
IS_FUND-MANAGED_BY [ACTIVE]     2,918
IS_SUBFUND_OF [ACTIVE]          2,101
IS_ULTIMATELY_CONSOLIDATED_BY   1,247
IS_DIRECTLY_CONSOLIDATED_BY     1,179
```

=> for Spanish IIC portfolios, `IS_FUND-MANAGED_BY` and `IS_SUBFUND_OF`
are as important as consolidation parents. All preserved verbatim with
status (gate 12); exceptions are first-class states (gate 13).

## 5. Resolution contract

```text
Instrument (per ISIN, per provider snapshot)
  figi[]                        — one-to-many preserved
  composite_figi / share_class_figi / venue
  security_type, security_type2, market_sector, name
  provider, provider_snapshot_date, source_hash

IssuerResolution (per ISIN)
  candidates[] = {lei, provider}        — never collapsed
  resolution_state:
    resolved_single        — exactly one provider, one LEI
    corroborated           — GLEIF + FIRDS agree
    conflict               — GLEIF + FIRDS disagree (both kept)
    gleif_only / firds_only
    not_covered            — in universe, no provider match
    not_in_universe        — outside FIRDS MiFIR scope AND
                             outside GLEIF NNA coverage
  Invalid/masked ISINs never reach this object (upstream gate).

LegalEntity (per LEI, per Golden Copy date)
  legal_name, category (FUND/SUBFUND/GENERAL/BRANCH/…),
  jurisdiction, entity_status, registration_status

EntityRelationship (per child LEI)
  relationship_type — verbatim GLEIF vocabulary
  relationship_status — ACTIVE|INACTIVE|NULL preserved
  exception_category / exception_reason — verbatim, first-class
```

## 6. Forbidden semantics (unchanged from pre-registration)

No `probably_*`, `matched_by_name`, `similar_issuer`, no fuzzy API usage,
no collapsing multiple candidates, no fabricated group when parent is
absent, no renaming `IS_*_CONSOLIDATED_BY` to "group", no treating
OpenFIGI as issuer authority.

## 7. Provider artifacts (pinned, hashed)

```text
gleif/isin-lei-20260918T071512.zip   sha256 f75c6668e8eed5…  32.8 MB
gleif/rr-cdf.zip (20260918)          669,742 records        38 MB
gleif/repex.zip  (20260918)          3,109,795 entities     50 MB
firds/FULINS_*_20260912 (C,D,E,F,H,I,J,O — 22 files)       ~180 MB
openfigi/results.json (sample 3000, seed 42, 2026-09-18)
```

R/S CFI families (OTC swaps/referential) not downloaded — out of the
FONDCART security universe by construction.

## 8. G7-B implemented — GLEIF Golden Copy evidence (2026-09-18)

Three artifacts from the SAME snapshot date, enforced fail-closed on
member-declared dates (`snapshot_date_mismatch` aborts):

```text
lei-cdf-3.1   8,440 MB xml   sha256 076609e9ba872c07…
rr-cdf-2.1      1.1 GB xml   sha256 (artifact 6a026cc7…)
repex-2.1       1.9 GB xml   sha256 (artifact 3ed697e0…)
```

Extraction is filtered — cnmv-iic is not a GLEIF replica:

```text
wanted_lei = distinct candidate_lei (G7-A, all loaded snapshots)

RR-CDF      → records where start_lei ∈ wanted (all types/statuses)
closure     = end_lei of retained records − wanted   (ONE hop, bounded)
LEI-CDF     → records for wanted ∪ closure, role resolved|closure_end_node
Repex       → exceptions for wanted LEIs only
```

Tables (append-only, partitioned `provider=gleif/snapshot=<date>`):

```text
legal_entities           LegalEntityObservation     + evidence_role
relationships            RelationshipObservation   type/status verbatim
relationship_exceptions  RelationshipExceptionObs  category/reason verbatim
```

### Live result (corpus: 2 periods loaded, 4,486 wanted LEIs)

```text
relationships:            2,277   (5 types; no IS_FEEDER_TO on our LEIs)
  IS_FUND-MANAGED_BY            750   (687 ACTIVE / 53 INACTIVE / 10 NULL)
  IS_ULTIMATELY_CONSOLIDATED_BY 718   (494/109/115)
  IS_DIRECTLY_CONSOLIDATED_BY   699   (469/119/111)
  IS_SUBFUND_OF                 109   (105/2/2)
  IS_INTERNATIONAL_BRANCH_OF      1   (1/0/0)
exceptions:               7,899   rows (never NULLs)
  NON_CONSOLIDATING 3,829  NO_KNOWN_PERSON 3,118  NATURAL_PERSONS 609
  NON_PUBLIC 187  NO_LEI 156
legal_entities:           5,121   (4,484 resolved + 637 closure)
  2 wanted LEIs absent from LEI-CDF 2026-09-18 (verified: ISSUED per
  API but not in the concatenated file) — honest gap, not fabricated
evidence_fingerprint:     d4e9a02744c526a6bf4539d8eec6da716f3fc595e5a4b6a85628ffeffe642900
```

Verified end-to-end: `GVCGAESCO EMERGENTFOND, FI` (FUND)
`--IS_FUND-MANAGED_BY/ACTIVE-->` gestora pulled as `closure_end_node`;
`BANCO SANTANDER S.A.` has no RR rows but two `NON_CONSOLIDATING`
exception rows — "no RR" is never "no parent", the distinction is
data. G7-A fingerprint and all G1–G6 fingerprints byte-identical.

### Gates — all 20 hold

1–3 same-date/pinned/filtered ✓  4 append-only ✓  5–7 verbatim types,
never `parent`, fund/subfund/feeder distinct ✓  8 periods preserved
(JSON array, period_type verbatim) ✓  9–10 exceptions as rows, absence
not asserted ✓  11–13 start/end kept, end nodes get Level-1, one-hop
bound ✓  14–15 zero fuzzy/group inference ✓  16–17 prior fingerprints
intact ✓  18 idempotent ✓  19 new snapshot = new partition ✓  20
magnitudes consistent with G7-R (subset of 2 loaded periods).
