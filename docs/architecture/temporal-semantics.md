# Temporal semantics (what the source actually supports)

The source gives us exactly:

| Concept | Source field | Precision |
|---|---|---|
| reporting period | `FechaDatos` (YYYYMM) + filename suffix | month |
| observation day | `VL_DiaN` position | day (FONDMENS only) |
| retrieved_at | our download timestamp | instant |
| publication_date | NOT in data; only inferable as "page listed it when scraped" | — |
| valid_from/to | NOT in source | — |

Rules:

1. `period` (YYYYMM) is the primary time axis for all families except FONDMENS
   rows, which expand to real dates validated against the calendar
   (VL_DiaN=0 → non-business day, dropped as UNAVAILABLE not zero-valued).
2. **No bitemporality claims.** We record `retrieved_at` per artifact and
   `period` per record; "known_at" queries = "as published in artifact version
   retrieved ≤ t". That is honest and sufficient.
3. Entity attributes (names, manager, depositary) are **period-stamped
   observations**, not current-state — history preserves renames/manager
   changes as facts, not corrections.
4. Corrections: if CNMV republishes a period with different bytes, both
   versions persist; canonical queries default to latest artifact version,
   with `as_retrieved_at` filter available.
5. Cadence is data-driven: portfolio snapshots exist only where the artifact
   contains the family — query `coverage`, never assume quarterly.
