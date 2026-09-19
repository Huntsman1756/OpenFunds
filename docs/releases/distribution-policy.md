# Distribution policy — v0.1

What `cnmv-iic` distributes, what it deliberately does not, and why.

## Policy

| artifact | distributed? | notes |
|---|---|---|
| **Source code** | **yes** | the whole package, tests, docs |
| **Schemas** | **yes** | parquet schemas, DuckDB views — part of `dataset_schema_version` |
| **Manifests / fingerprints** | **yes** | every manifest is redistributable metadata: counts, SHA-256 fingerprints, versions — never source content |
| **Synthetic fixtures** | **yes** | all test XML/JSON fixtures are synthetic by construction; no CNMV bytes are committed |
| **Frozen protocol artifacts** | **yes** | preregistered rules, taxonomy freezes, development gold, regression/holdout manifests — measurement metadata, not source data |
| **Raw CNMV source artifacts** | **no** | official publications (weekly bulletin XML, FOND* zips, HR PDF/HTML) are acquired by each user directly from CNMV; the project does not mirror or redistribute them |
| **Complete normalized dataset** | **not yet** | only after the legal/licensing analysis is settled; see below |

## Why raw artifacts are not redistributed

The dataset is *derived from* official CNMV publications. Those
publications are publicly available from the regulator; the project
adds value through parsing, provenance, and derived read models —
not by acting as a mirror. Each user reproduces the same logical
dataset by acquiring the same artifacts through the CLI:

```text
cnmv-iic sync --from 2012-01
cnmv-iic verify
```

Because artifacts are SHA-256 content-addressed and fingerprints are
recorded in every manifest, two builds over the same source bytes
produce **identical logical fingerprints** — `cnmv-iic verify`
recomputes all of them offline (period fingerprints by re-parsing the
stored artifacts; provider/lifecycle fingerprints from stored tables).

## Provenance and locators

Every row carries `source_artifact_id` — a content-addressed locator
(`<source-family>/<key>/<sha256>`), and source pages/URLs are recorded
in the artifact ledger. Redistribution of source *content* is out of
scope; redistribution of *locators and hashes* is always in scope —
they are what make third-party reproduction possible.

## Normalized dataset distribution — pending

A complete normalized dataset may be distributed in the future only
when the licensing analysis is sufficiently settled. Until then:

- users build locally from official sources (the path above);
- any bundled data shipped later must carry an explicit licensing and
  provenance statement, per source family;
- derived layers whose inputs are exclusively redistributable
  (manifests, fingerprints, protocol artifacts) may be published
  independently of that decision.

## Compatibility

Distributed artifacts are tied to the compatibility contract in
`cnmv_iic.versions`: `dataset_schema_version`,
`canonical_model_version`, `lifecycle_engine_version`,
`lifecycle_parser_version`, `lifecycle_rule_version`,
`parser_version`. A recipient can check that their build matches a
published baseline by comparing fingerprints and contract versions —
no byte-level redistribution required.
