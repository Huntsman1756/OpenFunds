# ADR-006: Project name — `cnmv-iic` (not "OpenFunds ES")

Status: Proposed · Date: 2026-09-17

## Context
"OpenFunds" collides with openfunds.org — an active, industry-backed
association and fund-data standard (CC BY-ND). "OpenFunds ES" would read as a
country chapter, create trademark/search confusion, and imply affiliation.

## Decision
Name: **cnmv-iic** (dist `cnmv-iic`, import `cnmv_iic`).

- Free on PyPI (JSON API verified 2026-09-17), zero GitHub collisions.
- Descriptive and accurately scoped: IIC = instituciones de inversión
  colectiva, the official CNMV term for what the files cover.
- Using "CNMV" descriptively follows existing PyPI precedent (cnmv-xbrl,
  cnmv-data).

## Alternatives
`openiic`/`iic-es` (free but "IIC" collides with I²C hardware; openiic≈kleros
openiico); `fondos-cnmv` (fine fallback); `cnmv-funds` (bland, dead-repo
collision).

## Consequences
+ No trademark shadow; honest scope signal.
− Less catchy; name is provisional pending user confirmation.
