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

## 10. G7-D implemented — OpenFIGI instrument evidence (campaign 2026-09-18)

Instrument domain, NOT issuer resolution: `security -> instrument
symbology` evidence in separate `instrument_observations` /
`instrument_candidates` tables — never `resolution_candidate` with a
FIGI pretending to be an LEI.

OpenFIGI is a LIVE API: no dated snapshot artifact exists, so the
partition key is `retrieval=<campaign>` (an API retrieval date, never
presented as a provider-issued snapshot) and
`temporal_semantics = current_api_enrichment_of_historical_security`.

Acquisition (G7-D1, `cnmv_iic.openfigi_client`):

```text
valid ISINs sorted -> deterministic 10-job batches (anonymous tier)
batch_id = sha256(endpoint + ordered jobs)
each POST stored immutably: provider_raw/openfigi/<campaign>/batches/
    <batch_id>.zip  {request.json, response.json, meta.json}
    meta: request/response sha256, ratelimit-* headers, retrieved_at
resume = existing batch artifact -> skip (no re-request, no overwrite)
len(response) == len(request) enforced per batch (positional order)
429 -> ratelimit-reset/Retry-After wait; 5xx -> bounded exp backoff
OPENFIGI_API_KEY optional env only (throughput, never semantics/files)
```

Per-job payload -> state (no result row silently discarded):

```text
{"data": [1 row]}    -> matched_single
{"data": [N rows]}   -> matched_multi   (venue multiplicity is normal)
{"warning": ...}     -> no_match
{"error": ...}       -> provider_error
other/absent job     -> invalid_response / provider_error
```

Measured FIGI hierarchy (corpus probe, see live numbers below):

```text
figi            venue-level        N per ISIN is normal
compositeFIGI   per-market         >1 non-null per ISIN is normal
shareClassFIGI  instrument family  never >1 NON-NULL per ISIN measured;
                                   some venue rows omit it (null-vs-
                                   value mix = provider quirk, not a
                                   second family)
```

All three kept verbatim — multi-venue multiplicity is evidence shape,
not ambiguity; coherence is derivable from shareClassFIGI, never
asserted by collapsing fields.

### Live result (corpus: 25,660 valid ISINs, campaign 2026-09-18)

```text
batches:         2,566 (10 jobs each, anonymous tier) — 0 failed,
                 0 retried batches lost; ~106 min paced at 25 req/min
observations:    25,660   matched_single 16,004 (62.4%)
                          matched_multi   6,791 (26.5%)
                          no_match        2,865 (11.2%)
                          provider_error / invalid_response: 0
candidates:      545,976 result rows preserved verbatim
                 max 296 venue FIGIs for one ISIN (DE0007100000)
fingerprint:     de3568e70a0a44adcf68a02eeebb0a4f1e4ce8b45ebc791069b3993900fccaaa
```

FIGI hierarchy measured on the full corpus (6,791 multi-result ISINs):

```text
one non-null shareClassFIGI:        6,757  (99.5% of multi)
all-null shareClassFIGI:               33
>1 non-null shareClassFIGI:             1  JE00B8DFY052 (WisdomTree
                                          Physical Gold EUR Hdg, 47
                                          rows, 2 genuine families —
                                          preserved, not adjudicated)
>1 non-null compositeFIGI:          6,623  (per-market aggregation —
                                          normal, not ambiguity)
null-vs-value shareClassFIGI mix:   3,160  (provider quirk: some venue
                                          rows omit the field)
>1 securityType2:                        15
>1 marketSector:                          2
>1 name:                              1,187 (cosmetic venue variance)
```

Cross-provider matrix (any issuer LEI evidence x OpenFIGI):

```text
issuer yes / openfigi yes   15,128
issuer no  / openfigi yes    7,667   instrument rescued where no
                                     LEI evidence exists (XS/LU gap)
issuer yes / openfigi no       410
neither                      2,455   the true dark residual (9.6%)
any evidence                23,205/25,660 (90.4%)
```

Coverage by ISIN prefix — OpenFIGI fills exactly GLEIF's structural
gap; domestic ES is its weak side:

```text
XS 96.7%  LU 87.2%  DE 96.6%  IT 95.5%  JP 96.6%  FR 91.6%
IE 92.5%  US 92.2%  CA 90.0%  BE 94.8%  GB 77.6%  ES 61.4%
```

By holding period: 2012-03 79.7% · 2025-12 94.0% — still
current-enrichment, never as-of-holding identity.

Bug fixed during build (pre-live): transport-level failures
(timeout/conn reset) were treated as campaign-fatal; they are now
retriable per batch like 5xx, bounded — covered by two tests.

### Gates — all 25 hold

1–2 valid ISINs only, exact ID_ISIN ✓  3–5 no search/filter/name
fallback ✓  6 pyopenfigi reviewed, REFERENCE_ONLY (oss-review) ✓
7 deterministic batches ✓  8 raw request/response + sha256 retained
✓  9 resume skips completed (verified: rerun re-requested nothing) ✓
10–12 ratelimit-* headers honoured, 429 reset wait, bounded 5xx
backoff ✓  13 positional cardinality validated per batch (0
mismatches in 2,566) ✓  14 0/1/N preserved ✓  15 multi-venue not
auto-ambiguity (matched_multi, coherence derivable) ✓  16 three FIGI
levels distinct ✓  17 no issuer inference from OpenFIGI ✓  18
retrieved_at vs snapshot distinguished (retrieval= partition,
provider_snapshot_date: null) ✓  19 re-export byte-identical
fingerprint ✓  20 new campaign = new partition ✓  21 GLEIF/FIRDS
untouched ✓  22 G1–G7-C fingerprints byte-identical (3258f662… /
d4e9a027… / da1806fe…) ✓  23 full corpus measured (25,660, not
extrapolated) ✓  24 XS/LU/ES/US stratification reported above ✓
25 zero provider responses discarded (545,976 rows = every job's
every result; the 2,865 warnings are no_match observations) ✓

G7 evidence stack is now complete: CNMV universe -> GLEIF issuer
candidates + FIRDS issuer/operator candidates + GLEIF entity/
relationship context + OpenFIGI instrument symbology. Next: G7-E
adjudication over this evidence — never inside a provider adapter.

## 11. G7-E — adjudication layer (derived, never provider evidence)

Adjudication is a DERIVED layer: it reads G7-A..D partitions plus the
immutable raw artifacts already in the ArtifactStore, writes its own
tables, and never modifies provider evidence. There is NO single
provider snapshot date — the input is pinned as an EvidenceBundle:

```text
gleif_anna_isin_lei@2026-09-18#3258f662…
gleif_golden@2026-09-18#d4e9a027…   (lei-cdf + rr-cdf + repex)
esma_firds@2026-09-12#da1806fe…
openfigi@2026-09-18#de3568e7…       (retrieval campaign, not a snapshot)

bundle_fingerprint = sha256(canonical ordered evidence ids)
                   = dfe244f54ad119d445ca216a443fdfd1ce6531486a5c39c2814a55ddbfd59def
```

A resolution is identified by (adjudication_version, bundle_fingerprint).
New evidence or new rules → new partition, never overwrite.
``adjudicated_at`` is written to rows but excluded from the fingerprint.

### Rules — deliberately boring

```text
gleif=A firds=A            -> corroborated,   resolved_lei=A
gleif=A firds=none         -> gleif_only,     resolved_lei=A
gleif=none firds=B         -> firds_only,     resolved_lei=B
gleif=A firds=B, A!=B      -> conflict,       resolved_lei=NULL
any provider >1 candidate  -> multiple_candidates, resolved_lei=NULL
neither produced           -> no_authoritative_match, resolved_lei=NULL
```

No provider priority, no name/ticker/country/CFI tie-break, OpenFIGI
never enters issuer adjudication (no ``openfigi_only`` state exists).

### Live result (bundle dfe244f5…, version 1)

```text
corroborated             7,028   (27.4%)
firds_only               7,194   (28.0%)   — fills the XS/LU GLEIF gap
gleif_only               1,045   ( 4.1%)
conflict                   271   ( 1.1%)
multiple_candidates          0
no_authoritative_match  10,122   (39.4%)
                    = 25,660  conservation holds
resolved (corr + single-source): 15,267 (59.5%)

issuer evidence strength for G8:
  corroborated  7,028   two independent official sources agree
  single-source 8,239   one source only — weaker, filterable
```

By period: 2012-03 resolved 2,710/9,230 (29%) · 2025-12 resolved
13,787/~16,022 (86%). By prefix — the residual dark zone is domestic:
ES 37% resolved (2,011 no_auth), LU 27% (2,202), XS 63%, US 80%,
FR 73%, DE 67%.

### Conflict context — the payoff of the bounded raw pass

G7-B extracted RR records only where start LEI was a GLEIF candidate,
so a FIRDS-only LEI ``B`` had no loaded ``B -> A`` record even when
RR-CDF contains it (measured pre-G7-E: only 25/271 pairs had a loaded
direct relation). G7-E runs a bounded second pass over the SAME stored
RR-CDF/LEI-CDF artifacts with wanted = conflict LEIs — derived
extraction over existing evidence, not a new provider, not a G7-B
rewrite:

```text
271 conflicts -> context kinds:
  direct_gleif_relation     219   (was 25 without the raw pass)
  entity_metadata_difference 22
  no_direct_gleif_relation   30
  unknown                     0

relationship types (all verbatim, direction + status preserved):
  IS_SUBFUND_OF                 185   <- umbrella vs subfund granularity
  IS_ULTIMATELY_CONSOLIDATED_BY  51
  IS_DIRECTLY_CONSOLIDATED_BY    42
  IS_FUND-MANAGED_BY              9
status: ACTIVE 279 · INACTIVE 2 · NULL 6
source: raw_artifact 245 · evidence_table 42
```

Interpretation: most "conflicts" are not contradictions but two
different grains — GLEIF/ANNA maps to the umbrella, FIRDS field 5 to
the subfund (or vice versa for consolidation). 183/271 conflicts are
IE-prefixed (Irish ICAV structures). Example, verified end-to-end:
``ES0305668016`` — GLEIF candidate "PENSIUM ESG I, FONDO DE
TITULIZACION", FIRDS candidate "PENSIUM ESG I FT - SEGUNDO
COMPARTIMENTO"; context shows the latter --IS_SUBFUND_OF--> the
former, ACTIVE since 2022-06-29, with record locators into both raw
artifacts. ``resolved_lei`` stays NULL: classification is information,
never adjudication.

### instrument_family_resolution

Same bundle, same version, separate domain — shareClassFIGI
convergence decided on the DISTINCT NON-NULL value set (a null-vs-
value mix is a provider quirk, not a second family):

```text
single_share_class_figi    9,571
no_share_class_figi       13,223   (matched rows, sc field absent)
no_openfigi_match          2,865
multiple_share_class_figi      1   (JE00B8DFY052 — genuinely 2, kept)
                          25,660
```

### Gates — all 20 hold

1 derived layer, G7-A..D untouched (fingerprints verified after run) ✓
2 same LEI -> corroborated (7,028 = G7-C cross-matrix count exactly) ✓
3–4 single-provider states ✓  5 different LEIs -> always conflict
(271 = measured divergences exactly) ✓  6 no provider priority ✓
7 no fuzzy/name/ticker matching anywhere in the pipeline ✓
8 OpenFIGI absent from issuer adjudication (test: ofi-only evidence
yields 100% no_authoritative_match) ✓  9 multiple_candidates never
collapsed (test) ✓  10 conflict classification never changes
resolved_lei=NULL (test + live: all 271 NULL) ✓  11 RR context keeps
type/direction/status verbatim ✓  12 reporting exceptions never used
as candidates ✓  13 bundle complete + fingerprinted (4 evidence ids) ✓
14 provider dates separate (3 snapshots + 1 retrieval) ✓
15 adjudication_version explicit ✓  16 same bundle+version -> exported:
false, identical fingerprint (verified) ✓  17 new evidence -> new
bundle partition, old preserved (test) ✓  18 G1–G7-D fingerprints
unchanged (verified post-run) ✓  19 the 271 divergences remain
conflicts — none resolved ✓  20 conservation 25,660 ✓

CLI: ``adjudicate`` · ``security <isin>`` · ``resolution <isin>`` ·
``resolution-coverage`` · ``resolution-conflicts``.

G7 is now functionally complete: every corpus ISIN carries a
deterministic, provenance-pinned issuer verdict (or an explicit
non-verdict) plus a separate instrument-family verdict. Next: G7-F
hardening, then G8 exposure engine — which must filter by resolution
strength (corroborated vs single-source) and never aggregate
conflicts silently.
