# G8-R2/R3 — value-weighted issuer-resolution coverage (measured)

Position-row grain, `abs(reported_market_value)`. Live bundle
`dfe244f5`, adjudication `6a0d0f94`. The headline is the **inverse**
of the optimistic hypothesis: coverage by *value* is LOWER than by
ISIN count — the unresolved residual is value-concentrated.

## Coverage matrix — 2012-03

total 59,748 rows · €123.46bn abs · securities €113.47bn · cash €10.00bn

| bucket                  |   rows |      abs value | % all | % sec |
|-------------------------|-------:|---------------:|------:|------:|
| no_authoritative_match  | 35,337 | €98,479,974,889 | 79.8% | 86.8% |
| cash                    |  3,526 |  €9,998,921,560 |  8.1% |   —   |
| corroborated            | 15,174 |  €7,523,191,836 |  6.1% |  6.6% |
| firds_only              |  3,428 |  €4,135,469,661 |  3.4% |  3.6% |
| gleif_only              |  2,133 |  €3,181,386,640 |  2.6% |  2.8% |
| conflict                |    143 |    €143,225,200 |  0.1% |  0.1% |
| invalid_masked_no_isin  |      7 |      €2,354,982 |  0.0% |  0.0% |

```text
resolved/all 12.02% · resolved/security 13.08% · resolved/valid_isin 13.08%
corroborated/valid_isin 6.63%
(ISIN-count resolution for the same universe was ~29% — value is worse)
```

## Coverage matrix — 2025-12

total 103,130 rows · €434.61bn abs · securities €432.26bn · cash €2.34bn

| bucket                  |   rows |       abs value | % all | % sec |
|-------------------------|-------:|----------------:|------:|------:|
| corroborated            | 49,261 | €167,606,956,673 | 38.6% | 38.8% |
| firds_only              | 34,751 | €123,983,090,831 | 28.5% | 28.7% |
| gleif_only              |  2,094 |  €22,174,207,355 |  5.1% |  5.1% |
| no_authoritative_match  | 15,434 | €109,259,837,588 | 25.1% | 25.3% |
| conflict                |  1,203 |   €6,673,059,566 |  1.5% |  1.5% |
| invalid_masked_no_isin  |    150 |   €2,563,819,845 |  0.6% |  0.6% |
| cash                    |    237 |   €2,344,748,984 |  0.5% |   —   |

```text
resolved/all 72.20% · resolved/security 72.59% · resolved/valid_isin 73.02%
corroborated/valid_isin 39.01%   (single_source ≈ 34% — half of resolved
                                 value is one-source-only)
(ISIN-count resolution was ~86% — again value coverage is lower)
```

## By evidence strength (abs value)

| period   | corroborated | single_source | unresolved | invalid/masked | cash |
|----------|-------------:|--------------:|-----------:|---------------:|-----:|
| 2012-03  |  €7.52bn |  €7.32bn |  €98.62bn |  €0.002bn |  €9.999bn |
| 2025-12  | €167.61bn | €146.16bn | €115.93bn |  €2.56bn |  €2.34bn |

## Decomposition — what explains the unresolved residue

### 2025-12 unresolved (€115.9bn security value)

```text
by OpenFIGI securityType2:
  Mutual Fund      €47.37bn  (1,938 ISINs) — foreign share classes
  Govt             €33.92bn  (164)         — sovereign/sub-sovereign
  Corp             €24.86bn  (587)
  (no OpenFIGI)    €6.70bn   (733)
  Common Stock     €2.42bn   (525)

by CNMV descripcion_if (resolved % of each class):
  Deuda Publica <1año   29.4%    Renta Fija <1año   45.3%
  IIC (fund positions)  49.4%    RF No Cotizada     15.1%
  —vs— Renta Variable Cotizada 93.1% · RF Cotizada >1año 98.4%
       Deuda Publica >1año 99.4% · ATA repos 97.6%

by ISIN prefix:
  LU 28.1% resolved (0% corroborated — FIRDS-only source)
  IE 59.4% resolved (2.6% corroborated)
  ES 80.0% · XS 78.4% · US 97.3% · NL 99.8%
```

### 2012-03 unresolved (€98.6bn)

```text
by market_sector:
  Govt   €53.4bn (752 ISINs) — Spanish public debt dominates
  Corp   €32.2bn (2,588)
  (none) €8.0bn  (1,728)
  Equity €3.3bn  (925)

top unresolved ISINs are almost all Spanish Treasury:
  ES00000121H0 €2.14bn · ES00000122F2 €2.06bn · ES00000122R7 €1.78bn
  ES00000121P3 €1.27bn · ES0000012098 €1.21bn · ES0L01210191 €1.18bn …
```

**Structural finding**: the value gap is not diffuse — in 2012 it is
overwhelmingly Spanish public debt (Letras/Bonos/Obligaciones, ES
prefix, `Govt` sector) absent from BOTH GLEIF ISIN↔LEI and FIRDS
FULINS evidence; in 2025 it is foreign mutual-fund share classes
(LU/IE, `Mutual Fund` type, single-source at best) plus short-dated
public debt. Any future coverage improvement is a provider question,
not an adjudication question — G7 rules are already maximal.

## Per-owner conservation

0 violations across all owners both periods (see coverage-contract).

## Reverse traversal cardinality (measured, not implemented)

`issuer LEI → resolved ISINs → FONDCART rows → reporting funds`,
deterministic:

```text
2025-12 top issuers:
  9598007A56S18711AH60  €35.69bn  96 ISINs   784 funds
  815600DE60799F5A9309  €20.58bn 128 ISINs   358 funds
  969500KCGF3SUYJHPV70  €11.68bn  78 ISINs   249 funds
  529900AQBND3S6YJLY83  €4.69bn   74 ISINs   158 funds
  5493006QMFDDMYWIAM13  €2.55bn   49 ISINs   401 funds  (Santander)

2012-03 top issuer: same LEI 9598007A56… €1.30bn · 23 ISINs · 232 funds
```

The `funds-exposed-to --lei` query shape is viable; cardinality is
measured, no CLI yet.
