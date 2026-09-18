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
+ `invalid_identifier`). G3 FONDMENS **PASS** (`docs/g3/results.md`, tag
`g3-daily-pass`). G4 FONDTRIM + FONDPATRIMDISVAR **implemented and
verified live** (`docs/g4/contract.md` + `docs/g4/oss-review.md` +
`docs/g4/results.md`): quarterly class metrics, compartment patrimony,
cross-family reconcile, metrics/fees/official-returns/allocation CLI.
G5 FONDDERI **implemented and verified live** (`docs/g5/contract.md` +
`docs/g5/oss-review.md` + `docs/g5/results.md`): verbatim evidence
ledger — compartment derivative operations + explicit zero-operation
coverage, `derivatives` CLI, coverage reconciliation.
G6 portfolio change semantics **implemented and verified live**
(`docs/g6/contract.md` + `docs/g6/oss-review.md` +
`docs/g6/results.md`): published-snapshot diff with measured identity
matching, strict change vocabulary, unresolved ambiguous groups,
conservation checks; `portfolio-diff`/`position-history`/
`portfolio-history` CLI.
155 unit tests, ruff and mypy clean.
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

G4 semantics worth knowing (FONDTRIM + FONDPATRIMDISVAR, measured
contract docs/g4/):
- TRIM grain: `(share_class_key, period)` — class-level (clase 0 =
  fund-level). Compartment (`VocacionInversora`/`ClaseFondo`) and entity
  (`CodigoDivisaIIC`) attrs denormalize onto the class record.
- PDV grain: `(compartment_key, period)` — NO Clase elements; never
  create class rows from it. Two rigidly separate field families:
  monetary stock fields in `CodigoDivisaIIC`, and signed flow/result
  fields in % over average daily patrimonio (bridge-verified).
- `0` is a REAL observed value in TRIM/PDV (fees can be 0.00) — NO
  sentinel semantics (inverse of FONDMENS). Absent element = NULL.
- Fees may be negative (rebates observed); official returns may be
  negative. All kept verbatim signed.
- Monetary fields are in the CLASS currency (`CodigoDivisa`) for TRIM —
  NOT always EUR (USD classes exist). Never assume EUR.
- `official_return_*` = CNMV's non-annualized Rentabilidad — never a
  generic `return` column; `RatioTotalGastos` is NOT labelled TER.
- Rolling blocks T/T-1/T-2/T-3: absent sub-element = insufficient
  history (missing, not zero). Empty containers observed.
- `quarterly_fingerprint`/`patrimony_fingerprint` separate; G1/G2/G3
  fingerprints unchanged.
- `reconcile` is informational: match/diff/skipped_currency/
  skipped_missing; currency checked before comparing; equality never
  required. CREATE VIEW cannot bind parameters in DuckDB — period is
  regex-validated then interpolated.
- CLI: `metrics`/`fees`/`official-returns` are class-grained (fund keys
  fail closed); `allocation` accepts fund/compartment/ISIN → owner
  compartments.

G5 semantics worth knowing (FONDDERI, measured contract docs/g5/):
- Evidence ledger, NOT a normalization engine: store only what the
  source supplies. `subyacente`/`instrumento` are officially "campo
  texto no normalizado" — verbatim, never parsed into underlier/
  strike/expiry/counterparty.
- Grain: `(compartment_key, period)` — no Clase elements; same
  portfolio-owner universe as PDV.
- Official closed enums decomposed, not invented: `Descripcion` →
  `side` (obligacion/derecho) + `underlier_class` (renta_fija/
  renta_variable/tipo_de_cambio/otros); `Objetivo` → `objetivo`
  (cobertura/inversion/objetivo_concreto_de_rentabilidad).
- `importe_eur` = committed nominal in EUR, signed (negatives live —
  kept verbatim). NOT market value, NOT % flow.
- `representation` is per-row: `structured | partially_structured |
  verbatim_only`. All live rows are partially_structured — CNMV
  supplies facets, never machine-readable instrument identity. That is
  the honest ceiling; a CDM export would require inference we refuse.
- Zero-operation compartments are explicit coverage rows —
  `reported_no_derivatives`, not absent data.
- Reconciliation is coverage-level only: `Importe` vs PDV
  `ResultadosDerivados` (stock EUR vs % flow) = `not_comparable`;
  same verdict vs FONDTRIM and FONDCART. Declared, not hidden.
- External derivative models (FINOS CDM, Strata, FpML) are
  REFERENCE_ONLY — semantic oracle, never a runtime dependency or a
  mold the data must fit. QuantLib = NO_USE.
- CLI: `derivatives` accepts fund/compartment/ISIN → owner
  compartments; exposes `representation` + provenance per row.
  Deliberately no options/futures/swaps/underlying/delta verbs —
  CNMV doesn't supply those concepts authoritatively.

G6 semantics worth knowing (portfolio change, measured contract
docs/g6/):
- Periods are published snapshots, not quarters: `explicit_periods` or
  `adjacent_available_snapshots` (`--previous` = owner's latest
  available snapshot strictly before to_period, BUT it never
  silently skips a measured published snapshot — under the verified
  post-2023 June+December cadence it fails with
  `previous_published_snapshot_not_loaded=<period>`; outside the
  measured window it resolves dataset-local).
- Matching is two-phase: identity matching first, change
  classification second — never "value changed → same security".
- `positions.fund_key` IS the compartment key (FundIdentity includes
  numero_compartimento).
- match_state: `exact_identifier` (ISIN unique both sides),
  `exact_source_signature` (unique verbatim signature,
  identifier_authority=none), `unresolved` (ISIN duplicated
  in-portfolio — groups reported unpaired, NEVER summed).
- Descriptors are never match inputs (18-30% churn measured) — they
  are `source_metadata_changed` outputs.
- Change vocabulary is closed: added/removed/unchanged/
  market_value_changed/weight_changed/market_value_and_weight_changed/
  source_metadata_changed. NO transaction verbs — added does not
  mean bought, removed does not mean sold.
- Weight fields: `derived`; weight deltas: `derived_from_derived`.
  VM deltas: `observed_delta`. Decimal everywhere.
- Conservation reported per side: matched + added + unresolved_new =
  count(new) (and mirror) — `holds` flag, never force-fit.
- FONDDERI excluded from individual matching
  (`individual_position_diff: unavailable` — no authoritative
  cross-snapshot identity, G5). PDV variation attached as context —
  no causal attribution.
- `diff_fingerprint` = sha256 over canonical changes — same inputs,
  identical output.

Still out: issuer resolution, corporate-action inference,
look-through, calculated returns, rankings, web frontend, REST API,
FundsXML export, normalized/CDM derivatives.

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
