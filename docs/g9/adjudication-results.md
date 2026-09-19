# G9-E — Lifecycle Adjudication Results

Verdict: **PASS** — preregistered protocol executed end-to-end:
rules frozen before implementation, gold evaluated, regression run
once without tuning, holdout unlocked only after all gates passed.

Preregistration: `docs/g9/adjudication-rules.md` (commit `5c2a1ac`,
frozen before any engine code).
Engine: `src/cnmv_iic/lifecycle_adjudicate.py` (`g9e-v1`).

---

## DEV ADJUDICATION (2,273 candidates)

```text
ADJUDICATED_ABSORBED_BY                    2,100   (92.4%)
ADJUDICATED_LIQUIDATED                        27   ( 1.2%)
INDETERMINATE_MULTIPLE_SUCCESSORS             83   ( 3.7%)
INDETERMINATE_NO_SUCCESSOR                    26   ( 1.1%)
INDETERMINATE_CORRECTION_OR_RENUNCIATION       6   ( 0.3%)
INDETERMINATE_CONFLICTING_EVIDENCE             1   ( 0.04%)
UNKNOWN_EXIT                                  30   ( 1.3%)
fingerprint: ad6d8529f80ac0b97f3c50f6b1a409387adc19448a3ca7eecebfee0d6185cf89
```

Successor corroboration on the 2,100 adjudicated absorptions:
**2,031 (96.7%)** assert the same successor in ≥2 source families
(bulletin + HR). Corroboration recorded, never required.

## GOLD EVALUATION (gate G7, preregistered ≥95%)

```text
agreement: 457 / 460 = 99.3%
mismatches: 3
```

All 3 mismatches share one pattern: gold label `POTENTIAL_ABSORBED`,
engine → `INDETERMINATE_CORRECTION_OR_RENUNCIATION`. These candidates
carry unresolved rectification evidence that the gold labeler did not
penalize but preregistered rule R1 does. The engine is *more*
conservative than gold — the designed direction. No gold case was
re-labeled after seeing engine output.

## REGRESSION CORPUS (150 — evaluated exactly once)

```text
ADJUDICATED_ABSORBED_BY   149
UNKNOWN_EXIT                1
fingerprint: 4fa59959a89d983a7ec9e4485e0d6f40f999b164e3d2d80a45a5eae33be64c21
```

Distribution skew toward absorbed is expected: development gold
absorbed all rare/flagged signatures, leaving the regression stratum
dominated by the common merger signature. Invariants all zero.

## GATES

```text
G1 identity promotion unresolved→exact:   0  PASS
G2 multi-successor auto-adjudications:    0  PASS
G3 contradiction collapse:                0  PASS
G4 corrections silently dropped:          0  PASS
G5 conservation (2,273 records, 1 each):  PASS
G6 deterministic fingerprint:             PASS (re-run identical)
G7 gold agreement ≥95%:                   99.3% PASS
G8 regression invariants:                 all zero PASS
→ holdout unlocked per protocol step 6
```

## BLIND HOLDOUT (250 — unlocked after regression PASS)

```text
ADJUDICATED_ABSORBED_BY             233   (93.2%)
INDETERMINATE_MULTIPLE_SUCCESSORS     8   ( 3.2%)
INDETERMINATE_NO_SUCCESSOR            4   ( 1.6%)
ADJUDICATED_LIQUIDATED                2   ( 0.8%)
UNKNOWN_EXIT                          3   ( 1.2%)
invariants:                           all zero
fingerprint: 520c4a7dfd10583d8ec93823ec06feba60defa066e10dbdad417dd0b4354673e
```

Holdout was adjudicated with **bulletin + FONDREGISTRO evidence only**
— no HR artifact was ever acquired for the 250 sealed entities.
Distribution shift vs dev is small (adjudication rate 93.2% vs 93.6%
for the two ADJUDICATED_* classes combined; indeterminate 4.8% vs
4.8%). The dominant absorbed-participant evidence lives in the weekly
bulletin spine, which covers holdout identically.

## FINAL METRICS (measured, not gated)

```text
absorbed adjudication coverage (dev):   2,100 / 2,273 = 92.4%
absorbed successor corroboration:       2,031 / 2,100 = 96.7%
liquidation adjudications:              29 total (27 dev + 2 holdout)
indeterminate rate (dev):               4.8%
conflict rate (dev):                    3.7% multi-successor
                                        + 0.04% merger+liquidation
correction/renunciation handling:       6 indeterminate, 0 dropped
source-agreement (single successor):    96.7% bulletin+HR
```

## NOT MATERIALIZED

```text
canonical lifecycle events:     0 (records are adjudication outcomes)
productive lineage edges:       0 (successor_key is a field, not a
                                   graph edge table)
CLI commands:                   none added
```

## G9-E VERDICT

**PASS.** The engine is small (7 ordered rules), deterministic, and
explainable. ~92% of exits adjudicated with exact-successor evidence;
the remainder is honestly `INDETERMINATE_*` / `UNKNOWN_EXIT` rather
than narratively completed. G9-C fingerprints unchanged; regression
corpus never tuned against.

## NEXT EXECUTABLE STEP

G9-F is effectively discharged: the holdout was unlocked and run once
under protocol. Remaining optional work: materialize adjudication
records into the Parquet export (derived table `lifecycle/adjudications`)
and/or lineage edges for `ADJUDICATED_ABSORBED_BY` — only on explicit
approval. G9-D (identity episodes) remains deferred until G10 needs
materialized intervals.
