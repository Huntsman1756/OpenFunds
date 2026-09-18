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

## 9. G7-C implemented — ESMA FIRDS FULINS evidence (2026-09-12)

Complete pinned snapshot: 16 ZIPs, all parts of asset letters
`C D E F H I J O` (`NNofMM` enforced per letter, fail-closed);
R/S excluded by scope decision — 0 covered corpus ISINs outside
C/D/E. Every part's filename date must agree with its in-file
`RptgPrd/Dt` (`snapshot_date_mismatch`/disagreement aborts). XML
declares `auth.017.001.02` (ISO 20022 envelope head.003.001.01);
schema text observed `auth.017.001.02_ESMAUG_FULINS_1.1.0.xsd` —
compatible with ESMA's published FIRDS schema v1.2.1 contract for
the fields consumed. See `firds-lifecycle.md` for FULINS/DLTINS
lifecycle.

Grain measured (5,329,746 RefData records across the 16 parts):

```text
record identity = ISIN x TradgVnRltdAttrbts/Id (venue MIC)
Issr present and valid in 100% of records (0 missing/invalid)
unique Issr per ISIN: always 1 in this snapshot — FIRDS is
functionally 1:1 on issuer, but the model allows N
```

Model — a FIRDS record is NOT an issuer candidate:

```text
resolution_candidate_evidence (new child table)
    observation_id, candidate_lei, evidence_index
    provider_record_locator  "<member>#RefData=<ordinal>"
    source_file, trading_venue, relevant_venue
    first_trade_date, termination_date, raw_json
```

```text
ISIN x venue records ──► 1 unique candidate LEI ──► N evidence rows
different Issr LEIs  ──► multiple_candidates
records but no usable Issr ──► no_candidate (new ResolutionState)
absent from snapshot ──► no_match  (never deduced not_applicable)
```

`relationship_semantics = firds_field5_issuer_or_venue_operator` —
measured to carry the issuer LEI for asset C (verified: subfund-level
names, e.g. individual ETF ICAVs), but named conservatively per ESMA's
own field definition rather than re-labelled `isin_issuer_to_lei`.

### Live result (corpus: 2 periods loaded, 25,660 valid ISINs)

```text
observations:    25,660   matched 14,493 (56.5%)   no_match 11,167
                          multiple_candidates 0   no_candidate 0
candidates:      14,493 unique LEIs
evidence rows:   248,342  (920 ISINs 1 row; rest multi-venue,
                           up to 54 venues measured)
                 C 34,531 / D 132,822 / E 80,989
                 FrstTradDt 100%, TermntnDt 36% (89,748 terminated
                 venue rows preserved as evidence)
fingerprint:     da1806feb763713ccbef5cab8819f09dfa0431e88a8f3efb12879cc801801e5b
```

Coverage by period — the temporal bias is reproduced, not smoothed:

```text
2012-03 holdings:  2,320/9,230  (25.1%)
2025-12 holdings: 13,385/16,642 (80.4%)
```

Corroboration matrix GLEIF x FIRDS (per ISIN):

```text
GLEIF match / FIRDS match      7,299   same LEI 7,028 · DIFFERENT 271
GLEIF no_match / FIRDS match   7,194   (structural XS/LU gap filled)
GLEIF match / FIRDS no_match   1,045
both no_match                 10,122
combined coverage            15,538/25,660 (60.6%)
```

The 271 divergences reproduce the measured C0 subset count exactly.
Verified example: `IE0006HMLPV6` — GLEIF maps to the umbrella
`JPMORGAN ETFS (IRELAND) ICAV` while FIRDS `Issr` is the
subfund-level `549300FZ7YUTJ13G1V05`, backed by venue rows
BEUP/BTFE/CEUD/CEUO. A granularity difference, not an error —
both candidates preserved, never auto-resolved (gate 25).

Bug found and fixed during live validation: the 16 parts originally
shared one `source_family`, so artifact dedupe collided on
`(period, provider, family)` — every run re-registered all parts and
the fingerprint changed. Fixed with per-part families
(`firds-fulins-<letter><part>`); re-ingest is now a true no-op
(`artifacts_new:0, exported:false`, fingerprint byte-identical) and
`test_idempotent_reingest` covers the multi-file case.

### Gates — all 25 hold

1–2 snapshot complete, all parts sha256 ✓  3 schema identified
(auth.017.001.02 / FULINS 1.1.0) ✓  4–6 valid CNMV ISINs only, exact
join, zero fuzzy ✓  7 candidate_count = unique LEIs ✓  8–9 same-LEI
venue rows preserved as evidence, not counted as candidates ✓
10 different LEIs = multiple_candidates ✓  11 no arbitrary selection
✓  12 absence = no_match ✓  13 Issr semantics measured by asset type
(subfund-level for C) ✓  14 missing/invalid Issr = no_candidate
(0 observed) ✓  15 snapshot date on every observation ✓  16
current_enrichment_of_historical_security ✓  17 artifact + member +
record locator per evidence row ✓  18 idempotent/deterministic ✓
19 new snapshot = new partition ✓  20–21 GLEIF + G7-B untouched
(fingerprints 3258f662…/d4e9a027… byte-identical) ✓  22 G1–G6
fingerprints intact ✓  23 coverage consistent with G7-R (only C/D/E
letters carry corpus ISINs) ✓  24 all 271 subset conflicts reproduced
✓  25 disagreements never auto-resolved ✓

No canonical issuer, no conflict winner, no umbrella/subfund
adjudication — that remains G7-E work.
