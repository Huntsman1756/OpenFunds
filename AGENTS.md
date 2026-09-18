# AGENTS.md

## Operating principles

- **Reuse-first, build-last** — per-milestone OSS review is a GATE:
  survey candidates, inspect code/license/tests, classify
  REUSE_DIRECTLY/ADAPT/PORT/REFERENCE_ONLY/REJECT in
  `docs/gN/oss-review.md` BEFORE writing the component (protocol in
  CONTRIBUTING.md). G3 review is at `docs/g3/oss-review.md`.
- Evidence-first, fail-closed, provenance-preserving; Decimal never
  float; no invented data; no silent inference.

## Project state

G1 holdings ledger **PASS** (tag `g1-holdings-pass`). G2 regulatory
identity **PASS** (`docs/g2/results.md`, tag `g2-identity-pass`, plus
post-adjudication tightening `4a208a6`: stale-fallback metadata + `--exact`
+ `invalid_identifier`). G3 FONDMENS **implemented and verified live**
(`docs/g3/contract.md` + `docs/g3/results.md`): daily NAV/AUM/investors per
share class with explicit observation states. G4 FONDTRIM **implemented**
(`docs/g4/contract.md`): quarterly class-level metrics — fees, official
returns, expense ratio, volatility. 90 unit tests, ruff and mypy clean.
Name: `cnmv-iic` (import `cnmv_iic`) — **not** "OpenFunds ES"
(openfunds.org collision, ADR-006).

G2 semantics worth knowing:
- Canonical keys: `fund_key=FI:9`, `compartment_key=FI:9:0`,
  `share_class_key=FI:9:0:1`. Compartment key = FONDCART portfolio owner —
  N classes share one portfolio, never duplicated.
- Resolution kinds: exact_share_class / exact_compartment / exact_fund /
  invalid_identifier / ambiguous / not_found. ISINs resolve only when
  `isin_state=valid`.
- Non-cadence months export registry+daily only (`fondcart_present:
  false`); `holdings` falls back to latest positions period <= as-of,
  honestly labelled via `stale`/`resolution_mode`; `--exact` disables it.
- `registry_fingerprint` covers identity tables; G1 `dataset_fingerprint`
  scope (positions+quality) is unchanged.

G3 semantics worth knowing:
- Grain: `(share_class_key, observation_date)` — FONDMENS is per-class,
  NEVER deduplicated to the compartment (inverse of the holdings rule).
- `'0'` = no-observation sentinel (boundary-only, measured; impossible
  days carry it too). Per-metric states: observed / source_zero_sentinel /
  missing / invalid; clean value NULL unless observed; `raw` verbatim.
- `observation_date` = FechaDatos month + DiaN for N <= month_length;
  impossible days rejected. Negative patrimonio is observed, not sentinel.
- `NumeroClase=0` = fund-level grain — a first-class key.
- `daily_fingerprint` is separate; G1/G2 fingerprints unchanged.
- No derived returns — official returns are FONDTRIM (G4).

G4 semantics worth knowing (FONDTRIM, measured contract docs/g4/):
- Grain: `(share_class_key, period)` — class-level (clase 0 = fund-level).
  Compartment (`VocacionInversora`/`ClaseFondo`) and entity
  (`CodigoDivisaIIC`) attrs denormalize onto the class record.
- `0` is a REAL observed value here (fees can be 0.00) — NO sentinel
  semantics (inverse of FONDMENS). Absent element = missing = NULL.
- Fees may be negative (rebates observed); official returns may be
  negative. All kept verbatim signed.
- Monetary fields are in the CLASS currency (`CodigoDivisa`) — NOT
  always EUR (USD classes exist). Never assume EUR.
- `official_return_*` = CNMV's non-annualized Rentabilidad — never a
  generic `return` column; `RatioTotalGastos` is NOT labelled TER.
- Rolling blocks T/T-1/T-2/T-3: absent sub-element = insufficient
  history (missing, not zero). Empty containers observed.
- `quarterly_fingerprint` separate; G1/G2/G3 fingerprints unchanged.

Next gates (G4-B..E): FONDPATRIMDISVAR own model (compartment-grained,
mixed monetary stock + signed %-over-PMD flow fields), joins/
reconciliation, CLI (metrics/fees/official-returns/allocation),
historical validation. Still out: FONDDERI, issuer resolution,
look-through, calculated returns, rankings.

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
- FONDREGISTRO ships in every monthly ZIP (incl. non-cadence months);
  structure `FondRegistro/FechaDatos/Entidad(Tipo, NumeroRegistro,
  Denominacion, ETF, Gestora, Depositario)/Compartimento(
  NumeroCompartimento, DenominacionCompartimento)/Clase(NumeroClase, ISIN,
  DenominacionClase)`. Share-class ISINs unique per period in samples.
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
