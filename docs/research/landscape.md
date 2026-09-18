# Landscape research log

## Search coverage

Executed searches (2026-09-17) over: GitHub repos (by name + by code/URL
patterns), PyPI, datos.gob.es, CNMV portal, openfunds.org, FundsXML,
FinDatEx-adjacent material, plus the mandated repository list. Concepts
searched: CNMV FOND*/SOC* filenames, "descarga información individual",
CNMV fund parsers (Python/Go), Spanish fund holdings datasets, FundsXML,
openfunds, EMT/EET/TPT, canonical fund/portfolio data models.

## Standards inventory

| Standard | Nature | Relevance |
|---|---|---|
| **CNMV FOND*/SOC* XML** | the actual source schema (XSDs ship inside each ZIP) | source of truth |
| **FundsXML 4.x** (fundsxml/schema, MIT) | industry XML for fund data exchange: static data, dynamic data (NAV), portfolio positions, regulatory reporting incl. country modules | export target + vocabulary reference; NOT the internal model (its granularity/semantics ≠ CNMV's) |
| **openfunds** (openfunds.org) | field dictionary (OF-IDs) for fund reference data; non-profit association founded by UBS/CS/JB/FE fundinfo; CC BY-ND 4.0 | terminology alignment reference; naming conflict for our project; ND clause forbids derivative dictionaries |
| **FinDatEx EMT/EET/TPT** | EU templates: EMT (MiFID target market), EET (ESG), TPT (tripartite holdings) | TPT is the nearest industry holdings format — optional later export; not needed for G0 |
| **CNMV XBRL taxonomy** | separate surface: per-entity intermediate financial statements (busqueda.aspx?id=12) | possible future second source; cnmv-xbrl (MIT) already parses it |
| **ISO 6166 ISIN / ISO 4217 currency / ISO 8601 dates** | validation primitives | use standard validators; flag invalid ISINs rather than fixing |

## Naming investigation

Provisional name "OpenFunds ES" **collides** with openfunds — an active,
industry-backed, registered standard whose name it would appear to derive from
("the openfunds for Spain"). Risks: trademark/association confusion,
search-engine ambiguity, implied affiliation, ND-license adjacency.

Candidate check (PyPI JSON API + GitHub search, 2026-09-17):

| Candidate | PyPI | GitHub | Assessment |
|---|---|---|---|
| openfunds, openfunds-es | free | — | REJECT: openfunds.org collision |
| openiic | free | kleros/openiico (crypto ICO dapp) + I2C-hardware repos | weak — "IIC" collides with I²C hardware everywhere; openiic≈openiico confusion |
| iic-es | free | only unrelated I²C repos | same I²C ambiguity, low discoverability |
| **cnmv-iic** | free | **zero conflicts** | descriptive, unambiguous domain signal, precedent exists (`cnmv-xbrl`, `cnmv-data` on PyPI) |
| cnmv-funds | free | delaosash/cnmv-funds (dead repo) | available but bland; slight collision w/ dead repo |
| fondos-cnmv | free | — | fine alternative |

Recommendation: **`cnmv-iic`** (importable, pronounceable, accurately scoped —
"IIC" is the official Spanish term for the entities covered). Python dist name
`cnmv-iic`, import `cnmv_iic`. See ADR-006.

## Hypotheses status snapshot

| H | Statement | Status | Evidence |
|---|---|---|---|
| H1 | Machine-readable instrument-level portfolio data suffices for useful snapshots | **SUPPORTED** | 103k positions 2025-12, ISIN 99.6%, MV+class+currency+issuer-text per position |
| H2 | Finite schema adapters cover history | **PROVEN (better than expected)** | one XSD generation, byte-identical 2012→2025 across all 11 families |
| H3 | Existing OSS reduces work substantially | SUPPORTED | Aletheia (MIT) gives the hardening+provenance pattern; nothing gives the portfolio ledger |
| H4 | No mature OSS already solves this | SUPPORTED | see oss-reuse.md |
| H5 | Gap = holdings history & cross-fund queries, not NAV search | SUPPORTED | product-gap.md |
| H6 | Publishable OSS without problematic data redistribution | LIKELY | ship downloader not data; bulk normalized release = legal review |
| H7 | Identity stable enough for history | SUPPORTED | (Tipo,NºRegistro,Compartimento,Clase) keys + ISINs + register numbers for institutions; names volatile |
| H8 | FONDCART ISINs sufficient for reverse queries | SUPPORTED w/ caveat | 99.6% 2025, ~94% 2012; masked/deposit exceptions documented |
| H9 | Derivatives representable without dangerous guessing | SUPPORTED w/ caveat | verbatim fields + Objetivo enum; no typed exposure |
| H10 | Parquet/DuckDB-class local stack suffices | SUPPORTED | ≤~4 GB raw, ~100k positions/period — workstation-scale |
