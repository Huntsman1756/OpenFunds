# ADR-004: Provenance — content-hash artifact ledger

Status: Accepted (draft) · Date: 2026-09-17

## Context
CNMV download URLs are ephemeral tokens; periods may be republished
(unverified but must be handled). Every claim needs a byte-level anchor.

## Decision
- `SourceArtifact` identity = SHA-256 of downloaded ZIP; per-member hashes too.
- Period+hash conflicts create superseding versions, never overwrites.
- Every canonical row: `source_artifact_id`, `member`, `period`,
  `evidence_state`, `record_locator`.
- Build emits dataset manifest (counts, hashes, dataset_sha256 over logical
  rows).

## Alternatives
URL-as-identity (breaks: tokens rotate); DB-only provenance (not portable).

## Consequences
+ Audit/reproduction without redistributing data; corrections handled honestly.
− Slight per-row overhead (columnar, cheap).
