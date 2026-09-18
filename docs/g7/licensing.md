# G7 provider licensing — what each source permits

Distinctions matter: permission to use one artifact does not extend
to the provider's other products.

## GLEIF (G7-A, G7-B)

- ISIN->LEI relationship files, LEI-CDF, RR-CDF, Reporting Exceptions:
  **CC0** — public domain dedication; free to use, copy, redistribute.

## ESMA FIRDS (G7-C)

- FULINS/DLTINS reference data: public register data published under
  MiFIR/MAR transparency obligations; ESMA register terms apply.
  We store immutable copies for evidence and do not redistribute raw
  files (see ADR-005).

## OpenFIGI (G7-D)

- **FIGI identifiers**: expressly dedicated to the public domain —
  may be reproduced, redistributed, used commercially.
- **OpenFIGI returned descriptive metadata** (name, ticker,
  securityType, securityDescription, ...): reusable per OpenFIGI's
  published terms/FAQ — symbology data may be stored and shared
  without fees. We retain verbatim response payloads as evidence.
- **Other Bloomberg data**: NOT implied by this permission — the
  OpenFIGI terms cover OpenFIGI symbology only; nothing here licenses
  Bloomberg Terminal or Bloomberg data products.

## G7-F — software reuse BOM

Every OSS component the project depends on, classed by how it is used.
``copied_code`` means verbatim source vendored into the repo;
``adapted_code`` means a design/pattern re-implemented here.
REFERENCE_ONLY components were studied, never imported.

| component | version | license | used_as | copied? | adapted? | NOTICE required |
|---|---|---|---|---|---|---|
| DuckDB | >=1.1 | MIT | DEPENDENCY | no | no | no |
| PyArrow | >=15 | Apache-2.0 | DEPENDENCY | no | no | no |
| lxml | >=5 | BSD-3 | DEPENDENCY | no | no | no |
| Typer | >=0.12 | MIT | DEPENDENCY | no | no | no |
| httpx | >=0.27 | BSD-3 | DEPENDENCY | no | no | no |
| pyopenfigi (tlouarn) | reviewed 2026-09 | MIT | REFERENCE_ONLY | no | no | no |
| pyfirds / esma-dm | reviewed | MIT | REFERENCE_ONLY | no | no | no |
| Aletheia patterns | reviewed | MIT | REFERENCE_ONLY | no | no | no |
| Hypothesis | >=6.100 | MPL-2.0 | DEPENDENCY (dev) | no | no | no |
| pytest | >=8 | MIT | DEPENDENCY (dev) | no | no | no |
| ruff | >=0.5 | MIT | DEPENDENCY (dev) | no | no | no |
| mypy | >=1.10 | MIT | DEPENDENCY (dev) | no | no | no |

Transport for OpenFIGI is stdlib ``urllib`` (deterministic batch
composition, immutable ZIP artifacts, sha256, checkpoint/resume —
requirements pyopenfigi does not provide). No provider SDK is vendored.

## G7-F — legal decision matrix

What the project may do with each artifact class. Local computation and
CLI exposure of derived verdicts are low-risk; redistribution and public
API hosting of provider-originated data need care per-source.

| artifact class | compute locally | expose via CLI | redistribute dataset | host public API |
|---|---|---|---|---|
| CNMV disclosures (raw) | yes | no (ADR-005) | no | no |
| CNMV-derived fund tables | yes | yes | uncertain — legal review | uncertain — legal review |
| GLEIF CC0 artifacts (ISIN-LEI, LEI/RR-CDF, Repex) | yes | yes | yes (CC0) | yes (CC0) |
| ESMA FIRDS reference data | yes | yes | uncertain — register terms | uncertain — register terms |
| FIGI identifiers | yes | yes | yes (public domain) | yes (public domain) |
| OpenFIGI descriptive metadata | yes | yes | uncertain — OpenFIGI terms | uncertain — OpenFIGI terms |
| Adjudicated resolutions (ISIN->LEI verdict) | yes | yes | uncertain — embeds ESMA candidates | uncertain — embeds ESMA candidates |
| Aggregated issuer exposure (G8) | yes | yes | uncertain — REQUIRES_LEGAL_REVIEW | uncertain — REQUIRES_LEGAL_REVIEW |

Interpretation: the constraining term is ESMA register redistribution,
not GLEIF (CC0) or FIGI (public domain). Every ``uncertain`` row is a
deliberate non-claim — resolve with counsel before publishing a
downloadable issuer-exposure dataset or a hosted API. The software
itself (downloader + parsers + adjudication) carries no such
restriction: users obtain provider data under their own rights.
