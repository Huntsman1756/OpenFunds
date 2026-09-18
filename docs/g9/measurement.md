# G9-A measurement — observational fund lifecycle candidates

Executed: 2026-09-18 against `.tmp-live/dataset`.
Script: `.research/g9a_measure.py` → output `.research/g9a_measurement.json`.
Measurement fingerprint: `a441948a782502b2b9715f51d4ba19c56d558c9c98dbd3ad7335bb1c2f4d9909`

## 1. Registry snapshot inventory

```text
observed FONDREGISTRO periods:  4
    2012-03, 2025-03, 2025-04, 2025-12

expected monthly span:          166 months (2012-03 .. 2025-12)
missing expected months:        162
observation coverage:           2.4%
```

The local corpus is a four-point sample, not a continuous series.
Month continuity therefore cannot be validated beyond a single pair —
this is the dominant measurement constraint, not a code defect.

## 2. Adjacent observed pairs

| previous | current | contiguous | missing months | fund + | fund − | comp + | comp − |
|----------|---------|-----------:|---------------:|-------:|-------:|-------:|-------:|
| 2012-03  | 2025-03 | no         |            155 |    869 |  1,702 |  1,113 |  1,710 |
| 2025-03  | 2025-04 | **yes**    |              0 |      5 |      3 |      7 |      4 |
| 2025-04  | 2025-12 | no         |              7 |     52 |     89 |     60 |     98 |

Gap-bounded deltas are **observed bounds only — they are NOT
candidates** (contract §3 gap rule). In particular:

```text
2012-03 → 2025-03:  1,702 keys absent later / 869 keys present later
    These say "the 13-year gap contains turnover", nothing more.
    They must never be reported as disappearance counts.
```

## 3. Candidates (truly consecutive pairs only)

Exactly one contiguous observed pair exists: `2025-03 → 2025-04`.

```text
FUND_APPEARED       5
FUND_DISAPPEARED    3
```

FUND_APPEARED (first_observed_present = 2025-04):

```text
FI:5946  GVC GAESCO CONSCIOUS BUSINESS EQUITY FUND, FI
FI:5947  CAIXABANK DEUDA PUBLICA 2029, FI
FI:5948  FONDO NARANJA RENTABILIDAD 2027 II, FI
FI:5949  BANKINTER DEUDA PUBLICA 2029, FI
FI:5950  KUTXABANK RF HORIZONTE 25, FI
```

FUND_DISAPPEARED (last_observed_present = 2025-03,
first_observed_absent = 2025-04 — `effective_at` remains NULL):

```text
FI:4278  UNIFOND BONOS GLOBAL, FI            (UNIGEST)
FI:5724  SABADELL GARANTÍA FIJA 20, FI       (SABADELL AM)
FI:5790  SMARTECH, FI                        (SANTANDER AM)
```

All eight carry `evidence_state = observational_only`, deterministic
`candidate_id`, source artifact + XML locator provenance.
None of them is a lifecycle event — they are questions for G9-B.

## 4. Fund-key census

```text
distinct fund_keys ever observed:      3,232
left-censored (present at 2012-03):    2,306
right-censored (present at 2025-12):   1,438
present in ALL 4 observed periods:       587
```

Censoring is honest: a fund at the 2012-03 boundary may predate the
dataset; a fund at 2025-12 may persist beyond it.

## 5. Entity-type and compartment separation

```text
entity_types present in corpus:  FI only
```

FHF / SICAV / SHF strata cannot be measured locally — the four
available snapshots contain FI rows only. This is recorded as a
coverage fact, not an assumption that other types have no turnover.

Compartment deltas measured separately (never mixed into fund-level
denominators): see §2 `comp +/−` columns.

## 6. Stratified disappearance sample

Stratum = `gestora_denominacion`; all 3 candidates covered (sample size
3 of 3 — the candidate pool is the whole contiguous universe):

```text
FI:5724  SABADELL GARANTÍA FIJA 20   SABADELL ASSET MANAGEMENT
FI:5790  SMARTECH                  SANTANDER ASSET MANAGEMENT
FI:4278  UNIFOND BONOS GLOBAL      UNIGEST
```

## 7. Cross-reference — NOT EXECUTED

```text
weekly registry bulletin:      PENDING — source not acquired locally
hechos relevantes IIC:         PENDING — source not acquired locally
```

Both official surfaces are identified and viable (see
`source-review.md`) but no artifacts exist in the local store yet.
Acquisition is a G9-B prerequisite, not part of this measurement.

## 8. Honest reading

- The measurement infrastructure works end-to-end: contiguity
  detection, gap bounding, candidate emission, census, fingerprint.
- With only 1 of 165 expected adjacent pairs contiguous, the local
  candidate yield is 8 rows. The true 2012→2025 lifecycle surface is
  mostly unmeasured — **more FONDREGISTRO months must be ingested
  before G9-B adjudication has a meaningful workload**.
- Nothing in this output is a legal claim. `FUND_DISAPPEARED` means
  "absent at the next observed snapshot", and only that.
