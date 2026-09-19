# G9-C — Lifecycle Taxonomy Freeze

Status: **FROZEN** (measurement-gated; no canonical events emitted).

Base: G9-B ledger `e2997ce6…8721`, candidates `e1ab53d3…e54`.

This document freezes the **semantic axes** that G9-E will adjudicate.
Nothing here is a production lifecycle event, lineage edge, or terminal
verdict. Values below are the *allowed vocabulary* — the adjudication
rules that assign them are preregistered separately in G9-E.

## Design result

Evidence signatures measured over 2,273 dev candidates: **39 distinct**,
top-10 cover 96.6%. The taxonomy is therefore deliberately small.

## Axis 1 — `event_family`

What legal/registry process the source act describes.

| value | definition | required evidence | non-equivalences |
|---|---|---|---|
| `REGISTRATION` | alta / inscripción en registro | registry act "incorporar/inscribir" | not disappearance-related |
| `DEREGISTRATION` | baja en registro | "cancelar la inscripción" | ≠ cause; baja is an *act*, not a reason |
| `MERGER` | fusión por absorción | "fusión" / "absorción" act-object | ≠ executed merger — see stage |
| `DISSOLUTION` | acuerdo de disolución | "disolución" in source prose | ≠ LIQUIDATION (may precede it) |
| `LIQUIDATION` | liquidación | "liquidación" act or `(EN LIQUIDACION)` marker | ≠ DEREGISTRATION |
| `TRANSFORMATION` | cambio de forma jurídica / fuera de IIC | "transformación" | not observed in dev → see below |
| `NAME_CHANGE` | cambio de denominación | "modificación de denominación" | never an exit by itself |
| `MANAGER_CHANGE` | sustitución de gestora | "sustituir la entidad gestora" | never an exit by itself |
| `DEPOSITARY_CHANGE` | sustitución de depositaria | same | never an exit |
| `OTHER_REGULATORY_ACT` | any other typed act | typed non-exit act | — |
| `UNKNOWN` | act not classifiable | verbatim preserved | — |

Observed in dev evidence: `TRANSFORMATION` **not observed** →
**DEFERRED** (kept in vocabulary, no adjudication rule emits it until
evidence appears). `TRANSFER` likewise **not observed** → DROPPED as
event_family (kept only as lineage_relation candidate).

## Axis 2 — `event_stage`

Where in the process the source act sits. **No universal ordering** —
stages are per-source verbatim, never promoted.

| value | source |
|---|---|
| `REQUESTED` / `PROPOSED` | not observed → DEFERRED |
| `AUTHORIZED` | HR "autorización" event |
| `APPROVED` | not observed → DEFERRED (kept for vocabulary completeness) |
| `REGISTERED` | bulletin "inscribir/calificar" the merger |
| `EXECUTED` | HR "ejecución" / "ecuación de canje definitiva" |
| `RENOUNCED` | "renuncia a la fusión" |
| `RECTIFIED` | "rectificación" (relation via correction graph) |
| `REPORTED` | generic HR/structured record |
| `DEREGISTERED` | baja act itself |
| `UNKNOWN` | — |

**Frozen fact**: `AUTHORIZED` → `EXECUTED` promotion is forbidden.
Observed: AUTHORIZED 2,551 vs EXECUTED 197 in assertions; at candidate
level 169 follow `AUTHORIZED→REGISTERED→EXECUTED`.

## Axis 3 — `participant_role`

Source-evidence semantics only (never final lineage):

| value | assignment |
|---|---|
| `SUBJECT` | entity the act is about / entity-context of an entity-scoped source (HR history) |
| `ABSORBED` | exact regnum in act text, not in `, por <X>` successor clause |
| `ABSORBING` | exact regnum in `, por <X>` successor clause |
| `PREDECESSOR` | reserved — no deterministic source rule yet → DEFERRED |
| `SUCCESSOR` | reserved — same |
| `TARGET` | explicit object identifier not otherwise classified |
| `UNKNOWN` | text regnum with no role-determining wording |

Observed distribution: ABSORBED 19,519 · SUBJECT 21,995 ·
ABSORBING 5,159 · TARGET 129 · UNKNOWN 6. Max 29 participants/assertion.

## Axis 4 — `terminal_outcome` (future; not materialized)

Why a `fund_key` left FONDREGISTRO.

| value | means | does NOT mean |
|---|---|---|
| `ABSORBED` | ceased as fund; official evidence names it absorbed participant of a completed/registered merger | merger merely authorized/proposed; another fund in the same doc absorbed |
| `LIQUIDATED` | liquidation evidenced (LIQUIDATION act or in-liquidation marker + baja) | dissolution agreement alone |
| `TRANSFORMED_OUT_OF_IIC` | transformed to non-IIC vehicle | not observed → DEFERRED |
| `TRANSFERRED_OUT` | assets transferred, vehicle persists elsewhere | not observed → DROPPED |
| `DEREGISTERED_OTHER` | baja without merger/liquidation evidence | a "cause" — it is residual |
| `UNKNOWN_EXIT` | insufficient/conflicting evidence | a guess |

## Axis 5 — `lineage_relation` (future; no edges materialized)

| value | evidence needed |
|---|---|
| `ABSORBED_BY` | absorbed participant + exact absorbing regnum |
| `TRANSFORMED_TO` | transformation evidence → DEFERRED |
| `TRANSFERRED_TO` | transfer evidence → DROPPED |
| `SPLIT_INTO` | split evidence → DROPPED (never observed) |
| `OTHER_SUCCESSION` | residual, documented only |

**Retired concepts** (old provisional vocabulary): `MERGED_INTO`,
`ABSORBED_INTO`, `ABSORBED_FROM` — all three collapse into
`ABSORBED_BY`. Source prose never distinguishes "merged into" from
"absorbed into"; `ABSORBED_FROM` is just the inverse role of the
surviving vehicle, not a distinct event.

## Axis 6 — `adjudication_state`

| value | meaning |
|---|---|
| `UNADJUDICATED` | default |
| `POTENTIAL` | evidence sufficient under preregistered rules |
| `CONFLICTING` | contradictory official evidence; abstain |
| `INSUFFICIENT_EVIDENCE` | abstain |
| `ADJUDICATED` | validated on gold + regression + holdout |

## Taxonomy decisions (KEPT / MERGED / RENAMED / DROPPED / DEFERRED)

| old concept | decision | reason |
|---|---|---|
| `MERGED_INTO` | MERGED → `ABSORBED_BY` | sources never distinguish merge vs absorption |
| `ABSORBED_INTO` | RENAMED → `ABSORBED_BY` | direction made explicit |
| `ABSORBED_FROM` | DROPPED | inverse role, not an event |
| `MERGER_EXECUTED` as cause | MERGED → family `MERGER` + stage `EXECUTED` | axes separated |
| `TRANSFERRED_OUT` | DROPPED | never observed in FI evidence |
| `SPLIT_INTO` | DROPPED | never observed |
| `TRANSFORMATION*` | DEFERRED | vocabulary kept; no dev evidence |
| `PREDECESSOR`/`SUCCESSOR` roles | DEFERRED | no deterministic source rule |
| `DISSOLVED` vs `LIQUIDATED` | KEPT both | sequential legal stages; observed combos measured — not forced exclusive |
| `DEREGISTERED` | KEPT as residual outcome | coexists with specific causes; not mutually exclusive |

## Invariants carried into G9-E

- participant roles come only from source wording — no fuzzy matching
- `AUTHORIZED` never promotes to `EXECUTED`
- >1 exact successor ⇒ `CONFLICTING`, never silently resolved
- corrections supersede via the correction graph; originals never deleted
- baja alone never implies a cause
- temporal gaps are diagnostics, never identity proof
