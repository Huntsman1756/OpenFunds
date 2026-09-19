# G9-B — Official Lifecycle Source-Assertion Ledger

Verdict gate record for the productive evidence-ledger build.
Evidence only — no canonical lifecycle events were materialized.

Base congelada:

```text
G9-A2 PASS   commit 8213913
G9-B-R PASS  commit 6ee2a00

FUND_DISAPPEARED: 2,523
blind holdout:    250 — SEALED (post-G9-E unlock)
```

Source architecture (measured, unchanged):

```text
SPINE:      CNMV_WEEKLY_REGISTRY_BULLETIN   (2012-01 → 2026-05)
SECONDARY:  CNMV_IIC_RELEVANT_INFORMATION   (per-entity histories)
AUXILIARY:  FONDREGISTRO terminal denominacion markers
```

## SOURCE ARTIFACTS

```text
weekly weeks:        746  (week ids covering 2012-01 → 2026-05)
weekly docs:         746  (745 registro + 1 boletin_completo — week
                           7169 fallback worked as a general rule)
weekly failures:     0
HR entities queried: 2,273 eligible (250 sealed never queried)
HR artifacts:        2,593 (2,520 search/result pages + 73 history pages)
HR failures:         7 transient read timeouts — all recovered on retry;
                     final failed count = 0
HR attachments:      0 downloaded — verdocumento URLs preserved per
                     observation; event page itself is the raw artifact
FONDREGISTRO docs:   121  (one per funds partition)
```

## SOURCE OBSERVATIONS

```text
total:               78,216
bulletin:            68,170   (verbatim_only 20,556 — mostly non-FI
                               namespace content preserved, not dropped)
relevant information: 9,521   (all structured)
FONDREGISTRO markers:   525
```

## ASSERTIONS (27,643 total)

```text
OTHER_REGISTRY_ACT:                  8,573   (folleto/delegación/modificación)
OTHER_LIFECYCLE_ASSERTION:           5,468   (HR events outside lifecycle taxonomy)
DEREGISTRATION_RECORDED:             4,246
MERGER_REGISTRATION_RECORDED:        2,733
MERGER_AUTHORIZED:                   2,551
NAME_CHANGE_REGISTRATION_RECORDED:   1,909
MANAGER_SUBSTITUTION_REPORTED:         942
REGISTRY_NAME_IN_LIQUIDATION_MARKER:   503
DEPOSITARY_SUBSTITUTION_REPORTED:      218
MERGER_EXECUTED:                       197
REGISTRATION_RECORDED:                 120
MERGER_REGISTERED:                     110
REGISTRY_NAME_BAJA_MARKER:              20
LIQUIDATION_EXECUTED:                   15
DEREGISTRATION_REPORTED:                13
DISSOLUTION_AGREED:                      9
UNKNOWN_REGISTRY_ASSERTION:              9
RECTIFICATION_REPORTED:                  3
MERGER_RENOUNCED:                        3
TRANSFORMATION_RECORDED:                 1
```

Stages preserved verbatim: AUTHORIZED (2,551) ≫ EXECUTED (197) — the
13:1 asymmetry measured in G9-B-R is retained, never upgraded.

## IDENTITY

```text
subject exact_register_number:     21,695 assertions
subject unresolved:                 5,948  (recorded, never fuzzy-matched)
entity resolutions: EXACT_REGNUM_CORROBORATED 2,153 (94.7%)
                    DISCOVERY_ONLY               96
                    NOT_FOUND                    24
successor exact (merger rows):   2,201/2,273 dev candidates (96.8%)
successor object_identifier:     5,154 assertions with cnmv_register_number,
                                 109 with verbatim_name only
```

## DATES

```text
explicit asserted_date:          22   (2 EFFECTIVE_DATE +
                                       20 SOURCE_BAJA_MARKER_DATE)
publication/week only:       27,570   (asserted_date NULL — never
                                       backfilled from publication)
```

Matches the G9-B-R finding: explicit effective dates are essentially
absent (~0.1%); precision is registry-week (bulletin) / event datetime
(HR).

## CORRECTIONS

```text
rectifications preserved:     3  (correction_target_state=unresolved —
                                  no automatic 'closest previous' pick)
renunciations preserved:      3  (MERGER_RENOUNCED)
originals deleted:            0  (never)
```

## CANDIDATE LINKAGE

```text
EXACT_SUBJECT_REGNUM:   13,721 links covering 2,273/2,273 dev candidates
EXACT_OBJECT_REGNUM:     2,463 links covering   321 candidates
TEMPORAL_CONTEXT_ONLY:   0 (not materialized — proximity ≠ causality)
no evidence (dev):       0
```

## HOLDOUT

```text
linked:    0
inspected: 0
queried:   0   (sealed_skipped=250 recorded by the HR crawl)
```

The 250 sealed ids are absent from `candidate_links` — verified on the
exported parquet, not just in-memory.

## DETERMINISM

```text
candidates_fingerprint: e1ab53d318378849a1b59097cc55ec27ef5501ffa2a5d3a4517b0cccbffe7e54
ledger_fingerprint:     e2997ce6ec688322a584b6b6a1a897ece1ce222a699513d037807800287a8ff1
second rebuild:         identical fingerprints (two consecutive exports)
offline requests:       0 (export reads ArtifactStore + funds parquet only)
```

## REGRESSION

```text
tests:                 312 passed
ruff:                  clean
mypy:                  clean (37 source files)
G9-A2 candidates:      2,523 reproduced byte-identically (same
                       sha256 formula → same candidate ids; the
                       candidates table fingerprint is stable)
```

## SOURCE ASSERTION COVERAGE (dev = 2,273, holdout excluded)

Measured, not a threshold:

```text
any linked assertion:          2,273 / 2,273   100%
bulletin exact act:            2,267            99.7%
HR lifecycle assertion:        1,571            69.1%
merger-registration assertion: 2,189            96.3%
merger-authorization:          1,283            56.4%
merger-execution:                  0  linked (197 exist — subject is the
                                          absorbing entity, not the
                                          disappeared fund)
dissolution assertion:             0  linked
liquidation assertion:             1
exact successor:               2,201            96.8%
any explicit asserted_date:       17             0.7%
rectification linked:              0
renunciation linked:               2
FONDREGISTRO marker linked:       48
```

### By disappearance year

```text
        n    bulletin  HR     merger_reg  successor
2012   220    99.5%    82.3%    98.2%      98.2%
2013   275   100%      72.4%    97.1%      97.5%
2014   221   100%      59.3%    96.8%      96.8%
2015   268   100%      57.1%    98.9%      98.9%
2016   160   100%      70.0%    94.4%      95.6%
2017   179    98.9%    67.6%    98.3%      98.9%
2018   139   100%      69.8%   100%       100%
2019   105    99.0%    70.5%    96.2%      97.1%
2020   138   100%      70.3%    92.0%      93.5%
2021   115   100%      67.8%    96.5%      96.5%
2022    94    98.9%    74.5%    93.6%      93.6%
2023    87    98.9%    79.3%    94.3%      93.1%
2024    93   100%      69.9%    91.4%      92.5%
2025   126   100%      69.0%    92.9%      96.0%
2026    53   100%      69.8%    94.3%      96.2%
```

### By lifespan

```text
                        n     bulletin  HR     merger_reg  successor
single_observation       32   100%      87.5%    96.9%      96.9%
2-6 months              129   100%      77.5%    96.1%      96.9%
7-24 months             442    99.1%    73.5%    94.6%      95.0%
>24 months            1,670    99.9%    66.9%    96.8%      97.3%
```

## G9-B GATES

```text
raw document provenance              100%   PASS
observations with provenance         100%   PASS
assertions with provenance           100%   PASS
silent source-document loss            0    PASS
silent unknown-template coercion       0    PASS (verbatim_only kept)
fuzzy subject identity                 0    PASS
fuzzy successor identity               0    PASS
AUTHORIZED auto-upgraded               0    PASS
BAJA auto-upgraded to LIQUIDATED       0    PASS
holdout linked/inspected               0    PASS
offline rebuild                     PASS
deterministic fingerprints          PASS
G1-G8 fingerprint changes              0    PASS
G9-A2 measurement fingerprint          0    PASS (same candidates)
```

## UNEXPECTED FINDINGS

1. Comma-less FI names exist in bulletin tables ("GRANTIA PHOENIX FI
   5534") — the strict `, FI` evidence gate sent 52 real fund rows to
   OTHER_ENTITY_CONTEXT including 2 dev-candidate BAJAS. Fixed by
   admitting `FI <regnum>` and line-terminal `FI` evidence.
2. PDF font mojibake (`n�mero`) broke the regnum regex on a subset of
   documents — a tolerant `n.{0,2}mero` pattern recovered ~170 merger
   acts.
3. Fund names containing `FUSIÓN` ("UNICAJA AHORRO FUSIÓN, FI") and
   folleto updates "con motivo de la fusión" produced false
   MERGER_REGISTRATION acts — classification now keys on the act
   object nearest the verb, not keyword presence.
4. "Incorporar al Registro" is a real CNMV act verb (delegation/
   modification incorporations) — added to the verb set.
5. 197 MERGER_EXECUTED assertions exist but link to ZERO dev
   candidates — the executed event's subject is the absorbing entity.
   The absorbed fund's disappearance is evidenced by
   REGISTERED-stage acts; execution evidence enriches the successor,
   not the disappeared subject. Important input for G9-E.
6. `AUTHORIZED` ≫ `EXECUTED` (2,551 vs 197) holds in production
   exactly as measured — source stages are preserved, never upgraded.
7. Two FONDREGISTRO-style markers also appear in bulletin prose
   (denominación changes "con motivo de la apertura del periodo de
   liquidación") — kept as OTHER_REGISTRY_ACT/NAME_CHANGE evidence.
8. A slow-trickling CNMV response can stall `urllib` reads despite a
   socket timeout — `resp.read()` is now inside the transport try and
   per-entity acquisition is fail-closed (recorded, never aborts).

## VERDICT

```text
G9-B: PASS — all gates green; coverage measured.
Source assertions ≠ adjudicated events (by design).
```

## NEXT

G9-C: lifecycle-cause taxonomy measurement over this ledger
(incl. the 96 DISCOVERY_ONLY + 24 NOT_FOUND resolution residue, the
0-linked merger-execution asymmetry, and date-semantics gaps).
G9-E later: adjudication design on top of frozen assertion coverage.
