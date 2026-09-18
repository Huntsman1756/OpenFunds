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
