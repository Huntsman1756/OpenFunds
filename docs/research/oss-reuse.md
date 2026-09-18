# OSS landscape & reuse assessment

Inspected by cloning and reading code, not READMEs. Clone depth=1, 2026-09-17.

## Repository assessment table

| Repo | License | Last activity | Lang | Purpose | Verdict |
|---|---|---|---|---|---|
| fundsxml/schema | MIT | 2026-08 (active) | XSD | FundsXML 4.x schema family (fund static/dynamic data, portfolio, regulatory reporting incl. EMT/EET/EFT/PRIIPs/SolvencyII, country packs) | REFERENCE_ONLY / export target |
| fundsxml/examples | Apache-2.0 | 2026-08 (active) | Java/C#/JS/Python/SQL | Examples: positions XML, DB import/export DDL (oracle/pg/sqlserver), JSON binding, Schematron checks | REFERENCE_ONLY — useful for export-format design + DB mapping patterns |
| qumundo/funds | **Proprietary** ("© Qumundo e.K. All rights reserved", no license grant) | 2026-06 | JS | Client for Qumundo commercial fund/ETF data API | DO_NOT_USE — not OSS despite public repo; example.json shows commercial product scope only |
| jcmoro/ticker-lab | **No LICENSE** (all rights reserved) | 2026-05 | Go/TS | Personal dashboard; `apps/cnmv-go` = working CNMV monthly ingest (HTML token scrape, zip, streaming XML, Postgres) | REFERENCE_ONLY — proves mechanics (endpoints, token scrape, real volumes); **cannot copy code**; scope = FONDMENS/FONDREGISTRO only, drops unknown elements silently, no XSD check, no provenance |
| EidoAut/Aletheia | **MIT** | 2026-09 (active) | C#/.NET | Analytics app with genuinely hardened CNMV provider (`CnmvIicProvider.cs`, `CnmvIicParser.cs`, `LocalProviderCache`, `DatasetFingerprintCalculator`, `FundDataProvenance`) | ADAPT — best-in-class patterns for parser security + provenance; C# code not directly reusable if we choose Python |
| delaosash/cnmv-funds | No LICENSE | 2020 | Python 2 | Scrapes *PDF* quarterly reports (tabula/PyPDF2) into per-security aggregation | DO_NOT_USE — PDF text scraping, wrong format, dead, no license |
| afernandez119/cnmv_data | No LICENSE (PyPI `cnmv-data` 1.0.0) | 2021 | Python | PDF portfolio table extraction (PyMuPDF) | DO_NOT_USE — same reason |
| antikas/open-investment-model | MIT | 2026-09 (active) | MD/JSON/TS | OpenIM — canonical entity model for investment firms (86 entities, FIBO alignment, legal-entity master w/ roles) | REFERENCE_ONLY — terminology source for canonical model |
| marcosagni98/cnmv-xbrl | MIT | 2026 (v1.0.2 on PyPI) | Python | Parses CNMV **XBRL** "información financiera intermedia" (different surface: per-entity financial statements) | ADAPT — Python prior art on CNMV structures; different dataset (XBRL estados vs. FOND*/SOC* dissemination XML) |
| Alvaru89/final_project_CNMV | (coursework) | ~2019 | Python | HTML scraping of CNMV fund pages → streamlit comparator | DO_NOT_USE |

## What Aletheia contributes (patterns worth porting)

`CnmvIicProviderOptions` + `CnmvIicProvider` implement nearly the exact
hardening checklist required:

- HTTP: 30 s timeout, ≤5 manual redirects, 64 MB payload cap, streamed read with
  byte counter, identifiable User-Agent.
- Payload validation by role (index HTML vs monthly ZIP): content-type check,
  ZIP magic (`PK\x03/\x05/\x07`), HTML-lookalike rejection, "final URI bounced to
  index page" detection.
- ZIP: ≤64 entries, ≤24 MB/entry, ≤64 MB total, ≤100:1 compression ratio,
  expected-entry check (`FONDMENS` must exist).
- XML: `DtdProcessing.Prohibit`, `XmlResolver=null`, `MaxCharactersFromEntities=0`,
  `MaxCharactersInDocument=20M`.
- Provenance: `FundDataProvenance` (provider, timestamps, requested/final URI,
  source reference string, point counts, SHA-256 fingerprint of output series),
  `LocalProviderCache` keyed by provider+URL with TTL.
- Robust month-name resolution incl. ES/CA/GL/EU/EN variants — the listing page
  is localized.

Weaknesses vs our goals: NAV-scope only (no FONDCART/FONDDERI/FONDTRIM), loads
whole XML into DOM (fine at 15 MB, less fine for 55 MB SOCCART — still OK),
drops unknown elements silently (`XDocument.Elements` selects known names),
no XSD validation, no artifact ledger, provenance is per-query not per-row.
License MIT → code may be adapted with attribution; if we build in Python we
port the *pattern*, not the code.

## What ticker-lab contributes (evidence, not code)

- Confirms tokenized URL mechanics, `?ejercicio=` year selector (their code uses
  `?ano=`; empirically `ejercicio` is what the live page emits — both observed,
  `ejercicio` verified).
- Confirms VL_DiaN=0 = non-trading day; ISIN as public key;
  `(Tipo, NumeroRegistro, Compartimento, Clase)` as natural key.
- Measured volumes (Nov-2025): 1,441 entities, 3,112 ISINs, 15.3 MB FONDMENS.
- No license → cite findings, write our own code.

## FundsXML / openfunds relationship

- FundsXML (MIT schema + Apache-2.0 examples): rich export/interop target.
  `FundsXML4_PortfolioData.xsd` covers positions; EET/EMT include files cover
  regulatory reporting. Use as **export adapter**, never internal model.
- openfunds.org: field-dictionary standard (OF-IDs), CC BY-ND 4.0 —
  **referencable but not adaptable** (NoDerivatives). Its existence is the
  main naming conflict for "OpenFunds ES" (see ADR-006).
- FinDatEx EMT/EET/TPT: European templates; TPT (tripartite template) is the
  closest industry analogue for holdings exchange. Semantic alignment is a
  mapping exercise, not a dependency.

## Gap conclusion (H4)

No existing OSS project provides a historical, provenance-preserving,
position-level ledger of Spanish IIC portfolios. Closest: Aletheia (NAV only),
cnmv-xbrl (XBRL estados, different surface), PDF scrapers (fragile, dead,
unlicensed). H4 SUPPORTED.
