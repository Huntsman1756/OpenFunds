# ADR-002: Storage — Parquet files + DuckDB query layer

Status: Accepted (draft) · Date: 2026-09-17

## Context
Dataset is GB-scale (≤~4 GB raw history, ~100k positions/period, ~15M NAV rows).
Requirements: reproducible dataset fingerprint, local-first, zero-ops.

## Decision
- Durable representation: **Parquet**, partitioned by family/period.
- Query: **DuckDB** (embedded SQL over Parquet) powering CLI + Python API.
- Provenance/artifact registry: JSONL ledger (+ optional SQLite catalog later).
- PostgreSQL only if a server API is ever added.

## Alternatives
SQLite-as-primary (weak for 100k×N analytical scans), Postgres-first (ops burden
unjustified), pandas-in-memory (memory churn), anything distributed (absurd at
this scale).

## Consequences
+ Content-addressable, diff-able dataset releases; trivial reproducibility.
− Must define row-content fingerprint (hash logical rows, not file bytes).
− Benchmarks at G1 gate before locking partitioning/indexing.
