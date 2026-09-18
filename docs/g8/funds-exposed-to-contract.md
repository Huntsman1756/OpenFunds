# G8-1 — `funds-exposed-to` contract

First G8 query surface: issuer LEI → resolved ISINs → FONDCART
position rows → reporting portfolio owners. Implemented in
`cnmv_iic.query.funds_exposed_to`, exposed as
`cnmv-iic funds-exposed-to`.

## Invocation

```bash
cnmv-iic funds-exposed-to LEI --period YYYY-MM [--evidence MODE] [--positions] [--json]
```

- `LEI` — positional, 20-char ISO-17442 shape (`18 alnum + 2 digits`).
  Malformed input fails closed (`NotFoundError` → exit 1); a
  well-formed LEI with no attributed holdings returns an honest empty
  result, **not** an error.
- `--period` — required FONDCART period; must exist in the dataset.
- `--evidence` — `all-resolved` (default) | `corroborated` |
  `single-source`. Selects which resolution states enter
  `known_resolved_value`. Unknown values fail closed (`ParseError`).
- `--positions` — emits position-row detail.
- `--json` — stable JSON contract (Decimals serialize as strings).

## Traversal (exact keys only)

```text
FONDCART position-row            (position-row grain — never grouped by ISIN)
   ↓ isin_raw == security_resolution.isin   (version/bundle pinned)
security_resolution.resolved_lei == requested LEI
   ↓ fund_key
portfolio owner                  (FONDCART grain, e.g. FI:9:0)
   ↓ fund_key, period
FONDREGISTRO compartments + funds (SAME period — historical names)
```

No fuzzy matching, no name lookup, no look-through, no parent
aggregation, no manager aggregation, no share-class expansion.

## What enters `known_resolved_value`

| state                  | included? | bucket                  |
|------------------------|-----------|-------------------------|
| `corroborated`         | yes       | `corroborated_value`    |
| `gleif_only`           | yes       | `gleif_only_value`      |
| `firds_only`           | yes       | `firds_only_value`      |
| `conflict`             | no        | —                       |
| `multiple_candidates`  | no        | —                       |
| `no_authoritative_match`| no       | —                       |

`single_source_value = gleif_only_value + firds_only_value` — the two
remain distinguishable; the filter only changes which buckets feed
`known_resolved_value`.

`known_resolved_value` is the **absolute** sum (`Σ|ValorMercado|`);
`signed_market_value` is preserved alongside so cancellation can never
hide gross exposure.

## Conflict candidates — visible but excluded

A `conflict` row carries `gleif_candidate_lei`/`firds_candidate_lei`;
a `multiple_candidates` row keeps its full list in
`resolution_candidates` (joined through `gleif/firds_observation_id`).
If the requested LEI appears in either, the row's absolute value is
reported as:

```text
conflict_candidate_value_excluded
conflict_candidate_rows_excluded
```

— separate from, and never inside, `known_resolved_value`.

## Coverage semantics (the corrected contract)

```json
"coverage": {
  "scope": "period_security_universe",
  "resolution_ratio": 0.7302,
  "corroborated_ratio": 0.3901,
  "issuer_specific_completeness": null,
  "issuer_exposure_semantics": "known_lower_bound",
  "completeness_reason": "unresolved securities cannot be proven not to belong to this issuer",
  "unattributed_universe": {
    "unresolved_value": "...",
    "invalid_masked_no_isin_value": "...",
    "cash_value": "...",
    "all_reported_value": "..."
  }
}
```

- `resolution_ratio` / `corroborated_ratio` are over the **period
  universe** (valid-ISIN market value), identical for every LEI in the
  same period — they describe the dataset, not the issuer.
- `issuer_specific_completeness` is **always `null`**: unresolved
  securities cannot be proven not to belong to this issuer, so the true
  exposure is unknown and `known_resolved_value` is only a lower bound.
- `unattributed_universe` exposes the residual honestly — it is
  unattributed universe value, **not** potential exposure of the
  queried issuer.

## Output shape

```text
lei, issuer {legal_name, entity_category, legal_jurisdiction}  (GLEIF evidence if loaded)
period, evidence, adjudication {version, bundle}
totals {known_resolved_value, corroborated_value, gleif_only_value,
        firds_only_value, single_source_value, signed_market_value,
        absolute_market_value, conflict_candidate_value_excluded,
        conflict_candidate_rows_excluded, position_rows,
        unique_isins, portfolio_owners}
owners[] {owner_key, fund_key, fund_name, compartment_name,
          manager_name, position_rows, unique_isins, signed_value,
          absolute_value, corroborated_value, gleif_only_value,
          firds_only_value}
positions[]  (--positions only)
  {owner_key, isin_raw, isin_state, descripcion_valor,
   reported_market_value, resolution_state, resolved_lei,
   evidence_strength, xml_locator}
coverage {...}
fingerprint   — sha256 over canonical JSON of (lei, period, evidence,
                version, bundle, owners, totals); identical inputs on
                identical data → identical fingerprint
```

## Live verification (`.tmp-live`, 2025-12)

```text
BANCO SANTANDER (5493006QMFDDMYWIAM13):
  known_resolved_value  €2,548,224,359  (lower bound)
    corroborated        €1,068,679,060
    firds_only          €1,479,545,299
  owners 401 · rows 626 · ISINs 49 · conflicts naming it: 0
  --evidence corroborated → €1,068,679,060 across 192 owners

Raiffeisen KAG (549300O2MVAMFR6BH208):
  gleif_only            €15,072,175  (1 owner, 1 row)
  conflict_candidate    €3,850,415   (3 rows — EXCLUDED, reported)
```

## Frozen gates

1. Only `resolved_lei` enters issuer totals.
2. Conflicts/multiple/no_match never aggregate.
3. GLEIF-only and FIRDS-only stay distinguishable.
4. Position-row grain — duplicate ISIN rows all contribute, no
   destructive `GROUP BY ISIN`.
5. Portfolio owner is the exposure grain; fund/compartment identity
   comes from the queried period's FONDREGISTRO; no share-class
   duplication.
6. Monetary values stay `Decimal` (G1 `ValorMercado` unit, signed +
   absolute preserved, no FX/NAV/notional).
7. `issuer_specific_completeness = null` always; period coverage always
   present.
8. Valid LEI without holdings → honest empty result; malformed LEI →
   fail-closed; unknown `--evidence` → fail-closed.
9. Deterministic fingerprint per (lei, period, evidence, version,
   bundle, data).

Tests: `tests/test_funds_exposed.py` — 12 cases incl. the four goldens
(100% corroborated; mixed evidence; issuer in conflict; LEI without
holdings).

## Explicit non-goals (deferred)

`issuer-exposure` aggregate command, manager aggregation (G8-3),
accounting-parent aggregation (G8-4), domestic look-through (G8-5),
derivatives (FONDDERI instrument identity still unsound), transaction
inference, issuer-name search, provider-priority tie-breaking.
