# ADR-001: Implementation language — Python

Status: Accepted (draft) · Date: 2026-09-17

## Context
Need: hardened XML/XSD parsing, streaming, Parquet/Arrow/DuckDB analytics,
CLI, wide contributor accessibility (OSS), minimal ops.

## Options
- **Python**: lxml (libxml2, real XSD 1.0 validation — verified working in this
  environment), defusedxml patterns, pyarrow, duckdb, polars, typer, pydantic.
  Prior art: cnmv-xbrl (MIT, Python) proves CNMV parsing in Python.
- **Go**: ticker-lab shows it's feasible (stdlib streaming XML, no XSD
  validation in stdlib → would need libxml2 bindings anyway); smaller data
  ecosystem (parquet via arrow-go is workable but heavier lift); primary
  audience for this dataset is data analysts → Python wins on adoption.
- **Rust**: strongest safety, weakest ecosystem fit (quick-xml good, XSD
  validation weak, data stack less ergonomic).
- **C#/.NET**: Aletheia is MIT and directly adaptable code-wise, but locks the
  project to .NET audience and its codebase is an app, not a library.

## Decision
Python. Rationale: best XML+XSD and Arrow/DuckDB ergonomics, largest likely
contributor base for a data-infrastructure OSS project, prior art exists.

## Consequences
+ lxml gives real XSD validation + iterparse streaming; duckdb/pyarrow first-class.
− GIL irrelevant at this scale; packaging discipline needed (pin deps, lockfile).
