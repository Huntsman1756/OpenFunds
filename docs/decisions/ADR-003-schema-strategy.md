# ADR-003: Schema strategy — single-generation adapters + deviation registry

Status: Accepted (draft) · Date: 2026-09-17

## Context
Empirically: all 11 XSD families are byte-identical 2012-03 → 2025-12, but real
instances deviate from XSD (required-in-schema elements are absent in practice:
CodigoISIN on deposits, CodigoDivisaIIC, VocacionInversora, VLDiario).

## Decision
1. One adapter per family (`fonddcart.v1`…), no versioned adapter tree.
2. Schema registry keyed by XSD SHA-256; unknown hash → UNSUPPORTED_SCHEMA.
3. Deviation registry documents each known instance-vs-XSD gap; validation is
   reported as quality metadata, not an ingest gate.
4. Unknown *elements/enums* still fail closed — leniency is only for the
   documented absence of elements, never for unknown presence.

## Consequences
+ Full 14-year coverage with 11 adapters total.
+ Honest model of CNMV's actual data quality.
− Deviation registry must be maintained; new deviations require review.
