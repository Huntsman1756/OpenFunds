# Public API contract — v0.1

Status: **frozen baseline** for `cnmv-iic` 0.1.x.

This document defines what is supported as a public contract and what
is explicitly not. Anything not listed here is internal and may change
without notice.

## Compatibility contract

Every dataset and manifest carries `cnmv_iic.versions.contract()`:

| field | value at v0.1 | meaning |
|---|---|---|
| `package_version` | `0.1.0` | released code |
| `dataset_schema_version` | `1` | parquet layout + table set |
| `canonical_model_version` | `0.1.0` | entity/field semantics |
| `lifecycle_engine_version` | `g9e-v1` | adjudication rules — frozen |
| `lifecycle_parser_version` | `1` | assertion extraction |
| `lifecycle_rule_version` | `1` | rule ids R1..R7 |
| `parser_version` | `0.1.0` | source adapters |

A breaking change to any of these requires bumping that version or an
explicit migration. `g9e-v1` is immutable: any rule change produces
`g9e-v2`, never a silent modification.

## Supported module

```python
from cnmv_iic.api import open_dataset, Dataset, versions_contract
```

`open_dataset(path=None)` returns a read-only `Dataset` handle over a
local dataset directory (default: the standard data dir). All methods
return JSON-serializable dicts; all are offline and deterministic.

### Methods

| method | contract |
|---|---|
| `info()` | periods, row counts, quality states, lifecycle layer, fingerprints, compatibility |
| `versions()` | the compatibility contract above |
| `fund(key, as_of=None)` | registry record for FI/regnum/ISIN |
| `share_class(key, as_of=None)` | share-class record + fund context |
| `class_summary(key, as_of=None)` | observation coverage of a class |
| `funds_of_institution(role, register_number, as_of=None)` | `role`: `gestora`/`depositario` |
| `fund_events(from_period, to_period, fund=None)` | mechanical registry diffs — WHAT changed, never WHY |
| `holdings(identifier, as_of=None, exact=False)` | reported portfolio positions |
| `funds_holding(isin, as_of=None, exact=False)` | funds reporting a position — reported positions, never beneficial ownership |
| `portfolio_diff(identifier, from_period=None, to_period=None, previous=False)` | position-level diff |
| `position_history(identifier, isin)` | one position across periods |
| `portfolio_history(identifier)` | portfolio across periods |
| `nav/aum/investors(key, frm=None, to=None)` | daily observation series |
| `metrics(key, period)` / `fees(key, period)` | quarterly blocks (YYYY-MM) |
| `official_returns(key, from_period=None, to_period=None)` | CNMV-computed returns, verbatim |
| `allocation(identifier, period)` | patrimony allocation |
| `reconcile(period, tolerance=0.01)` | cross-family comparison — derived, equality never required |
| `issuer(isin)` | issuer-resolution verdict; conflicts carry full context |
| `issuer_evidence(isin)` / `lei_evidence(lei)` | raw evidence rows |
| `issuer_coverage()` / `issuer_conflicts()` | resolution surface |
| `funds_exposed_to(lei, period, include_positions=False)` | issuer exposure — reported positions |
| `lifecycle(entity_key)` | adjudication + derived ABSORBED_BY edges + full provenance |
| `predecessors_of(entity_key)` | funds adjudicated absorbed by this entity |

### Error behavior

- `cnmv_iic.errors.NotFoundError` — identifier cannot be resolved
  (`not_found`, `ambiguous`, `invalid_identifier`) or entity absent at
  the requested period.
- `cnmv_iic.errors.DatasetError` — dataset directory missing required
  tables/periods.
- No fuzzy lookup, no silent correction: identifiers resolve exactly or
  fail.

### Identifier forms

| form | example |
|---|---|
| fund key | `FI:4955` (entity type + CNMV register number) |
| compartment key | `FI:4955:0` |
| share-class key | `FI:4955:0:1` |
| ISIN | `ES0138841038` (exact, check digit validated) |
| CNMV register number | `4955` |
| issuer LEI | `959800…` (exposure queries) |

### Semantic boundaries (non-negotiable)

- Positions are **reported portfolio positions**, never beneficial
  ownership or look-through.
- `fund_events` are mechanical registry diffs; they never assert cause.
- `lifecycle` results are **engine conclusions** (`rule_id` +
  `engine_version` + evidence provenance), not observed source facts.
- Only `ADJUDICATED_ABSORBED_BY` produces lineage edges.
  `INDETERMINATE_*` and `UNKNOWN_EXIT` never produce edges.
- No single `effective_date` is invented; per-stage evidence dates are
  preserved.
- `identity_state=unresolved` never promotes to exact identity.
- `official_returns` are CNMV's own computed values, verbatim.

## Supported CLI surface

The CLI mirrors the API. See `README.md` for the full command list.
`cnmv-iic dataset-info` prints `info()`; lifecycle commands print
`lifecycle()`/`predecessors_of()`.

## Explicitly NOT supported (v0.1)

- Internal DuckDB view/table names — not a contract, may change.
- Direct parquet paths — layout may change within
  `dataset_schema_version`.
- REST/HTTP API — deferred until real usage justifies a thin layer.
- `SUCCESSOR_OF`/`PREDECESSOR_OF` stored edge types — inverse queries
  are computed at read time.
- Identity episodes — deferred (G10-A) pending a concrete query that
  cannot be answered without them.
