# G9-E — Adjudication Rule Preregistration

Status: **FROZEN before implementation** (protocol v1).

This document fixes, before any engine code runs, the complete
adjudication rules, precedence, conflict handling, and pass gates.
If the engine fails the gates, the correct output is `FAIL` or
`INCONCLUSIVE` — G9-C is never reinterpreted retrospectively.

## Inputs

Derived candidate evidence profiles (G9-C) over the G9-B
source-assertion ledger. The engine consumes profiles + their linked
assertions/participants only. No new evidence sources. No fuzzy
matching. No clocks.

## Output vocabulary (complete — no other labels allowed)

```text
ADJUDICATED_ABSORBED_BY
ADJUDICATED_LIQUIDATED
INDETERMINATE_MULTIPLE_SUCCESSORS
INDETERMINATE_NO_SUCCESSOR
INDETERMINATE_CONFLICTING_EVIDENCE
INDETERMINATE_CORRECTION_OR_RENUNCIATION
UNKNOWN_EXIT
```

Explicitly NOT emitted: `MERGED_INTO`, `TRANSFERRED_TO`,
`TRANSFORMED_INTO`, `ABSORBED_FROM`, any unlisted value.

## Frozen source rules

- `MERGER_EXECUTED` is NOT required for absorption adjudication
  (present in only 169/2,216 merger paths).
- Exact successor cardinality must be exactly 1 to adjudicate
  `ABSORBED_BY`. `>1` → never auto-resolved. `0` → never forced.
- bulletin + HR agreement on the same successor is recorded as
  corroboration metadata, never a precondition.
- `DISSOLUTION_AGREED` is not a liquidation signal (0 dev candidates
  linked). It contributes to conflict detection only.
- `identity_state=unresolved` never promotes to exact.
- Rectifications/renunciations are modifiers that can force
  INDETERMINATE — never decorative events, never deleted.
- Any merger + liquidation contradiction blocks adjudication; both
  evidences are preserved in the record.

## Rule precedence (evaluated in order, first match wins)

```text
R1  has_merger_renounced AND any other merger evidence
    OR has_rectification (unresolved correction chain)
    → INDETERMINATE_CORRECTION_OR_RENUNCIATION

R2  contradiction flag MERGER_PLUS_* (merger + dissolution/
    liquidation evidence on same candidate)
    → INDETERMINATE_CONFLICTING_EVIDENCE

R3  candidate_is_absorbed_participant AND |exact_successor_ids| > 1
    → INDETERMINATE_MULTIPLE_SUCCESSORS

R4  candidate_is_absorbed_participant AND |exact_successor_ids| = 1
    AND merger evidence (AUTHORIZED or REGISTERED or EXECUTED)
    → ADJUDICATED_ABSORBED_BY
    record: successor_key = FI:<the single exact successor>
    record: corroborated = successor asserted in ≥2 source families

R5  any merger evidence AND |exact_successor_ids| = 0
    → INDETERMINATE_NO_SUCCESSOR

R6  has_liquidation OR has_in_liquidation_marker
    (and no merger evidence survived above)
    → ADJUDICATED_LIQUIDATED

R7  otherwise → UNKNOWN_EXIT
```

Notes on precedence:

- R1 before R2: a renounced merger is a correction-state issue, not
  a generic conflict.
- R3 before R4: multi-successor can never reach adjudication.
- R4 requires the candidate to be an actual `ABSORBED` participant —
  merely appearing in merger-adjacent text does not qualify.
- `MERGER_AND_BAJA_NO_SUCCESSOR` flag routes through R5, not R2:
  merger+baja without successor is absence of evidence, not
  contradiction (baja is the disappearance act itself).
- `MULTI_SUCCESSOR` flag routes through R3 (its own label), not R2.

## Frozen thresholds

No coverage target. No accuracy threshold that could incentivize
tuning. The engine either satisfies the zero-invariants or fails.

## Preregistered gates

```text
G1  zero identity promotion: unresolved participant identifiers never
    appear as exact successor keys
G2  zero multi-successor auto-adjudications
G3  zero contradiction collapse (merger+liquidation never emits
    ADJUDICATED_*)
G4  zero silent dropping: every renunciation/rectification produces an
    INDETERMINATE_* outcome or is recorded on the adjudicated record
G5  conservation: every adjudicated candidate appears exactly once
G6  deterministic fingerprint: identical inputs → identical outputs
G7  dev gold agreement: engine outcome class matches gold expected
    class on ≥ 95% of gold cases (sanity gate against implementation
    bugs, not a tuning target)
G8  regression corpus evaluated exactly once; distribution reported;
    invariants G1–G6 must hold; no tuning after seeing results
G9  holdout unlocked only after regression PASS
```

Gold expected-class mapping:

```text
POTENTIAL_ABSORBED      ↔ ADJUDICATED_ABSORBED_BY
POTENTIAL_LIQUIDATED    ↔ ADJUDICATED_LIQUIDATED
CONFLICTING             ↔ any INDETERMINATE_*
INSUFFICIENT_EVIDENCE   ↔ any INDETERMINATE_* or UNKNOWN_EXIT
UNKNOWN_EXIT            ↔ UNKNOWN_EXIT
```

## Measured metrics (reported, not gated)

```text
absorbed adjudication precision (vs gold expected)
absorbed adjudication coverage
liquidation precision
indeterminate rate
conflict rate
correction/renunciation handling
source-agreement rate on adjudicated successors
```

## Execution order (exact)

```text
1. freeze this document            ← commit before engine code
2. implement engine
3. run on 460-case dev gold        → measure G7 + invariants
4. freeze engine version
5. run once on 150-case regression → invariants + distribution
6. if regression gates PASS: unlock 250-case holdout
7. run holdout once                → distribution vs dev shift
8. final adjudication + report
```

If any gate fails: STOP. Output FAIL/INCONCLUSIVE. No tuning.
