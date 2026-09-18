# Licensing & legal review

Classification scale: PROVEN / LIKELY / AMBIGUOUS / REQUIRES_LEGAL_REVIEW.

## Code-side rights (our software)

| Item | Status | Notes |
|---|---|---|
| Write and publish our own parser/pipeline | PROVEN | our code, our license (recommend Apache-2.0 or MIT — see ADR-006 on name; license ADR pending) |
| Reuse fundsxml/schema | PROVEN | MIT |
| Reuse fundsxml/examples patterns | PROVEN | Apache-2.0 |
| Reuse Aletheia code/patterns | PROVEN | MIT — attribution + LICENSE inclusion required if code copied |
| Reuse ticker-lab code | BLOCKED | no LICENSE → all rights reserved; reference concepts only |
| Reuse delaosash/afernandez119 code | BLOCKED | no LICENSE |
| Reuse qumundo/funds | BLOCKED | proprietary license file |
| Use openfunds field IDs/names | AMBIGUOUS | CC BY-ND 4.0 = no derivatives; referencing/aligning is fine, copying the dictionary into a derived artifact is not |
| Package name `openfunds`/`openfunds-es` | FREE on PyPI but NOT RECOMMENDED | collides with openfunds.org association (see ADR-006) |

## CNMV source-data rights

CNMV Nota Legal (`cnmv.es/portal/utilidades/notalegal`, `sede.cnmv.gob.es/.../NotaLegal.aspx`):

- © CNMV claims exclusive rights over site content and grants **no general license** ("no concede licencia de uso… salvo acuerdo expreso por escrito").
- Standard disclaimers: informative purpose, no accuracy guarantee, may modify/suspend access without notice.
- CNMV disclaims veracity of third-party-filed registry data (matters for our data-quality disclaimers too).

Counterweight: **Ley 37/2007** (PSI reuse, transposing EU Dir. 2003/98 & 2019/1024) + RD 1495/2011 standard reuse conditions: cite source, don't distort meaning, note update date, no implied official endorsement. CNMV publishes datasets on datos.gob.es (e.g., XBRL intermediate financial info), evidencing intent for reuse; the individual-information download page itself is unauthenticated public bulk access built expressly for redistribution of filings.

| Action | Status | Rationale |
|---|---|---|
| Download the ZIPs | PROVEN | public, unauthenticated, purpose-built download page |
| Cache locally during processing | PROVEN | transient technical copy |
| Publish software that downloads them | PROVEN | user-side fetch; we never ship bytes |
| Publish source manifests (URL family, period, sha256, size, retrieved_at) | LIKELY | metadata/facts about files, not the files |
| Publish per-row provenance (which artifact+period a fact came from) | LIKELY | metadata |
| Redistribute raw XML/ZIP in bulk | AMBIGUOUS | CNMV asserts copyright; PSI law likely permits with attribution, but the safe default is **don't redistribute raw archives** — ship downloader instead |
| Publish normalized records (our canonical dataset) | LIKELY-but-flagged | factual data extraction; database sui generis risk is CNMV's not ours; attribution + PSI conditions apply. REQUIRES_LEGAL_REVIEW before publishing bulk normalized snapshots at scale |
| Include data in commercial products | AMBIGUOUS | PSI law doesn't forbid commercial reuse; CNMV nota legal is silent-to-restrictive; flag for counsel |
| Public API serving the data | LIKELY for metadata; AMBIGUOUS for bulk positions | same reasoning as normalized records |

## Architectural consequence (fail-safe)

The repo must be fully functional **without** any bundled CNMV data:
`tool → user downloads → local cache → local database`. Publish manifests and
hashes so others verify they obtained identical bytes. Minimal synthetic or
heavily-truncated fixtures only for tests (schema-shaped, marked synthetic).

## Data quality legal note

CNMV itself disclaims accuracy of issuer-filed data. Our outputs must carry
"as reported" semantics + provenance, which conveniently aligns with both the
legal posture and the engineering design.
