# G3 — FONDMENS observed contract

Evidence-first inventory of real FONDMENS XML before adapter implementation.
Sources: four official CNMV artifacts (2012-03, 2025-03, 2025-04, 2025-12),
the `FONDMENS.xsd` shipped inside each ZIP, and the official explanatory
document `FONDMENS_Documento Explicativo.pdf` (Departamento de Estudios,
Estadisticas y Publicaciones, 27 April 2017).

## 1. Availability and structure

- FONDMENS is present in **every** sampled artifact (2012-03, 2025-03,
  2025-04, 2025-12). It is a **monthly** family, unlike the post-2022
  FONDCART cadence. Member names vary in case (`FONDMENS_201203.XML` vs
  `FONDMENS_202512.xml`).
- Root: `FondMens`; `FechaDatos` is `YYYYMM` (observed: `202512`).
- Hierarchy (verified identical in 2012 and 2025):

```text
FondMens
  FechaDatos
  Entidad
    Tipo
    NumeroRegistro
    Compartimento
      NumeroCompartimento
      Clase
        NumeroClase
        ISIN
        VLDiario            { VL_Dia1 .. VL_Dia31 }
        PatrimonioDiario    { Patrimonio_Dia1 .. Patrimonio_Dia31 }
        ParticipesDiario    { Participes_Dia1 .. Participes_Dia31 }
```

- Every `Compartimento` contains at least one `Clase`. There is no
  compartment-level daily data outside a `Clase` element.
- `NumeroClase = 0` is common (2,158 / 2,484 classes in 2012-03; 889 / 3,102
  in 2025-12). It carries **fund-level** reporting for funds without classes —
  the official doc's "a nivel de clase, compartimento o fondo, segun sea el
  caso". Clase 0 is a first-class share-class key, not an absence marker.

## 2. Official semantics (explanatory PDF)

- "Suministra informacion sobre el patrimonio, el valor liquidativo y el
  numero de participes para cada uno de los dias del mes."
- **VL and patrimonio are in EUR.** The doc warns they may not match FONDTRIM
  when the class currency is not EUR — a cross-source difference to document,
  not reconcile, in G4.
- Identifier fields "sirven para vincularse con FONDREGISTRO" — the join is
  officially intended.
- Universe: "todos los FI".
- Data comes from IIC communications; CNMV warns aggregate statistics may
  differ because of later corrections. The file is a snapshot, not a ledger
  of corrections.

## 3. Day numbering and month length

- Day elements are numbered 1..31 and **all 31 elements are present** when the
  block exists, regardless of month length.
- Day elements are optional in the XSD (`minOccurs="0"`) but in practice are
  serialized even for impossible days.
- April 2025 (30-day month): `VL_Dia31`, `Patrimonio_Dia31`,
  `Participes_Dia31` exist and contain `"0"`.
- **Contract rule:** `observation_date` is constructed deterministically as
  `FechaDatos` year-month + `DiaN` day-of-month, for N <= calendar month
  length. Elements for N > month length are impossible days: they are
  serialization padding, not observations, and are **rejected** (not emitted).

## 4. Zero sentinel semantics (measured, not assumed)

Evidence across 2025-12 (~2.6M day-values over 3,102 classes):

| Pattern                            | Classes |
|------------------------------------|---------|
| Interior zero (real-gap-like)      | 0       |
| Leading-zero series                | 12      |
| Trailing-zero series               | 4       |
| All-zero class                     | 137     |
| Missing blocks (all three absent)  | 12      |

- `0` appears **only** at series boundaries or across whole classes, never as
  an interior gap. Combined with the impossible-day zero, `0` is a
  **no-observation sentinel**, not a measured value.
- 2012-03 contains **zero** sentinel values at all — every class was fully
  observed. The sentinel pattern is a modern phenomenon (registered classes
  without activity).
- Zeros are **independent per metric**: 90 day-cells have VL=0 with
  participes != 0, 285 the inverse. Per-metric states are mandatory.
- The reason for absence (pre-launch, liquidation, reporting gap) is **not**
  stated in the source and must not be inferred.

## 5. Value domains

- VL: decimal, observed scale 0-4 (dominantly 4). `decimal128(38,4)` exact.
- Patrimonio: decimal, observed scale 0-2. `decimal128(38,2)` exact.
- Participes: always integer lexical form. `int64`.
- **Patrimonio can be negative**: FI:5904:0:1 shows a contiguous run of
  -0.88 .. -9.71 in 2025-12. Negative patrimonio is a real observed value and
  is preserved as `observed`, never reclassified.
- Dot decimal separator in all sampled periods; no thousands separators.

## 6. Key and coverage semantics

- 2025-12: 3,102 FONDMENS class keys; 0 duplicate keys; 0 duplicate ISINs;
  0 absent ISINs. Joined against same-period FONDREGISTRO: **0 orphans,
  0 missing**.
- 2012-03: 2,484 class keys; identical cleanliness.
- `(share_class_key)` is unique within a file; `(share_class_key,
  observation_date)` is therefore the canonical row key.
- `unresolved_registry_reference` remains necessary: coverage was perfect in
  the samples, but nothing in the contract guarantees it.

## 7. Row contract (canonical)

One row per `(share_class_key, observation_date)` for calendar-valid days:

```text
share_class_key, fund_key, compartment_key, share_class_isin,
observation_date, day_index,
nav / nav_raw / nav_state,
aum / aum_raw / aum_state,
investors / investors_raw / investors_state,
registry_state,
observed_period, source_artifact_id, source_sha256, member_sha256,
xml_locator, parser, parser_version
```

Metric states: `observed` | `source_zero_sentinel` | `missing` | `invalid`.
Clean columns (`nav`, `aum`, `investors`) are NULL unless `observed`; `*_raw`
preserves the verbatim lexical value. `registry_state` is `resolved` or
`unresolved_registry_reference`.

## 8. Explicitly out of scope for G3

No derived returns, no forward-fill, no NAV fabrication, no FONDTRIM
reconciliation, no portfolio-level interpretation. Participe/patrimonio data
is class-level operational data, not holdings.
