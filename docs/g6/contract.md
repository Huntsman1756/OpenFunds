# G6 — Measured identity contract for portfolio comparison

Measured before designing `PositionMatch`. Source: real FONDCART
members across the research corpus (2012-03, 2014-03, 2016-03,
2018-03, 2020-03, 2022-03, 2023-06, 2025-12 — FONDCART absent in
2024-03 / 2025-03, cadence as documented in G0).

## 1. Identifier states per snapshot

`CodigoISIN` classified by the existing `IsinState` taxonomy
(`valid | masked | invalid | absent`):

| Period   | rows    | portfolios | valid   | absent | masked | invalid |
|----------|--------:|-----------:|--------:|-------:|-------:|--------:|
| 2012-03  | 59,748  | 2,299      | 56,215 (94.1%) | 3,526 | 0   | 7   |
| 2014-03  | 55,512  | 2,037      | 51,561 (92.9%) | 3,949 | 0   | 2   |
| 2016-03  | 60,885  | 1,800      | 57,541 (94.5%) | 3,338 | 0   | 6   |
| 2018-03  | 70,667  | 1,748      | 69,686 (98.6%) | 976   | 0   | 5   |
| 2020-03  | 76,011  | 1,696      | 75,553 (99.4%) | 457   | 0   | 1   |
| 2022-03  | 84,155  | 1,622      | 84,045 (99.9%) | 109   | 0   | 1   |
| 2023-06  | 89,659  | 1,712      | 89,503 (99.8%) | 145   | 10  | 1   |
| 2025-12  | 103,130 | 1,668      | 102,743 (99.6%)| 237   | 148 | 2   |

- `masked` (`XXXXXXXXXXXX`) appears only in the late era (2023-06: 10,
  2025-12: 148) — a real, growing state, never an identity.
- `absent` declines era over era (5.9% → 0.2%) but never disappears.
- `invalid` is rare everywhere (1–7 rows/period); kept verbatim with
  its state.

## 2. ISIN is NOT unique within a portfolio — measured

Duplicated **valid** ISINs inside the same compartment portfolio:

| Period   | portfolios w/ dup ISIN | rows in dup groups | same signature¹ | different signature¹ |
|----------|-----------------------:|-------------------:|----------------:|---------------------:|
| 2012-03  | 166 | 628 | 37  | 224 |
| 2025-12  | 150 | 1,098 | 101 | 305 |

¹ signature = (DescripcionIF, DescripcionValor, ClaseIF, Divisa)

Live examples show the duplication is structural, not noise:

```
FI:16:0  ES0000012098  'Deuda Publica Cotizada'  vs  'Adquisicion
                        Temporal Activos'        — bond vs repo leg
FI:63:0  ES0000012G26  'RENTA FIJA|DEUDA ESTADO' vs 'REPO|BANCO
                        INVERSIS'                — same ISIN, two roles
FI:50:0  ES0L02610092  same DescripcionIF, descriptor coupon differs
                        (2,010 vs 1,990)         — distinct lots
FI:94:0  ES05050470F3  three rows, same ISIN, differing coupon text
```

Contract consequence: **ISIN alone is not a row key.** Of valid rows,
98.2–99.4% have an ISIN unique within their portfolio (exact-matchable);
0.6–1.8% live in ambiguous groups that must not be silently collapsed,
summed (a repo + bond sum conflates instrument types), or paired by
position order.

## 3. Descriptors are unstable across snapshots — measured

Same `(portfolio, ISIN)` pairs present in both snapshots whose
`DescripcionValor` text differs:

| Transition          | common pairs | descriptor changed |  %   |
|---------------------|-------------:|-------------------:|-----:|
| 2012-03 → 2014-03   | 15,788       | 4,694              | 29.7 |
| 2014-03 → 2016-03   | 17,917       | 4,686              | 26.2 |
| 2016-03 → 2018-03   | 19,383       | 4,361              | 22.5 |
| 2018-03 → 2020-03   | 25,609       | 6,009              | 23.5 |
| 2020-03 → 2022-03   | 26,870       | 4,968              | 18.5 |
| 2022-03 → 2023-06   | 43,845       | 7,881              | 18.0 |
| 2023-06 → 2025-12   | 30,084       | 5,336              | 17.7 |

Causes are benign and varied: abbreviation drift (`ACCIONES|INDITEX`
→ `... C`), issuer renames (`GAS NATURAL` → `NATURGY ENERGY`),
category prefixes (`BONO|` → `RFIJA|`), coupon/maturity text updates.

Contract consequence: **descriptors can never be a match input**
(18–30% churn) — they are a change *output*
(`source_metadata_changed`).

Same-snapshot, same-descriptor → multiple ISINs: 549–910 descriptors
per period map to >1 valid ISIN — descriptor is not an identifier in
either direction.

## 4. Non-valid identifiers have no cross-signature reach — measured

Rows with `absent`/`masked`/`invalid` ISIN whose full verbatim
signature `(DescripcionIF, DescripcionValor, ClaseIF, Divisa)` appears
uniquely on both sides of a snapshot pair:

| Transition          | non-valid rows (a / b) | unique signature matches |
|---------------------|-----------------------:|-------------------------:|
| 2022-03 → 2023-06   | 108 / 153              | 3   |
| 2023-06 → 2025-12   | 150 / 305              | 4   |

Contract consequence: `exact_source_signature` matching exists but is
nearly empty in practice — it stays in the model with
`identifier_authority = none`, honest and rare.

## 5. The contract

```
PositionMatch
    match_state:
        exact_identifier        valid ISIN, unique in BOTH snapshots
        exact_source_signature  non-valid ISIN, byte-identical full
                                signature, unique on both sides
        unresolved              ambiguous identifier group OR no
                                authority to match on
    match_basis:
        exact_valid_isin | verbatim_signature | ambiguous_identifier |
        none
    identifier_authority:
        authoritative_identifier | none
```

```
PositionChange                    (only over matched pairs)
    ADDED_POSITION      present in later snapshot, absent earlier
    REMOVED_POSITION    present in earlier snapshot, absent later
    UNCHANGED_POSITION  all compared fields identical
    MARKET_VALUE_CHANGED | WEIGHT_CHANGED |
    MARKET_VALUE_AND_WEIGHT_CHANGED
    SOURCE_METADATA_CHANGED       identity-stable, descriptor/facet
                                  text differs — not an economic event
    IDENTITY_UNRESOLVED           grouped/ambiguous rows, reported
                                  with both sides' row counts
```

Forbidden vocabulary (never emitted): `BOUGHT SOLD INCREASED_STAKE
REDUCED_STAKE NEW_BUY EXIT NET_BUYING NET_SELLING NET_FLOW TURNOVER` —
the disclosure proves state difference only.

Weights are `derived` (computed from reported VM / reported total) and
`weight_delta` is `derived_from_derived` — provenance states preserved
two layers above the XML.

Derivatives (FONDDERI) are excluded from individual matching — G5
measured zero authoritative cross-snapshot instrument identity;
`individual_position_diff: unavailable` with explicit reason.

Conservation gate (only where identity is unambiguous):
`matched + added = count(new)`, `matched + removed = count(old)`;
ambiguous groups add `unresolved_old`/`unresolved_new` to the equation
— never "fixed" by heuristic.
