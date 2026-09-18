# G3 — OSS reuse review (FONDMENS)

Retroactive per-milestone reuse review, per the project operating
principle: **reuse-first, build-last**. Every candidate was inspected at
code level, not README level. Classification vocabulary:

`REUSE_DIRECTLY` | `ADAPT` | `PORT` | `REFERENCE_ONLY` | `REJECT`

## Candidates

| Candidate | License | FONDMENS coverage | Verdict |
|-----------|---------|-------------------|---------|
| `EidoAut/Aletheia` — `CnmvIicParser.cs` | MIT | `ParseMonthlyNavs`: VLDiario only, single-ISIN lookup | **REFERENCE_ONLY** |
| `jcmoro/ticker-lab` — `apps/cnmv-go/parser.go` | own repo | `ParseMens`: all 3 metrics, streaming | **REFERENCE_ONLY** |
| `afernandez119/cnmv_data` | unclear | none — PDF quarterly-report scraper | **REJECT** (different surface) |
| `delaosash/cnmv-funds` | none visible | none — PDF report scraper, tabula-py | **REJECT** (different surface) |
| `qumundo/funds` | "All rights reserved" | none — commercial data-service client | **REJECT** (license + surface) |
| `mcanet/cnmv-parser` | none visible | none — company-registry scraper, 6 commits | **REJECT** |
| `Alvaru89/final_project_CNMV` | unclear | none — web-scraped fund pages | **REJECT** |
| `antikas/open-investment-model` | MIT | none — conceptual entity model | **REFERENCE_ONLY** (G-later naming) |
| `marcosagni98/cnmv-xbrl` | MIT | none — XBRL Circular 4/2008 statements | **REFERENCE_ONLY** (evaluate at G4) |
| `fundsxml_schema`/`examples` | spec | none — EU fund-data standard | **REFERENCE_ONLY** (export milestone) |

## Contract gaps found in the two real implementations

Both surviving candidates validate several of our measured rules but fail
the G3 contract:

**Aletheia `ParseMonthlyNavs` (C#)**
- Parses `VLDiario` only — 1 of 3 metrics.
- Single-ISIN lookup, not a whole-file ledger.
- `value <= 0 → skip`: zero *and* negative dropped silently — no state,
  no raw preservation.
- Malformed numerics silently skipped (conflated with absent).
- Missing `VLDiario` block indistinguishable from "class absent".
- No regulatory keys, no provenance, no registry join, no dedup check.
- Confirms independently: impossible-day rejection (`DaysInMonth`),
  zero-as-absence, no interpolation, DTD-off + doc-size cap (the XML
  hardening patterns already credited in NOTICE.md).

**ticker-lab `ParseMens` (Go)**
- All 3 metrics, streaming decoder, correct `daysInMonth` rejection.
- `float64` for VL/patrimonio — violates the Decimal contract
  (30.4632 is not representable exactly).
- `VLDiario[day] == 0 → skip whole row`: couples metrics — the 90 live
  cells with VL=0 but participes≠0 would lose real investor data.
- `strconv` errors ignored → malformed values silently become 0
  (conflated with sentinel).
- ISIN-only rows — `NumeroClase` parsed but dropped; no
  `share_class_key`, no provenance, no states, no `missing` vs
  `sentinel` distinction, absent-ISIN classes dropped entirely.
- Confirms independently: three-metric model, impossible-day rejection,
  zero-as-skip, `NUMERIC(20,6)/(20,2)/BIGINT` ≈ our
  `decimal(38,4)/(38,2)/int64` sizing.

## Discrepancy found (worth recording)

`ticker-lab/docs/cnmv-integration.md` states *"Días no hábiles llevan
valor 0"* — non-business days carry zero. **Falsified by measurement**:
2025-12 values vary on weekends (FI:9:0:1: 30.4632 → 30.4786 across Sat–Sun),
and a whole-file scan found **zero interior zeros** across ~2.6M cells.
`0` is a boundary/no-observation sentinel, not a non-business-day marker.
The Go code's actual behaviour (skip any `0`) is consistent with our
measured semantics, not with that doc note.

## Outcome

Own adapter stands — no candidate met the contract (3 metrics ×
per-metric states × verbatim raw × share-class keys × registry join ×
row-level provenance × fail-closed structure). The missing step was this
review itself, now recorded. Independent convergence on impossible-day
rejection, zero-as-absence and column sizing strengthens confidence in
the measured contract (`docs/g3/contract.md`).

## Rule going forward

Per-milestone reuse review is a **gate**: before any new component, list
candidates, inspect code, classify, and record the table in
`docs/gN/oss-review.md`. `REFERENCE_ONLY`/`REJECT` are legitimate
outcomes — the review exists to prevent both blind reinvention and blind
reuse.

G4 pre-registration: evaluate `marcosagni98/cnmv-xbrl` (MIT, Python,
Parquet exports, share-class/NAV-variation domain models) and any
FONDTRIM processors before writing the FONDTRIM adapter.
