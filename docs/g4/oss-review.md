# G4 — OSS reuse review (FONDTRIM + FONDPATRIMDISVAR)

Per-milestone reuse review per the reuse-first protocol
(CONTRIBUTING.md). Candidates inspected at code level.

## Candidates

| Candidate | License | FONDTRIM / PDV coverage | Verdict |
|-----------|---------|----------------------|---------|
| `EidoAut/Aletheia` | MIT | none — REGISTRO + MENS only | **REJECT** (no coverage) |
| `jcmoro/ticker-lab` `cnmv-go` | own repo | none — `VocacionInversora` field marked "populated from FONDTRIM (later phase)" | **REFERENCE_ONLY** |
| `marcosagni98/cnmv-xbrl` 1.0.2 | MIT | none — XBRL Circular 4/2008 accounting statements, a different official file family | **REFERENCE_ONLY** |
| `afernandez119/cnmv_data` | unclear | none — PDF quarterly-report scraper | **REJECT** |
| `delaosash/cnmv-funds` | none | none — PDF scraper | **REJECT** |
| `mcanet/cnmv-parser` | none | none — company-registry scraper | **REJECT** |
| `Alvaru89/final_project_CNMV` | none visible | none — BeautifulSoup scraping of CNMV HTML fund pages (rentabilidad/fees as web text) | **REJECT** |
| `qumundo/funds` | "All rights reserved" | none — commercial API client | **REJECT** |

## Notes

- **cnmv-xbrl** is the closest conceptual neighbour (typed share-class /
  holdings / NAV-variation domain models, Parquet export, MIT, Python),
  but it parses the XBRL financial-statement taxonomy, not the FOND*
  dissemination XML. If a future milestone ever ingests CNMV XBRL
  accounting reports it becomes the primary reuse candidate — full
  code-level inspection required then, not now.
- No surveyed product has reusable FONDTRIM/PDV code. Commercial
  products (VETA and similar) consume FONDTRIM fields — evidence the
  surface matters, not reusable code.
- Generic infrastructure is already reused and unchanged: lxml (secure
  XML), Decimal, PyArrow, DuckDB, Typer, pytest/ruff/mypy. New code is
  strictly the CNMV semantic mapping.
- ISIN validation stays in-house: our ISO 6166 checkdigit is 20 lines,
  verified against ~6k real ISINs including 2 official check-digit
  errors; `python-stdnum` adds a dependency for no contract gain
  (REFERENCE_ONLY decision recorded).

## Outcome

Implement own adapters for both families, over the existing hardened
tooling. Contract evidence before any adapter: `docs/g4/contract.md`.
