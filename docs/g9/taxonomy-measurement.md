# G9-C — Lifecycle Taxonomy Measurement & Freeze

Verdict: **PASS** — taxonomy measured and frozen over the G9-B ledger.
No canonical lifecycle events, no lineage edges, no holdout access.

Base: G9-A2 `8213913` · G9-B-R `6ee2a00` · G9-B `9ce46e9`.

---

## CANDIDATE PROFILES

```text
count:        2,273 / 2,273
fingerprint:  8add87b77e8ff8eaa88f8a6593852cbc6d7cdb289de877486a9fc50b6c666423
conservation: PASS (one profile per dev candidate; zero extra)
provenance:   100% — every assertion cited via assertion_ids
holdout:      0 profiles materialized
```

## ASSERTION PARTICIPANTS

```text
table required?:      YES — source assertions are genuinely multiparty
rows:                 46,808
role distribution:    SUBJECT 21,995 · ABSORBED 19,519
                      ABSORBING 5,159 · TARGET 129 · UNKNOWN 6
max participants:     29 (one merger registration act)
identity:             exact_register_number 41,005 · unresolved 5,803
unresolved roles:     5,803 (entity-context + verbatim names; never
                      promoted to exact)
fingerprint:          65a0a6d7d5a81ac57641c1bd832b1edc1b280115a0c52b1015dbc6eb6489e379
```

Multipart evidence measured per type:

```text
MERGER_REGISTRATION_RECORDED   up to 29 exact regnums/assertion
MERGER_AUTHORIZED              up to 18
MERGER_EXECUTED                231 assertions with zero text regnums
                               (subject = entity-context absorber)
MERGER_RENOUNCED               sparse — entity-context only
```

Design consequence: `subject_key`/`object_key` retained for
compatibility; `lifecycle_assertion_participants` is the evidence grain.
A terse `MERGER_EXECUTED` yields **only** the entity-context `SUBJECT` —
never an inferred `ABSORBING`. Unresolved HR events (dissolution,
rectification) get entity-context `SUBJECT` so the entity whose
official history records them is measurable as participant.

## EVIDENCE SIGNATURES

```text
distinct:            39
top-10 coverage:     2,196 / 2,273 = 96.6%
singletons:          17
rare (count ≤ 10):   28 signatures
```

Top signatures (bits: DEREG·AUTH·REG·EXEC·REN·DISS·LIQ·IN_LIQ·
BAJA_MK·TRANS·RECT·ABSORBED·ABSORBING·#SUCC·CONSISTENT·CONFLICT):

```text
1  DEREG+AUTH+REG+ABSORBED, 1 succ, consistent         1,617  (71.1%)
2  same + ABSORBING also present                       254
3  same as 1 + EXECUTED in own HR history              131
4  same as 1, >1 successor (CONFLICT)                  64
5  same as 2 + EXECUTED                                30
6  DEREG only, no merger, no successor                 29
7  DEREG + IN_LIQUIDATION marker, no merger            24
8  DEREG+REG only (no AUTHORIZED)+ABSORBED, 1 succ     17
9  AUTH+REG+ABSORBED+ABSORBING, >1 succ (CONFLICT)     15
10 as 1 + BAJA_MARKER                                  15
```

**Headline finding**: signatures 1–3 + 8–10 are all "baja +
registered/authorized merger + absorbed + single successor" variants —
≈2,050 candidates (90%). G9-E can be a small explicit engine.

## MERGER PATHS (dev candidates with any merger evidence)

```text
AUTHORIZED→REGISTERED            1,996
AUTHORIZED→REGISTERED→EXECUTED     169
AUTHORIZED→EXECUTED                  3
AUTHORIZED only                     23
REGISTERED only                     22
AUTHORIZED→REGISTERED→RENOUNCED      3
EXECUTED via absorber (sole link)    0
other                                0
```

By era: `AUTHORIZED→REGISTERED` dominates every year 2012–2026;
`→EXECUTED` evidence concentrates 2012–2015 (24/39/23/29) then thins —
the HR execution event exists mostly for older mergers.
`MERGER_EXECUTED` **never** names the absorbed fund in text — it links
candidates only via entity-context of their own HR history (169/2,216
merger candidates, 7.6%). G9-E must NOT require EXECUTED.

## SUCCESSOR CONSISTENCY

```text
0 exact successors (SUCCESSOR_ABSENT):     83
1 exact successor (SUCCESSOR_SINGLE):    2,106
>1 exact successors (SUCCESSOR_CONFLICT):  84
```

Cross-source agreement for the 2,106 single-successor cases:

```text
bulletin + HR agree on same successor:   2,037  (96.7%)
weekly bulletin only:                       44
HR only:                                    25
```

No conflict auto-resolved. The 84 `>1 successor` profiles are
exhaustively in development gold.

## SUCCESSOR TEMPORALITY (FONDREGISTRO presence of exact successors)

```text
already existing before disappearance:  2,240
same-month appearance:                      0
later appearance:                          35
not in FI registry:                         0
foreign/non-FI:                             0
```

Descriptive only — later appearance is not rejected (e.g. successor
registered after absorption act). All 2,275 exact successor references
are domestic CNMV regnums; no foreign successor was asserted.

## DISSOLUTION / LIQUIDATION — combination matrix

```text
DEREG+MERGER                        2,171
DEREG only                             29
IN_LIQUIDATION+DEREG                   24
MERGER only (no DEREG linked)          23
BAJA_MARKER+DEREG+MERGER               17
IN_LIQUIDATION+DEREG+MERGER             4
IN_LIQUIDATION only                     2
LIQUIDATION+DEREG+MERGER                1
LIQUIDATION+IN_LIQUIDATION+DEREG        1
```

`DISSOLUTION_AGREED` participates in **zero** dev candidates — its 9
assertions all carry unresolved subjects in histories of non-candidate
entities (entity-resolution states DISCOVERY_ONLY/NOT_FOUND). The
merger+dissolution "contradiction" measured as `MERGER_PLUS_LIQUIDATION`
in exactly **1** candidate (`83c9dec1c99e072f`) plus 4
`IN_LIQUIDATION+MERGER` marker combos — all preserved as
evidence-pattern flags in gold, none adjudicated. Prior heuristic count
of five contradiction candidates was name-text-based; participant-
normalized evidence shows the phenomenon is rarer than estimated.

## TEMPORAL PROFILE (assertion publication → first_observed_absent, months)

```text
MERGER_AUTHORIZED     n=8,692  p10=2  p50=3  p90=20  min=-123 max=160
MERGER_REGISTRATION   n=9,794  p10=-1 p50=0  p90=25  min=-127 max=158
MERGER_EXECUTED       n=180    p10=0  p50=0  p90=2   min=0    max=13
LIQUIDATION_EXECUTED  n=4      —     p50=8           min=5    max=14
```

Negative/positive tails reflect per-entity HR history ordering, not
anomalies. EXECUTED publications cluster tightly at disappearance
(p50=0). Temporal gaps are diagnostics only.

## CORRECTIONS

```text
rectifications:      3  (all correction_target_state = unresolved —
                     no explicit target date; never auto-linked)
renunciations:       3  (2 with other merger evidence → flag)
exact links:         0
unresolved links:    3
```

Originals never deleted; renunciations remain source assertions.

## TAXONOMY CHANGES

```text
MERGED_INTO           MERGED   → ABSORBED_BY      (indistinguishable in sources)
ABSORBED_INTO         RENAMED  → ABSORBED_BY      (explicit direction)
ABSORBED_FROM         DROPPED                     (inverse role, not an event)
MERGER_EXECUTED=cause MERGED   → family+stage axes separated
TRANSFERRED_OUT       DROPPED                     (never observed)
SPLIT_INTO            DROPPED                     (never observed)
TRANSFORMATION*       DEFERRED                    (vocabulary kept)
PREDECESSOR/SUCCESSOR DEFERRED                    (no deterministic rule)
DISSOLVED/LIQUIDATED  KEPT both                   (sequential stages)
DEREGISTERED          KEPT residual               (coexists with causes)
```

Full semantics: `docs/g9/lifecycle-taxonomy.md` (frozen).

## FINAL TAXONOMY

```text
event_family:      REGISTRATION DEREGISTRATION MERGER DISSOLUTION
                   LIQUIDATION TRANSFORMATION* NAME_CHANGE
                   MANAGER_CHANGE DEPOSITARY_CHANGE
                   OTHER_REGULATORY_ACT UNKNOWN
event_stage:       REQUESTED* PROPOSED* AUTHORIZED APPROVED*
                   REGISTERED EXECUTED RENOUNCED RECTIFIED
                   REPORTED DEREGISTERED UNKNOWN
participant_role:  SUBJECT ABSORBED ABSORBING PREDECESSOR*
                   SUCCESSOR* TARGET UNKNOWN
terminal_outcome:  ABSORBED LIQUIDATED TRANSFORMED_OUT_OF_IIC*
                   DEREGISTERED_OTHER UNKNOWN_EXIT
lineage_relation:  ABSORBED_BY TRANSFORMED_TO* OTHER_SUCCESSION
adjudication_state: UNADJUDICATED POTENTIAL CONFLICTING
                   INSUFFICIENT_EVIDENCE ADJUDICATED

(* = DEFERRED — in vocabulary, no rule emits it yet)
```

## TAXONOMY APPLICABILITY (not adjudication coverage)

```text
potential ABSORBED:                 2,103  (92.5%)
potential LIQUIDATED:                  27
potential TRANSFORMED:                  0
potential other deregistration:         0  (DEREGISTERED_OTHER residual
                                          folded into unknown_exit)
conflicting:                          113  (84 multi-successor +
                                          26 merger-no-successor +
                                          3 renounced-with-merger)
unknown / insufficient evidence:       30
```

## DEVELOPMENT GOLD

```text
count:               460 cases
signature coverage:  39 / 39 (all rare signatures exhaustive;
                     all flagged, multi-successor, renunciation,
                     rectification, dissolution/liquidation combos;
                     era-stratified samples of common signatures)
fingerprint:         5bb54c14388c469f794b18907a840aed9af0846ab8422e08697ad4aa79e8d289
artifact:            docs/g9/taxonomy-development-gold.json
expected semantics:  source-grounded POTENTIAL_*/CONFLICTING/
                     INSUFFICIENT labels + successor where single-exact
```

## REGRESSION CORPUS

```text
count:        150 (era × signature stratified)
fingerprint:  3e2610f9166562be3941c71859a25f4add79371e53aa588c7311f39e9decac6f
artifact:     docs/g9/taxonomy-regression-manifest.json
overlap:      gold 0 · holdout 0
confirmed not used for taxonomy design: TRUE
```

## HOLDOUT

```text
count: 250 · touched: 0 (no acquisition, no links, no profiles,
no gold/regression inclusion — verified in code paths)
```

## DETERMINISM

```text
profile fingerprint:      8add87b7…c423 (rebuild = identical)
participants fingerprint: 65a0a6d7…e379
ledger fingerprint:       e2997ce6…8721 = G9-B unchanged
candidates fingerprint:   e1ab53d3…e54  = G9-A2 unchanged
offline rebuild:          PASS (export derives only from stored bytes)
second run:               identical fingerprints
```

## REGRESSION

```text
tests:   323 passed (11 new participant/profile tests incl. multiparty,
         absorber-subject execution, entity-context linking,
         multi-successor conflict, signature invariance, conservation)
ruff:    clean
mypy:    clean
G1–G8:   unchanged (no shared code touched)
G9-A2:   candidates fingerprint unchanged
G9-B:    ledger fingerprint unchanged
```

## G9-C VERDICT

**PASS** — all gates met:

```text
profiles 2,273/2,273 · conservation PASS · provenance 100%
holdout touched 0 · signatures measured (39, top-10 = 96.6%)
conflicts measured never resolved · corrections measured
taxonomy axes frozen separately · decorative values dropped/deferred
dev gold frozen (460, all signatures) · regression frozen (150, unused)
determinism PASS · G9-A2/G9-B fingerprints unchanged
```

## NEXT EXECUTABLE STEP

G9-E adjudication-rule preregistration and implementation against
development gold; validate once on frozen regression corpus; only
afterwards unlock blind holdout.
