# User guide — v0.1

Real examples over a locally built dataset. Every command is
read-only; `--json` gives machine-readable output everywhere.

## Build the dataset

```text
pip install -e .
cnmv-iic sync --from 2012-01          # backfill + lifecycle + verify
cnmv-iic verify                       # offline fingerprint check
cnmv-iic dataset-info                 # coverage, counts, fingerprints
```

`sync` composes the existing acquisition path (monthly backfill,
weekly-bulletin acquisition, offline lifecycle export, offline
verify) — it adds no new ingestion logic. Stored artifacts are never
re-downloaded, so re-running is cheap.

## Find a fund by ISIN

```text
$ cnmv-iic fund ES0138841038
```

Resolves the ISIN against the registry at the latest period, then
returns the full record: fund, compartments, share classes — each with
its CNMV register number and provenance artifact id. Registry keys
(`FI:9`, `FI:9:0`, `FI:9:0:1`) and raw register numbers resolve the
same way.

## Historical holdings

```text
$ cnmv-iic holdings ES0138841038 --as-of 2025-06
$ cnmv-iic holdings FI:9 --as-of 2025-12
$ cnmv-iic portfolio-history FI:9
$ cnmv-iic position-history FI:9 US0378331005
$ cnmv-iic portfolio-diff FI:9 --from 2025-09 --to 2025-12
```

Positions are **reported portfolio positions** — what the fund
disclosed, never beneficial ownership or look-through.

## Which funds reported a position

```text
$ cnmv-iic funds-holding US0378331005 --as-of 2025-12
```

Inverse lookup: every fund/compartment reporting the instrument at
that period.

## Issuer exposure

```text
$ cnmv-iic issuer US0378331005          # resolution verdict + evidence
$ cnmv-iic lei-evidence 95980020140005964591
$ cnmv-iic issuer-coverage              # full-resolution surface
$ cnmv-iic issuer-conflicts             # every CONFLICT, full context
$ cnmv-iic funds-exposed-to 95980020140005964591 --period 2025-12
```

Issuer resolution is evidence-first: `conflict` verdicts carry the
complete disagreement context; the engine never picks a winner.

## Fund lifecycle — what happened to this fund?

```text
$ cnmv-iic lifecycle-fund FI:5534
```

```json
{
  "adjudication": {
    "entity_key": "FI:5534",
    "adjudication": "ADJUDICATED_ABSORBED_BY",
    "successor_key": "FI:1865",
    "rule_id": "R4",
    "engine_version": "g9e-v1",
    "cross_source_corroborated": true,
    "authorization_date": "...",
    "registration_date": "...",
    "deregistration_date": "...",
    "source_artifact_ids": ["cnmv-weekly-registry/…/…", "…"]
  },
  "absorbed_by_edges": [ … ],
  "absorbed_funds": [ … ]
}
```

Key semantics:

- The adjudication is an **engine conclusion** (`rule_id`,
  `engine_version`, evidence signature) — not a source fact.
- Dates are **evidence dates per stage**; no single `effective_date`
  is invented.
- `INDETERMINATE_*` / `UNKNOWN_EXIT` outcomes are returned verbatim —
  they never produce edges.

```text
$ cnmv-iic predecessors-of FI:2359      # funds absorbed by this one
```

`SUCCESSOR_OF`-style inverse queries are computed at read time; no
inverse edge types are stored.

## From a lineage edge to the original artifact

Every adjudication carries the full provenance chain. In Python:

```python
from cnmv_iic.api import open_dataset

d = open_dataset()
life = d.lifecycle("FI:4955")
adj = life["adjudication"]

# assertion ids that supported the conclusion
import json
assertion_ids = json.loads(adj["participant_assertion_ids"])

# source artifacts behind those assertions (PDFs, HTML, XML)
artifact_ids = json.loads(adj["source_artifact_ids"])
# e.g. "cnmv-weekly-registry/2644/registro/<sha256>",
#      "cnmv-iic-relevant-information/hr/FI:4955/search/<sha256>"
```

Each `source_artifact_id` is a content-addressed locator
(`<source-family>/<key>/<sha256>`) — the raw bytes live in the local
artifact store under `artifacts/`, immutable and SHA-256 addressed.
The chain is always:

```text
edge → adjudication → candidate profile → assertions
     → source documents → original artifact bytes
```

So "show me the evidence" is a deterministic walk, not a database
join lottery.

## Python API

```python
from cnmv_iic.api import open_dataset

d = open_dataset("path/to/dataset")     # or default data dir
d.info()                                # dataset-info equivalent
d.fund("ES0138841038")
d.holdings("FI:9", as_of="2025-12")
d.funds_holding("US0378331005")
d.nav("FI:9:0:1", frm="2025-01-01", to="2025-12-31")
d.issuer("US0378331005")
d.funds_exposed_to("95980020140005964591", period="2025-12")
d.lifecycle("FI:5534")
d.predecessors_of("FI:2359")
d.versions()                            # compatibility contract
```

Everything in `cnmv_iic.api` is the supported public contract —
internal DuckDB views are not. See `public-api-v0.1.md`.

## What is observed vs derived

| layer | status |
|---|---|
| registry records, positions, NAV/AUM/investors, official returns | observed source data (verbatim) |
| quality/reconciliation rows | derived comparisons — equality never required |
| issuer resolutions | evidence verdicts; conflicts preserved |
| lifecycle adjudications | engine conclusions (rule + version + provenance) |
| lineage edges | derived; only from `ADJUDICATED_ABSORBED_BY` |
| `INDETERMINATE_*` / `UNKNOWN_EXIT` | honest outcomes, never force-resolved |
