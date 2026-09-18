# Source adapter design (CNMV → canonical)

## Pipeline

```
list page (ejercicio=YYYY)
  → scrape month→token map (localized month names: ES/CA/GL/EU — Aletheia pattern)
  → GET token URL (hardened: timeout, redirect≤5, ≤64MB, content-type, ZIP magic)
  → SourceArtifact (sha256 now, bytes immutable)
  → zip open (entry ≤N, decompressed ≤cap, ratio ≤cap, name normalization:
    FAMILY_PERIOD.{xml,xsd} case-insensitive; path-traversal rejected)
  → per member: XSD hash → schema registry lookup → KNOWN or UNSUPPORTED_SCHEMA
  → streaming parse (lxml.etree.iterparse, DTD/entities disabled, char cap)
  → element accounting {seen, mapped, ignored_known, UNKNOWN→fail}
  → canonical rows + provenance
  → reconcile/report (never coerce)
```

## Adapter-per-family, single generation

Because all XSDs are byte-identical 2012→2025, **one adapter per family**
(`fondcart.v1`, …) suffices; the registry still fingerprints every artifact's
XSD so any future schema drift fails closed.

Observed-deviation registry (from schema-history.md) is part of each adapter's
contract — e.g. FONDCART allows absent `CodigoISIN`; FONDDERI/
FONDPATRIMDISVAR allow absent `CodigoDivisaIIC`; FONDMENS allows `Clase`
without `VLDiario`; FONDTRIM tolerates `VocacionInversora` absence/order.

## Parsing rules

- Unknown element/attribute/enum value → `UNSUPPORTED_SCHEMA` error for that
  member; recorded in run report; partial family output is marked incomplete,
  not silently missing.
- Text fields stored verbatim (encoding is UTF-8 with occasional mojibake in
  the wild — store as received, flag encoding anomalies; never "fix").
- `DescripcionValor` split on `|` is a DERIVED parse producing
  `(instrument_type, issuer_text, coupon_text, maturity_text)` — raw kept.
- Numbers: Decimal, source scale (VL=4dp, money=2dp).
- Empty/0 sentinel: `VL_DiaN=0` ⇒ UNAVAILABLE for that day (documented CNMV
  convention, confirmed by ticker-lab + data).

## Acquisition etiquette

Identifiable UA, ~1.5 s between requests, reuse cached artifacts by hash,
HEAD/GET only against documented page+token endpoints, no parallel hammering.
