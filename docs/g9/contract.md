# G9 preregistration — fund lifecycle evidence & lineage

Date: 2026-09-18
Base HEAD: `8108484bc23f78c7c7c2cb706a09c3e2a290cb04`
Status: **PREREGISTERED BEFORE INFERENTIAL LIFECYCLE CODE**.

## 1. Boundary

G0–G8 are immutable evidence already acquired. G9 begins exactly at the existing boundary:

```text
WHAT changed
    ↓
WHY / WHAT OFFICIAL LEGAL EVENT explains it
```

Existing `fund-events` keeps its current mechanical semantics. G9 must not silently reinterpret an `IdentityEvent` as a legal lifecycle event.

## 2. Mandatory four-layer separation

```text
OBSERVATIONAL CHANGE
        ↓
LIFECYCLE CANDIDATE
        ↓
OFFICIAL SOURCE ASSERTION(S)
        ↓
ADJUDICATED LIFECYCLE EVENT
```

Invariants:

- `FUND_DISAPPEARED != LIQUIDATED`.
- `NAME_CHANGED != RENAMED` unless official evidence supports that event semantic.
- merger authorization != merger execution.
- absence of successor evidence != no successor.
- source absence != legal extinction.
- CNMV exit != economic-lineage death.
- legal-entity identity != fund lineage.
- ISIN != eternal fund identity.
- `fund_key` remains canonical OpenFunds identity.
- no fuzzy successor matching.
- no lifecycle event without provenance.
- no lineage edge without evidence.
- no exact `effective_at` inferred from a monthly snapshot boundary.
- no `UNKNOWN` silently excluded.
- no current issuer-resolution evidence used to prove historical fund lifecycle.

## 3. G9-A — observational whole-fund candidates

### Grain

`fund_key × adjacent_observed_registry_snapshots`.

Candidate types:

```text
FUND_APPEARED
FUND_DISAPPEARED
```

`COMPARTMENT_APPEARED` / `COMPARTMENT_DISAPPEARED` may be emitted in a **separate compartment-grain table** after fund-level measurement. They must never be mixed into fund-level denominators.

### Required fields

```text
candidate_id
candidate_type
entity_key
previous_observed_period
current_observed_period
last_observed_present
first_observed_absent
previous_artifact_id
current_artifact_id
previous_locator
current_locator
observation_contiguous
missing_expected_periods
evidence_state = observational_only
```

`candidate_id` is deterministic SHA-256 over the canonical semantic tuple. No random UUID.

### Gap / censoring rule

If an expected monthly FONDREGISTRO snapshot is missing, do not place the event inside the gap. Preserve only observed bounds. First/last dataset boundaries are left/right-censored; they are not appearance/disappearance events without an adjacent observed comparison.

## 4. G9-R measurement preregistration

Before any lifecycle adjudication code:

1. enumerate every available monthly FONDREGISTRO period in the local artifact ledger from 2012 to latest;
2. validate month continuity and record missing expected months;
3. for each adjacent **observed** period compute exact fund-key set difference;
4. materialize counts of `FUND_APPEARED` and `FUND_DISAPPEARED` by month and entity type;
5. separately measure compartment deltas;
6. report first/last observed period for every fund key;
7. reconcile annual candidate counts against independent CNMV aggregate/weekly registry evidence where comparable, but never force equality across different publication semantics;
8. freeze the measurement fingerprint before writing lifecycle rules.

Known repo checkpoints are descriptive only, not candidate counts:

```text
2012-03  funds=2306
2025-03  funds=1473
2025-12  funds=1438
```

Net differences (`-868`, `-35`) are **not** disappearance counts and must never be reported as such.

Current execution note: raw CNMV artifacts are intentionally absent from the public Git repository. Exact month-to-month candidate counts must be executed against the existing local `data-dir`; G9-R does not claim PASS until this measurement is recorded.

## 5. G9-B — official evidence ledger

Do not jump from candidate to canonical event.

Provisional tables:

```text
lifecycle_source_documents
lifecycle_source_observations
lifecycle_assertions
```

### LifecycleSourceDocument

```text
source_document_id
source_family
source_url
retrieved_at
raw_sha256
publication_date?
official_identifier?
source_actor
supersedes_document_id?
```

### LifecycleAssertion

```text
assertion_id
source_document_id
assertion_type
assertion_stage
subject_key?
subject_identifier_raw
object_key?
object_identifier_raw?
effective_date?
publication_date?
raw_text
source_locator
parser_version
representation = structured | partially_structured | verbatim_only
```

Exact CNMV register numbers are authoritative join keys when present. Names are retained verbatim but never used as authoritative fuzzy identity.

## 6. Source assertion semantics

Provisional assertion classes may include:

```text
REGISTRATION_RECORDED
DEREGISTRATION_RECORDED
MERGER_REQUESTED
MERGER_AUTHORIZED
MERGER_REGISTERED
MERGER_EXECUTED
MERGER_RENOUNCED
DISSOLUTION_APPROVED
LIQUIDATION_EXECUTED
TRANSFORMATION_RECORDED
MANAGER_SUBSTITUTION_RECORDED
DEPOSITARY_SUBSTITUTION_RECORDED
UNKNOWN_ASSERTION
```

Final taxonomy is frozen only after the development gold corpus.

Key rule: `MERGER_AUTHORIZED` can create a lifecycle **candidate/evidence assertion**, never a VERIFIED lineage edge. A later `MERGER_EXECUTED` or `MERGER_REGISTERED` source is required for executed lineage.

## 7. G9-C/D/E — event, identity episodes, lineage

Adjudication states:

```text
VERIFIED
SUPPORTED
AMBIGUOUS
CONTRADICTORY
UNRESOLVED
```

No probabilistic confidence score is part of the canonical contract.

Provisional final event taxonomy:

```text
REGISTERED
FIRST_ACTIVITY_OBSERVED
RENAMED
MANAGER_CHANGED
DEPOSITARY_CHANGED
STRUCTURE_CHANGED
MERGED_INTO
ABSORBED_INTO
ABSORBED_FROM
TRANSFORMED_INTO
TRANSFERRED_OUT
TRANSFERRED_IN
DISSOLVED
LIQUIDATED
DEREGISTERED
NEVER_OBSERVED_ACTIVE
UNKNOWN_EXIT
```

This list is provisional. Evidence decides which distinctions are actually sustainable.

### Lineage edge

```text
lineage_edge_id
predecessor_vehicle_key
successor_vehicle_key
relation_type
effective_at?
publication_date?
observed_at
source_assertion_id
evidence_state
```

Lineage links distinct vehicles; it never asserts they are the same identity. A transformation to an ordinary SA/SL is not forced into a fund-to-fund edge.

### Identity episodes

If later useful, `identity_episode` references the existing `fund_key` and spans observed state intervals. Monthly observations may bound a change; they do not create an exact legal effective date.

## 8. Temporal semantics

Keep distinct:

```text
effective_at        # only explicit official effective/legal date
publication_date    # date source was published/registered
observed_at         # when our system observed/adjudicated evidence
retrieved_at        # artifact acquisition time
last_observed_present / first_observed_absent  # registry interval bounds
```

Never choose the midpoint/end/start of an observation interval as `effective_at`.

## 9. Correction and source-actor semantics

Relevant-information records can be rectified/superseded. Source ingestion must preserve correction chains; a corrected assertion cannot silently coexist as equally current truth.

Distinguish at least:

```text
CNMV_RESOLUTION
REGISTRY_BULLETIN
REGULATED_ENTITY_COMMUNICATION
SUBMITTED_DOCUMENT
```

The source actor is evidence metadata, not an automatic source-precedence rule.

## 10. Gold corpus and blind holdout

Development/regression corpus must contain at least:

- plain active fund;
- simple rename;
- manager change;
- depositary change;
- dissolution/liquidation;
- domestic merger with later execution;
- merger authorization later renounced;
- cross-border merger/transfer;
- disappearance with no explanatory evidence;
- registered vehicle with weak/no activity evidence;
- transformation from SICAV to ordinary company;
- ambiguous successor;
- correction/rectification chain;
- multiple lifecycle events close in time.

Split into `development`, `regression`, `blind_holdout`. The blind holdout is not inspected while rules are developed.

## 11. Preregistered precision gates

Fixed before holdout inspection:

```text
provenance completeness                  = 100%
fabricated successor                     = 0
silent identity collision                = 0
verified wrong lifecycle classification = 0
successor exact precision               >= 99%
lifecycle type precision                >= 99%
```

Also report, with denominators:

```text
candidate coverage
adjudication coverage
exact effective-date coverage
exact successor coverage
AMBIGUOUS count
UNRESOLVED count
CONTRADICTORY count
```

Recall may be lower. `UNRESOLVED` is preferred to false resolution.

Additional invariants:

- category `Fusión de IIC` alone never yields VERIFIED `MERGED_INTO`;
- merger authorization alone never yields a lineage edge;
- `BAJA` alone proves registry exit, not liquidation cause;
- exact successor is never produced by name similarity;
- correction/supersession chains are respected;
- unknown source templates fail closed / remain verbatim;
- same canonical evidence + rule version => same event/edge IDs and fingerprints;
- offline rebuild succeeds once source artifacts are frozen.

## 12. Kill criteria

G9 closes `FAIL` or `INCONCLUSIVE` if official evidence cannot meet the precision/provenance gates. In that case OpenFunds retains mechanical `fund-events` and does not manufacture causal lifecycle.

## 13. G9-R status

- OSS reuse review: **PASS**.
- Official-source viability: **STRONGLY SUPPORTED**.
- Full month-to-month FONDREGISTRO appearance/disappearance measurement: **PENDING LOCAL ARTIFACT EXECUTION**.

Therefore overall **G9-R remains OPEN, not PASS**.

## 14. Next executable step

Run the preregistered G9-A measurement over every monthly FONDREGISTRO partition in the existing local `data-dir`, freeze counts/gaps/fingerprint, then sample candidates against weekly registry bulletins + relevant-information histories. Do not implement lifecycle adjudication until that measurement is committed.