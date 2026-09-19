# G9-B preregistration — official lifecycle source-assertion ledger

Date: 2026-09-19
Base: G9-A2 `8213913`, G9-B-R `6ee2a00` (PASS)
Status: **PREREGISTERED BEFORE PRODUCTION INGESTION**.

G9-B builds **evidence**. It does not adjudicate lifecycle; it does not
materialize canonical `MERGED_INTO`/`LIQUIDATED`/`DEREGISTERED`; it does
not open G10.

## 1. Frozen invariants

```text
FUND_DISAPPEARED          != LIQUIDATED
MERGER_AUTHORIZED         != MERGER_EXECUTED
MERGER_REGISTERED         != explicit effective_at
BAJA                      != cause of BAJA
source assertion          != adjudicated lifecycle event
weekly registration date  != legal effective date
publication datetime      != effective date
exact successor absent    != no successor
name similarity           != identity
```

`fund_key` remains canonical OpenFunds identity.

## 2. Source architecture (measured, G9-B-R)

```text
SPINE:      CNMV_WEEKLY_REGISTRY_BULLETIN   (chronological, 2004->present)
SECONDARY:  CNMV_IIC_RELEVANT_INFORMATION   (per-entity history)
AUXILIARY:  FONDREGISTRO denominacion markers (baja / EN LIQUIDACION)
```

The bulletin spine must be able to produce a complete evidence ledger
even when `relevant_information` is `NOT_FOUND`. HR enriches stage,
dates, and successor; it is never a prerequisite.

## 3. Three mandatory levels — never collapsed

```text
lifecycle_source_documents     one official acquired artifact
lifecycle_source_observations  one recognizable registry/event unit
lifecycle_assertions           zero-or-more per observation
```

Plus:

```text
lifecycle_entity_resolutions   fund_key -> NIF discovery evidence (HR)
candidate_source_evidence      candidate_id x assertion links
```

No candidate linkage for the 250 sealed blind-holdout ids
(`docs/g9/blind-holdout-manifest.json`). Raw document acquisition may
incidentally download documents containing holdout funds — allowed;
candidate-specific linkage/parsing for holdout ids is forbidden.

## 4. lifecycle_source_documents

```text
source_document_id      sha256(family|logical_key|raw_sha256)[:20]
source_family           cnmv_weekly_registry | cnmv_iic_relevant_information | fondregistro
logical_source_key      weekly_registry/<week_id>/<role>
                        hr/<nif>/history/page-<n>
                        hr/search/<candidate_id>
                        fondregistro/<period>
source_url              retrieval URL (provenance, not canonical id)
source_role             registro | boletin_completo | entity-search | entity-history | registry-monthly
publication_date?       bulletin: week end; FONDREG: period end; HR: none
retrieved_at
raw_sha256
content_type
size_bytes
artifact_id             ArtifactStore source_id
supersedes_document_id? new bytes for same logical key -> new doc id
parser_eligible
```

Raw bytes live in `ArtifactStore` (blob payload, SHA-256 addressed).
The `verdocumento?e=` token is retrieval provenance, never identity.

## 5. lifecycle_source_observations

```text
source_observation_id   sha256(document_id|locator|unit_seq)[:20]
source_document_id
source_family
source_section_raw      e.g. BAJAS | FUSION DE FONDOS DE INVERSION | <hr category>
subject_name_raw
subject_register_number_raw
regnums_in_text         all register numbers verbatim
successor_regnums       register numbers inside the ', por <fund>' clause
entity_name_raw         HR entity header
entity_nif
entity_resolution_state EXACT_REGNUM_CORROBORATED | DISCOVERY_ONLY |
                        AMBIGUOUS | NOT_FOUND | NULL
resolved_fund_key?      only when EXACT_REGNUM_CORROBORATED
official_event_registration_number   HR event id — NOT the fund regnum
publication_datetime
category_raw
observation_text_verbatim
attachment_url
source_locator          page/section/unit anchor
correction_indicator
representation          structured | partially_structured | verbatim_only
parser, parser_version
```

Unrecognized historical template -> `verbatim_only`. Evidence is never
dropped because it cannot be normalized.

## 6. lifecycle_assertions

```text
assertion_id            sha256(observation_id|type|subject|object|seq)[:20]
source_observation_id
source_document_id
assertion_type          provisional taxonomy below
assertion_stage         REQUESTED | PROPOSED | AUTHORIZED | APPROVED |
                        REGISTERED | EXECUTED | RENOUNCED |
                        DISSOLUTION_AGREED | LIQUIDATION_EXECUTED |
                        DEREGISTERED | TRANSFORMATION_RECORDED |
                        REPORTED | UNKNOWN_STAGE
subject_key?            FI:<regnum> only when entity type unambiguous
subject_identifier_type cnmv_register_number | entity_name | nif | none
subject_identifier_raw
object_key?             FI:<regnum> only for exact domestic regnum
object_identifier_type?
object_identifier_raw?  name verbatim when no regnum
asserted_date?          explicit official date only — else NULL
asserted_date_semantics?EFFECTIVE_DATE | EXECUTION_DATE |
                        AUTHORIZATION_DATE | REGISTRATION_DATE |
                        DISSOLUTION_DATE | LIQUIDATION_DATE |
                        SOURCE_BAJA_MARKER_DATE | OTHER_EXPLICIT_DATE
publication_datetime
raw_text
source_locator
identity_state          exact_register_number | unresolved
representation
correction_of_observation_id?
supersedes_assertion_id?
correction_target_state resolved | unresolved
parser_version, rule_version
```

### Bulletin assertion types

```text
REGISTRATION_RECORDED              NUEVAS INSCRIPCIONES
DEREGISTRATION_RECORDED            BAJAS
MERGER_REGISTRATION_RECORDED       FUSION prose (subject=absorbed regnum,
                                   object=por-clause regnum or verbatim name)
OTHER_REGISTRY_ACT                 delegacion/revocacion gestion,
                                   modificaciones, actualizaciones
UNKNOWN_REGISTRY_ASSERTION
```

### HR assertion types

```text
MERGER_REQUESTED / MERGER_PROPOSED / MERGER_AUTHORIZED /
MERGER_REGISTERED / MERGER_EXECUTED / MERGER_RENOUNCED
DISSOLUTION_AGREED / LIQUIDATION_EXECUTED
DEREGISTRATION_REPORTED / TRANSFORMATION_RECORDED
MANAGER_SUBSTITUTION_REPORTED / DEPOSITARY_SUBSTITUTION_REPORTED
RECTIFICATION_REPORTED
OTHER_LIFECYCLE_ASSERTION / UNKNOWN_ASSERTION
```

`AUTHORIZED` is never auto-upgraded to `EXECUTED` by later
disappearance. `REGISTERED` and `EXECUTED` are distinct stages.

### FONDREGISTRO marker assertions

```text
REGISTRY_NAME_BAJA_MARKER           'baja dd.mm.yyyy' in denominacion
REGISTRY_NAME_IN_LIQUIDATION_MARKER '(EN LIQUIDACION)' in denominacion
```

`baja` marker date -> `asserted_date` with semantics
`SOURCE_BAJA_MARKER_DATE` — never auto-`effective_at`.

## 7. Corrections

Corrections are first-class: original observations/assertions are never
deleted. A rectification links `correction_of_observation_id` only when
it unambiguously references a prior unit; otherwise
`correction_target_state = unresolved` — never nearest-match guessing.
Same for renunciation/desistimiento/anulación.

## 8. Candidate linkage

```text
candidate_id            sha256("FUND_DISAPPEARED"|fund_key|prev|curr)[:16]
assertion_id
link_state              EXACT_SUBJECT_REGNUM | EXACT_OBJECT_REGNUM |
                        AMBIGUOUS
```

Only exact CNMV register numbers create links. Temporal proximity alone
never proves causality; blind-holdout ids produce zero link rows.

## 9. Determinism & offline rebuild

```text
same raw documents + same parser/rule version
    = same observations, assertions, links, fingerprints
```

Processing timestamps are excluded from fingerprints. After the crawl,
an offline rebuild from ArtifactStore must reproduce identical
fingerprints with 0 network requests.

## 10. Preregistered gates

```text
raw document provenance                 = 100%
source observations with provenance     = 100%
assertions with provenance              = 100%
silent source-document loss             = 0
silent unknown-template coercion        = 0
fuzzy subject identity                  = 0
fuzzy successor identity                = 0
AUTHORIZED auto-upgraded to EXECUTED    = 0
BAJA auto-upgraded to LIQUIDATED        = 0
holdout linked/inspected                = 0
offline rebuild                         = PASS
deterministic fingerprints              = PASS
G1-G8 fingerprint changes               = 0
G9-A2 measurement fingerprint changes   = 0
```

Coverage is measured, not a PASS threshold.
