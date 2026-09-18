# Architecture principles (evidence-bound)

1. **Official source of truth only.** Every material fact carries
   `source_artifact_id` → SHA-256-pinned bytes. Nothing enters the canonical
   store except through a source adapter or an explicitly-marked derived layer.
2. **Fail closed.** Unknown schema hash, unknown element, unknown enum value,
   malformed archive → explicit error state, never silent skip. "Observed
   deviations" are an allowlist that must be extended deliberately.
3. **Observed ≠ derived.** `OBSERVED | DERIVED | INFERRED | UNAVAILABLE |
   INDETERMINATE` on values where it matters (e.g., weights are DERIVED —
   source gives market value only; exposure sums are DERIVED).
4. **Never invent.** Missing CodigoISIN stays missing. Masked `XXXXXXXXXXXX`
   stays masked. `INFERRED` requires documented justification; default is
   `UNAVAILABLE`.
5. **Immutability + determinism.** Same bytes + same parser version ⇒ same
   canonical output, verifiable by dataset fingerprint. Raw artifacts are
   never mutated; corrections create new artifact versions linked by
   `supersedes`.
6. **Modular monolith / library.** No Kafka/K8s/services. The whole history is
   ~GB-scale — boring technology wins.
7. **No LLM anywhere in the data path.** Ambiguous regulatory text stays text.
8. **CLI-first, API-later.** The public contract is a Python API + CLI +
   Parquet files; any HTTP API is a thin layer over the same query layer.
9. **Publish code, not data.** User fetches CNMV bytes themselves; we publish
   manifests/hashes (see licensing.md).
