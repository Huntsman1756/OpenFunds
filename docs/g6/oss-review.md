# G6-R — OSS reuse review: historical portfolio change semantics

Scope under review: comparing two published FONDCART snapshots of the
same portfolio owner and exposing the differences as a *change ledger*
— not as inferred transactions.

## Surveyed references

| Reference | What it does | Classification | Rationale |
|-----------|--------------|----------------|-----------|
| `fundsxml/examples` — `Large_File_Processing/python/delta_diff.py` | Streams two FundsXML files, indexes positions by `UniqueID`, emits `added / removed / changed / unchanged` | **ADAPT pattern** | The exact-identity → added/removed/changed skeleton and constant-memory streaming are directly reusable. Rejected parts: `float` math, fixed `0.005` tolerance, and the `UniqueID` uniqueness assumption — FONDCART has no UniqueID and measured ISIN duplication is real (below). We keep `Decimal`, explicit comparison rules, and a measured identity basis. |
| `dgunning/edgartools` | 13F quarter-over-quarter comparisons, per-position history objects | **REFERENCE_ONLY** | Useful API shape precedent (comparison object, position history). Its market context (quarterly 13F filings, CUSIP keys) does not transfer; semantics stay ours. |
| rust-sec-fetcher / 13F Rust implementations | CUSIP-keyed matching, weight/value deltas | **REFERENCE_ONLY** | Confirms the "explicit match key + delta of derived weights" pattern. Rust implementations are not a runtime dependency. |
| 13F radar-style implementations | Turn differences into `new buys`, `full sells`, `net buying/selling`, `net flow`, `turnover` | **REJECT semantic layer** | Snapshot differences are not transactions. CNMV disclosures prove state difference only — price moves, FX, corporate actions, flows, reclassifications and reporting changes all produce identical-looking deltas. Those verbs are not adoptable for this source. |

## Conclusion

No mature OSS implements a CNMV FONDCART snapshot diff (the surveyed
Spanish repos — Aletheia, delaosash/cnmv-funds, afernandez119/cnmv_data,
qumundo/funds, ticker-lab — have no holdings-diff at all). The
*pattern* from FundsXML `delta_diff` is adapted; the *semantics* are
defined by the measured contract in `contract.md`, not inherited from
13F tooling.

## What is deliberately NOT reused

- float arithmetic / fixed epsilon tolerance → we use `Decimal` and
  exact observed-value comparison; "changed" means the reported value
  differs, tolerance is an opt-in display parameter only.
- `UniqueID` as authoritative identity → FONDCART has none; identity
  basis is measured in `contract.md` (ISIN unique-in-portfolio,
  verbatim signature, or unresolved).
- Transaction vocabulary (`BOUGHT`/`SOLD`/`NET_FLOW`/`TURNOVER`) →
  never emitted; the disclosure proves state difference only.
- Fuzzy/similarity matching of descriptors → prohibited; measured
  descriptor churn is 18–30% between snapshots, so descriptors can
  never be a match input.
