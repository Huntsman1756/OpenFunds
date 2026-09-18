# G5-R — OSS reuse review: FONDDERI

Per the reuse-first protocol (CONTRIBUTING.md): survey → code
inspection → classification, before any adapter code.

## CNMV FONDDERI parser candidates

| Candidate | Evidence | Verdict |
|-----------|----------|---------|
| EidoAut_Aletheia | `CnmvIicParser.cs` covers MENS/TRIM-adjacent files; **zero** FONDDERI coverage (grep-verified) | REJECT |
| jcmoro_ticker-lab | `cnmv-integration.md` lists FONDDERI as "Cartera de derivados" with a later-phase placeholder; no parser | REFERENCE_ONLY |
| mcanet/cnmv-parser | company-registry scraper, different surface | REJECT |
| afernandez119/cnmv_data, delaosash_cnmv-funds, Alvaru89, qumundo | PDF/web/API scrapers of other surfaces; no DERI coverage | REJECT |
| antikas_open-investment-model | fund data model, no CNMV ingestion | REFERENCE_ONLY |
| marcosagni98/cnmv-xbrl | CNMV XBRL accounting reports — different file family | REFERENCE_ONLY |

No mature FONDDERI parser exists in the surveyed space. As in G4, the
own-adapter decision holds — over reused generic tooling (lxml,
Decimal, PyArrow, DuckDB, Typer).

## External derivative-domain models (semantic oracles, NOT runtimes)

| Candidate | What it offers | Verdict |
|-----------|----------------|---------|
| **FINOS Common Domain Model** (Apache-2.0, v7.x) | Open standard for products, trades and lifecycle of derivatives incl. ETD activity; rich structured economic terms | REFERENCE_ONLY — expects attributes CNMV does not supply (typed underlier, expiry, strike, contract specs). Forcing `Instrumento` free text into `ExchangeTradedProduct` would be inference, not mapping. Kept as semantic oracle for a possible future `export --format cdm`. |
| **OpenGamma Strata** (Apache-2.0) | Consolidated product model + analytics/risk | REFERENCE_ONLY — pricing/risk is out of scope; the product model is useful vocabulary but cannot be populated inference-free from FONDDERI. |
| **FundsXML 4.x schema** (fundsxml.org) | `FutureType`, `OptionType`, `SwapType`, `WarrantType`, EMT instrument-type enums — mature fund-side derivative vocabulary | REFERENCE_ONLY — candidate target vocabulary for a future export; not a CNMV parser. |
| **FpML** | OTC derivative trade standard | REFERENCE_ONLY — FONDDERI reports positions/operations, not trade confirmations. |
| **QuantLib** | pricing/analytics engine | NO_USE — analytics and pricing do not belong to the ingestion ledger. |

## Consequence

`FONDDERI` will be modelled as an **evidence ledger**: every source
field preserved verbatim; closed enums typed as enums; the officially
"texto no normalizado" fields never parsed into derivative attributes.
External models are consulted only to know which concepts exist — never
to invent them.
