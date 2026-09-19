# G9-F — Derived Lifecycle Read Model

Verdict: **PASS** — adjudications + derived `ABSORBED_BY` edges
materialized into the Parquet export with full provenance and
deterministic rebuild.

Engine frozen at `g9e-v1` — no rule changes were made here.

## Materialized tables

```text
lifecycle/adjudications/part-0.parquet   2,523 rows (one per candidate:
                                        2,273 dev + 250 holdout)
lineage/edges/part-0.parquet             2,333 rows (ABSORBED_BY only)
```

Adjudication row carries: `adjudication_id`, `candidate_id`,
`entity_key`, `adjudication` (g9e-v1 vocabulary), `successor_key`
(nullable), `rule_id`, `engine_version`, `evidence_signature`,
`evidence_profile_id`, assertion-id lists by class
(authorization/registration/deregistration/execution/participant),
`cross_source_corroborated`, evidence dates per class
(`authorization_date`, `registration_date`, `deregistration_date`,
`execution_date` — never a single invented `effective_date`),
`source_artifact_ids` (raw_sha256-backed), `flags`,
`adjudicated_at_build` (content stamp — engine version, no clock).

No `confidence`/score column: the 93% figure is empirical engine
coverage, not per-row probability.

Edge row: `edge_id`, `from_entity_key` (absorbed), `to_entity_key`
(absorber), `edge_type=ABSORBED_BY`, `evidence_state=ADJUDICATED`,
`rule_id`, `engine_version`, `candidate_id`,
`source_assertion_ids`.

Not materialized: `MERGED_INTO`, `TRANSFORMED_INTO`, `TRANSFERRED_TO`,
`SPLIT_INTO`, `PREDECESSOR_OF`, `SUCCESSOR_OF` (inverse queryable),
edges from `ADJUDICATED_LIQUIDATED` or any `INDETERMINATE_*` /
`UNKNOWN_EXIT`.

## Gates

```text
F2 conservation:   2,523 adjudications out (all candidates)      PASS
F3 edges:          2,333 = ABSORBED_BY adjudications exactly     PASS
                   0 edges from INDETERMINATE_*/UNKNOWN_EXIT
                   0 non-ABSORBED_BY edge types
F4 integrity:      0 edges without matching adjudication
                   0 non-FI successor keys in edges
                   out-degree(ABSORBED_BY) = 0 violations (≤1)   PASS
                   in-degree max = 86 (FI:2359 — allowed)
F5 round-trip:     edge → adjudication → evidence assertion_ids
                   all resolvable in lifecycle/assertions        PASS
F6 dates:          0 invented dates (every *_date equals a real
                   assertion publication_datetime)               PASS
F7 determinism:    second export — identical fingerprints        PASS
F8 exposure:       lifecycle_adjudications + lineage_edges views
                   CLI: lifecycle-fund, predecessors-of          PASS
```

## Fingerprints

```text
adjudications:  5de67147a6f456c44e766966baeb71b636985edcddef1a8702c403598d555b6f
lineage_edges:  9dc2f1c32eb90ac7858ccaf4ec986434b12fef7e2317f657fc09c78c79e2669f
ledger (G9-B):  e2997ce6…8721 unchanged
participants:   65a0a6d7…e379 unchanged
candidates:     e1ab53d3…e54  unchanged
```

## Outcome distribution (all 2,523)

```text
ADJUDICATED_ABSORBED_BY                    2,333  (92.4%)
INDETERMINATE_MULTIPLE_SUCCESSORS             91
INDETERMINATE_NO_SUCCESSOR                    30
ADJUDICATED_LIQUIDATED                        29
UNKNOWN_EXIT                                  33
INDETERMINATE_CORRECTION_OR_RENUNCIATION       6
INDETERMINATE_CONFLICTING_EVIDENCE             1
```

## Regression

```text
tests: 332 passed · ruff clean · mypy clean (39 files)
```

## Status of the G9 series

```text
G9-A  observational candidates      PASS
G9-B-R source coverage              PASS
G9-B  source-assertion ledger       PASS
G9-C  taxonomy measurement+freeze   PASS
G9-E  adjudication engine (g9e-v1)  PASS
G9-F  derived read model            PASS
G9-D  identity episodes             deferred until G10 needs them
```
