# Provenance model

## SourceArtifact (immutable ledger entry)

```json
{
  "source_id": "cnmv-iic-zip/2025-12/<sha256>",
  "provider": "cnmv",
  "source_family": "descarga-informacion-individual",
  "period": "2025-12",
  "source_page": "https://www.cnmv.es/portal/publicaciones/descarga-informacion-individual?ejercicio=2025",
  "source_url_ephemeral": "https://www.cnmv.es/webservices/verdocumento/ver?e=…",
  "retrieved_at": "2026-09-17T…Z",
  "content_type": "application/zip",
  "size_bytes": 8468915,
  "sha256": "…",
  "members": [{"name":"FONDCART_202512.xml","sha256":"…","bytes":38742259}, …],
  "xsd_hashes": {"FONDCART":"c5ab271b…", …},
  "supersedes_sha256": null,
  "parser_version": "0.1.0",
  "schema_adapter": "fonddcart.v2012"
}
```

- Artifact identity = **content hash**; the token URL is recorded for audit but
  is not identity (tokens rotate).
- Re-downloaded identical bytes → same source_id, no new version.
- Same period, different bytes → new artifact version, `supersedes` set, old
  kept (never silently overwritten).

## Row-level provenance

Every canonical row carries: `source_artifact_id`, `member_name`,
`period`, `evidence_state`, `extracted_at` (deterministic: artifact's
retrieved_at), plus `record_locator` where feasible (entity/compartment/class
path; not byte offsets — XML order is enough).

## Evidence states

| State | Use |
|---|---|
| OBSERVED | literal source value |
| DERIVED | deterministic computation over OBSERVED (e.g., weight = valor_mercado/total; DescripcionValor split) — method+version recorded |
| INFERRED | heuristic/looked-up (e.g., issuer cluster by name) — documented reason, reviewable |
| UNAVAILABLE | field absent/masked in source |
| INDETERMINATE | source ambiguous / conflicting |

## Dataset manifest per build

```json
{"dataset_version":"…","created_at":"…","source_count":N,
 "source_period_min":"2012-01","source_period_max":"…",
 "parser_version":"…","schema_registry_version":"…",
 "row_counts":{…},"source_hashes":[…],"dataset_sha256":"…"}
```

Fingerprint = SHA-256 over canonical Parquet row content in deterministic
order (documented serialization). Enables "same bytes ⇒ same dataset" check.
