# AGENTS.md

## Project state

G1 vertical slice **implemented and verified live**:
`cnmv-iic update --period 2012-03|2025-12` runs acquisition → artifact →
FONDCART → Parquet end-to-end against real CNMV. 27 unit tests, ruff and
mypy clean. Name: `cnmv-iic` (import `cnmv_iic`) — **not** "OpenFunds ES"
(openfunds.org collision, ADR-006).

Next gates (post-G1, not started): FONDMENS/FONDTRIM/FONDREGISTRO adapters
(share-class ISIN lookup needs FONDREGISTRO), FONDDERI verbatim records,
portfolio-diff only after cadence semantics formalized (Q/Q ≤2022, H/H ≥2023).

## Verified environment facts
- Windows, Python 3.11+ (uv-managed venv shadows system python — install
  with `python -m pip`, not bare `pip`).
- Console is cp1252 — no non-ASCII outside Spanish accents/dashes in CLI
  output (`≤`, `→`, `∪` crash help text).
- PyPI HTML endpoints return 200 for everything through this network — use
  `pypi.org/pypi/<name>/json` for existence checks.

## Verified CNMV facts (do not rediscover)
- Index page: `portal/Publicaciones/Descarga-Informacion-Individual.aspx?ejercicio=YYYY&lang=es`;
  links are opaque tokens `webservices/verdocumento/ver?e=…`, month via `title`.
- Full 11-family set only in quarter months ≤2022; only June+December from 2023.
- XSDs byte-identical 2012→2025; real instances deviate — registry in
  `src/cnmv_iic/schemas/registry.py` (CodigoISIN absent on deposits,
  masked XXXXXXXXXXXX, Divisa absent on 17 positions in 2012-03 only).
- FONDCART real structure: `FondCart/FechaDatos(YYYYMM)/Entidad(Tipo,
  NumeroRegistro)/Compartimento(NumeroCompartimento)/InversionesFinancieras(
  ClaseIF, DescripcionIF, CodigoISIN?, DescripcionValor, Divisa?, ValorMercado)`.
- ValorMercado is always dot-decimal scale-2; DescripcionIF has 12 labels,
  only `Depositos` is cash.

## Rules
- `.research/`, `data/`, `.tmp-live/` are local-only, gitignored, never
  published. No CNMV raw bytes in the repo; tests use synthetic fixtures.
- Fail-closed on unknown elements/XSDs; OBSERVED vs DERIVED discipline per
  `docs/architecture/provenance.md`.
- Decimal only for source values; derived fields kept separate.
- Verification: `pytest tests/ -q`, `ruff check src tests`, `mypy src`;
  live check: `python -m cnmv_iic.cli update --period <YYYY-MM> --data-dir .tmp-live`.
