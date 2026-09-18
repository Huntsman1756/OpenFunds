# G9-R — official lifecycle source review

Date: 2026-09-18
Base HEAD: `8108484bc23f78c7c7c2cb706a09c3e2a290cb04`

## Executive finding

G9 should **not** be designed as `registry disappearance → free-text guess`.

CNMV exposes at least two materially stronger lifecycle evidence surfaces:

1. **Operaciones de Registro Semanales** — a weekly bulletin of registry acts with structured sections such as `NUEVAS INSCRIPCIONES`, `BAJAS`, `MODIFICACIONES`, and `FUSIÓN DE FONDOS DE INVERSIÓN`. Merger text can state exact CNMV register numbers for absorbed and absorbing funds.
2. **Hechos relevantes de IIC y otras entidades autorizadas** — long historical event timelines with date/time, entity, category, registration number, summary text, and source documents. Categories include `Fusión de IIC`, `Baja/Disolución/Liquidación/Absorción`, `Revocación de IIC`, and `Sustitución de Gestora o Depositario de IIC`.

These sources complement monthly FONDREGISTRO: snapshots generate candidates; registry acts and relevant information explain/legalize them.

## Source matrix

| source_family | Coverage / retention observed | Identifiers | Structure | Dates | Lifecycle information | Limitations / G9 use |
|---|---|---|---|---|---|---|
| `FONDREGISTRO` | Monthly, 2012→present (already acquired in OpenFunds) | exact `(Tipo, NumeroRegistro)` plus compartment/class keys | structured XML | observed month | presence/absence; name/manager/depositary/structure snapshots | **Candidate source only.** Cannot prove cause or exact effective date. |
| `CNMV_WEEKLY_REGISTRY_BULLETIN` | Weekly portal; historical bulletins are searchable. Full retention boundary still to measure | denomination + exact CNMV register number; merger prose gives predecessor/successor numbers | semi-structured sections/tables + deterministic registry prose | week; individual act wording may carry additional dates | new registration, deregistration (`BAJAS`), registered merger, name/manager/depositary and other registry changes | Strong evidence of a registry act. `BAJA` alone does not prove liquidation/merger cause. No bulk API/rate limit documented. |
| `CNMV_IIC_RELEVANT_INFORMATION` | Search results explicitly expose history from 01/07/1988 on sampled entities | entity/NIF on page; event registration number; prose often contains exact CNMV fund register numbers | structured metadata + category + summary + linked document; content can be free text | publication date/time; some records explicitly state legal/effective/execution dates | merger authorization/execution/renunciation, dissolution/liquidation, transformation, manager/depositary substitution, cross-border events | Category is routing metadata, **not** final lifecycle type. Correction/rectification chains must be modeled. Some items are CNMV resolutions; others are regulated-entity communications. |
| `CNMV_MERGER_PROJECT_OR_APPLICATION` | Available as official documents for sampled cases; historical coverage to measure | often exact predecessor/successor names and CNMV register numbers | partially structured / document text | project/application/approval dates may appear | proposed merger terms, parties, exchange mechanics | Proposal/application/authorization is not execution. Evidence stage must remain pre-event until later source proves effectiveness. |
| `CNMV_FUND_DETAIL_AND_PERIODIC_DOCS` | Existing current/historical fund surfaces | CNMV register number, NIF, share-class ISINs | structured/semi-structured | registration dates and report dates where present | registration-date corroboration; identity state | Secondary corroboration, not a merger engine. |
| `CNMV_FOREIGN_IIC_REGISTER` | Current/historical registry surface | foreign-IIC CNMV register number + legal/fund identity | structured registry | registry dates where published | exact target identity for cross-border mergers/transfers | Needed only when official source names a foreign successor. Do not fuzzy-match names. |
| `CNMV_ANNUAL_AGGREGATES` | Annual reports/statistics | aggregate only | tabular/statistical | annual | independent totals for registrations/deregistrations | Oracle/reconciliation only; cannot create row-level lifecycle events. |

## Source evidence that changes the design

### Weekly bulletin can prove an exact registered absorption

A sampled bulletin places `BANKINTER DEUDA PUBLICA 2025, FI` (CNMV 5659) under `BAJAS` and in the same fund section states that the merger by absorption into `BANKINTER DEUDA PUBLICA 2029, FI` (CNMV 5949) is registered. This is stronger than inferring a successor from a simultaneous disappearance/appearance.

### `Fusión de IIC` is a lifecycle **stage**, not proof of completion

Sampled relevant-information histories show both:

- authorization followed later by execution/effectiveness;
- authorization followed by **renunciation**.

Therefore:

```text
MERGER_AUTHORIZED != MERGED_INTO
```

A lineage edge cannot be VERIFIED solely because a merger authorization exists.

### Exact effective dates sometimes exist

Some relevant-information items explicitly state execution/effectiveness dates. When present, G9 may set `effective_at` from that source. When absent, G9 must retain an observation interval (`last_observed_present`, `first_observed_absent`) and leave exact `effective_at` null.

### Cross-border successor identity is possible

Sampled CNMV records explicitly identify Luxembourg UCITS / foreign IIC successors, sometimes including the CNMV foreign-IIC register number. This supports exact cross-border lineage when that identifier is present; it does not justify name-only matching.

### Transformations are not fund-to-fund succession

CNMV histories contain voluntary deregistration after transformation of a SICAV into an ordinary company. That is a terminal CNMV-IIC event and possibly a legal-vehicle continuation, but it is **not** a successor investment fund. The lineage model must not force every exit into `fund → fund`.

### Source actor and corrections matter

CNMV relevant-information pages mix CNMV resolutions and regulated-entity communications, and rectification/supersession exists. Every source observation therefore needs:

```text
source_actor
source_category
official_event_registration_number
publication_date
effective_date_if_explicit
corrects_or_supersedes?
raw_text
source_locator
```

## Provisional source-stage vocabulary

This is a source assertion stage, not the final lifecycle taxonomy:

```text
REQUESTED
PROPOSED
AUTHORIZED
APPROVED
REGISTERED
EXECUTED
RENOUNCED
DISSOLUTION_AGREED
LIQUIDATION_EXECUTED
DEREGISTERED
TRANSFORMATION_RECORDED
UNKNOWN_STAGE
```

Do not freeze the final list until the development gold corpus has been inspected.

## Legal / reuse treatment

G9 inherits `docs/research/licensing.md`: official bytes remain local immutable artifacts; repository code, manifests/hashes and source provenance may be published under the existing policy; bulk redistribution of CNMV raw/normalized records remains outside this gate and flagged for legal review.

## G9-R source verdict

**SOURCE VIABILITY: STRONGLY SUPPORTED.**

The official evidence surface is richer and more structured than the initial prompt assumed. The design should prioritize weekly registry acts + IIC relevant-information assertions before considering generic document parsing.

Overall G9-R remains **OPEN** until the full monthly FONDREGISTRO appearance/disappearance measurement has run over the local artifact history.