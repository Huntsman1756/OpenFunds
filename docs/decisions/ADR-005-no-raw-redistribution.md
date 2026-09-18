# ADR-005: Do not redistribute raw CNMV artifacts

Status: Accepted (draft) · Date: 2026-09-17

## Context
CNMV's nota legal claims © and grants no general license; Spanish/EU PSI law
(Ley 37/2007, RD 1495/2011) likely permits reuse with attribution, but bulk
raw redistribution is the riskiest act and unnecessary.

## Decision
- Repo ships downloader + manifests + hashes only; `data/` is user-generated
  and gitignored.
- Tests use synthetic/minimal schema-shaped fixtures, not CNMV dumps.
- Publishing normalized datasets or a public API over them is deferred pending
  legal review (documented as AMBIGUOUS/REQUIRES_LEGAL_REVIEW in licensing.md).

## Consequences
+ Project is publishable today without legal exposure.
− Users must run acquisition themselves (fine — it's ~minutes).
