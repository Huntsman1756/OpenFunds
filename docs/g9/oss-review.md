# G9-R — OSS reuse review

Date: 2026-09-18
Base HEAD inspected: `8108484bc23f78c7c7c2cb706a09c3e2a290cb04`
Status: **review complete; no new runtime dependency selected**.

## Scope

G9 extends the existing `cnmv-iic` data infrastructure from mechanical registry deltas (`WHAT changed`) toward evidence-backed fund lifecycle and lineage (`WHY / what legal event explains the change`). This review is intentionally narrow: it looks for reusable lifecycle/event/lineage machinery and does **not** reopen G0–G8 parsing, acquisition, provenance, storage, identity, or issuer-resolution decisions.

Existing project infrastructure remains `REUSE_DIRECTLY`: hardened acquisition, immutable `ArtifactStore`, row-level provenance, deterministic fingerprints, FONDREGISTRO identity, Parquet/DuckDB storage, exact fail-closed keys, and offline rebuild.

## Candidates inspected

| Candidate | License | What it actually provides | Decision | Why |
|---|---|---|---|---|
| `Huntsman1756/OpenFunds` current G0–G8 | MIT | CNMV acquisition/artifacts, exact fund/compartment/class identity, monthly registry snapshots, mechanical `fund-events`, provenance, deterministic storage | **REUSE_DIRECTLY** | This is the substrate. G9 should add evidence/candidate/adjudication layers, not duplicate it. |
| `fundsxml/schema` | MIT | Fund/share-class static vocabulary including liquidation date/reason and registration/deregistration concepts; transaction vocabulary includes merger/liquidation concepts | **REFERENCE_ONLY** | Useful terminology/interop reference, but not a lifecycle evidence engine and no predecessor/successor adjudication model was found. |
| `dgunning/edgartools` | MIT | SEC fund objects (notably N-CEN), filing objects, exact filing provenance; SEC catalog also exposes deregistration/business-combination filing types such as N-8F/N-14 | **REFERENCE_ONLY** | Good architectural prior art for keeping source filing objects separate from derived fund state. SEC-specific identifiers/forms; no direct CNMV lifecycle reuse. |
| `ting-huang-dataops/FundService-CorporateAction-Automation-Suite` | no license found | VBA return-of-capital and boxed-position operations automation | **REJECT** | Public repo is not licensed for reuse and solves security-level operational corporate actions, not fund-vehicle lifecycle. |

Additional GitHub searches for mutual-fund merger/liquidation/lineage/predecessor-successor engines did not surface a mature OSS implementation that solves regulatory fund-vehicle lineage with exact source evidence. This is a search finding, not a claim that no such software can exist.

## Reuse decision

No generic graph database, entity-resolution library, or lifecycle framework is justified at G9-R.

The smallest correct architecture is to reuse existing OpenFunds primitives:

```text
FONDREGISTRO observations
        ↓
exact fund_key / compartment_key
        ↓
observational lifecycle candidates

ArtifactStore + acquisition + provenance
        ↓
official lifecycle source documents
        ↓
source observations/assertions

candidate + assertions
        ↓
deterministic adjudication
        ↓
lifecycle event + optional lineage edge
```

## What must be new code if G9 proceeds

Only CNMV-specific responsibilities:

- exact whole-fund appearance/disappearance candidate generation over monthly FONDREGISTRO;
- acquisition/parsing of official CNMV lifecycle evidence surfaces;
- representation of source assertions and correction/supersession chains;
- lifecycle-stage classification with abstention;
- deterministic adjudication and lineage-edge materialization;
- gold/holdout validation.

Everything else should reuse G0–G8 infrastructure.

## Non-reuse decisions

- No LLM/embedding/fuzzy-name component for authoritative lifecycle extraction.
- No generic knowledge graph runtime.
- No UUID identity layer replacing `fund_key`.
- No FundsXML lifecycle model as internal canonical source.
- No SEC/EDGAR parser dependency: its value is architectural reference only.

## Gate consequence

G9-R reuse gate: **PASS**.

This does **not** make overall G9-R PASS; the official-source review and complete month-to-month FONDREGISTRO candidate measurement are separate gates.