# FIRDS lifecycle — reference for future daily updates

Documented during G7-C0 even though G7-C only implements FULINS
snapshots. Sources: ESMA "Instructions on access and download of full
and delta reference data files", `esma-dm` delta_processor, `pyfirds`
model, and measurement of the 2026-09-12 files.

## File types

| Type | Content | Frequency |
|---|---|---|
| FULINS | Full snapshot of all active records | daily |
| DLTINS | Delta: records added/changed/terminated since previous snapshot | daily |

## Partitioning

`FULINS_<A>_<YYYYMMDD>_<NN>of<MM>.zip` — one or more parts per asset
letter A (CFI first char, ISO 10962):

```text
C collective investment   D debt      E equity    F futures
H rights/warrants         I options   J strategies O others
R referential             S swaps     (10 partitions total)
```

Completeness for a snapshot date = every part `01..NN` of every in-scope
asset letter, all sharing `<YYYYMMDD>`; the date is also declared inside
each XML at `RptgPrd/Dt` — prefer the in-file date.

G7-C scope decision: C,D,E,F,H,I,J,O extracted; **R,S excluded** —
OTC referential/swaps cannot appear as FONDCART holdings ISINs
(verified: 0 covered corpus ISINs outside C/D/E). Revisit if FONDDERI
identity resolution ever needs them.

## Record types

- FULINS records are plain `RefData` elements.
- DLTINS wraps records in `NewRcrd` / `ModfdRcrd` / `TermntdRcrd`
  (and a CANCELLED state in esma-dm's processor).
- Record identity = `ISIN × TradgVnRltdAttrbts/Id` (venue MIC) — the
  same ISIN appears once per venue; `TechAttrbts/RlvntTradgVn` is the
  reporting/reference venue and CAN differ from the record's venue.

## Termination & versioning

- `TradgVnRltdAttrbts/TermntnDt` marks a venue record as terminated;
  terminated records remain in FULINS (89% of 2026-09-12 records have
  one) — they are evidence, not noise.
- `TechAttrbts/PblctnPrd` (FrDt[/ToDt]) gives the publication window of
  the record itself.
- Reconstructing "as-of" state requires FULINS baseline + sequential
  DLTINS application keyed by ISIN×venue — NOT implemented in G7-C.
- `FrstTradDt`, `AdmssnApprvlDtByIssr`, `ReqForAdmssnDt` are additional
  dates preserved verbatim in evidence rows.

## Schema

Envelope `head.003`/`head.001` BizData; payload message
`auth.017.001.02` (`FinInstrmRptgRefDataRpt`), XSD
`auth.017.001.02_ESMAUG_FULINS_1.1.0.xsd`; ESMA's published usage
guideline is "FIRDS Reference Data XML Schema v1.2.1". Element paths
are namespace-agnostic in our parser (`{*}` wildcards) so a namespace
revision does not silently change semantics — a new `MsgDefIdr` would
be recorded as a new parser-visible version.

## `Issr` (field 5) semantics

Officially "issuer or operator of the trading venue identifier". For
instruments issued by the venue itself the LEI is the venue operator's.
For C-type (CIV) records it resolves to subfund-level FUND entities —
a different granularity than the GLEIF/ANNA umbrella mapping. Never
normalized to `isin_issuer_to_lei`; preserved verbatim as
`firds_field5_issuer_or_venue_operator`.
