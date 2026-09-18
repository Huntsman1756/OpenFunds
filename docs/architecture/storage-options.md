# Storage options evaluation

Workload (evidence-based): ~170 monthly + ~54 full artifacts; ≤4 GB raw;
FONDCART-class ≈100k rows/period; FONDMENS ≈68k obs/month ⇒ ~10–15M NAV rows
over full history; queries: per-class NAV series, per-fund snapshots,
security→funds reverse scans, period cross-sections, diffs.

| Option | Verdict | Why |
|---|---|---|
| **Parquet** | primary durable format | columnar, versionable by content hash, zero-server, perfect for archival snapshot-per-period layout and dataset fingerprinting |
| **DuckDB** | query engine over the Parquet | native Parquet scans, SQL, window functions for diffs, Python-embedded, zero-ops; benchmark at G1 |
| SQLite | optional catalog only | provenance/artifact registry could live here; not needed for analytics at this scale |
| PostgreSQL | deferred | only if a multi-user server API ever ships; adds ops burden now |
| Polars | optional fast path | nice for transforms; DuckDB+Arrow covers needs; revisit if benchmarks demand |
| Pandas | avoid in hot path | memory-heavy vs Arrow-native |

Layout (logical, media-agnostic):

```
data/
  raw/cnmv-iic/<period>/<sha256>.zip        # immutable, local/user cache
  artifacts.jsonl                          # SourceArtifact ledger
  normalized/<family>/<period>.parquet     # observed facts
  derived/<metric>/<period>.parquet        # DERIVED layer, method-versioned
  catalog.duckdb (optional view layer)
```

Determinism: fixed column order, sorted rows by documented key, fixed Parquet
writer version + compression → reproducible `dataset_sha256` over row content
(hash the logical rows, not the file bytes, to survive writer changes).

Benchmarks required before finalizing indexes/partitioning (G1): one month,
one full period, one year, full history; wall time / RSS / disk / rows-sec;
security reverse-lookup latency; diff latency.
