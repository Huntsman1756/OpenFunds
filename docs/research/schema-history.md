# CNMV schema history — XSD fingerprint matrix

Method: downloaded the March (or June/December full-cadence) ZIP for
2012, 2014, 2016, 2018, 2020, 2022, 2023-06, 2025-12; hashed every embedded XSD
with SHA-256; validated representative instances with lxml.

## Result: ONE schema generation for the entire history

Every XSD is byte-identical across all sampled periods (2012-03 → 2025-12):

| Family | XSD SHA-256 (truncated) | Periods identical |
|---|---|---|
| FONDREGISTRO | 1b0a949a3940cd2f | 2012,2014,2016,2018,2020,2022,2023-06,2024,2025 |
| FONDMENS | 923803f9a93fa658 | idem |
| FONDTRIM | 7a39ece36605ee85 | idem |
| FONDPATRIMDISVAR | aae1105328bd4c24 | idem |
| FONDCART | c5ab271b641242d4 | idem |
| FONDDERI | abeccc345799fa9d | idem |
| SOCREGISTRO | 6c47400171a8e705 | idem |
| SOCTRIM | d2867f6d6538a77d | idem |
| SOCPATRIMDISVAR | 8a1a5b24b066da8d | idem |
| SOCCART | db61da5d84bf9b96 | idem |
| SOCDERI | 0a23059a385dfa86 | idem |

→ **H2 strongly supported**: a single adapter per family covers 2012→present.
No versioned schema adapters needed. (Caveat: this samples March/June/December;
a full backfill should still fingerprint every artifact's XSD and fail closed on
any unknown hash — cheap insurance.)

## Observed instance-vs-XSD deviations (schema-invalid real data)

The published XSDs mark many elements as required (minOccurs=1) that real
instances omit. Validation of real files (lxml, XSD 1.0):

| File | Valid? | Deviation |
|---|---|---|
| FONDREGISTRO_202512 | ✅ | — |
| SOCCART_202512, SOCDERI_202512 | ✅ | — |
| FONDCART_202512 | ❌ (n≈237) | `InversionesFinancieras` without `CodigoISIN` element — all are `DescripcionIF=Depositos` (bank deposits legitimately have no ISIN) |
| FONDCART_201203 | ❌ (n≈3,543) | same — ~5.9% of positions lacked the ISIN element in early history |
| FONDMENS_202512 | ❌ (12) | `Clase` without `VLDiario` (classes with no observations that month) |
| FONDTRIM_202512 | ❌ (460) | `Compartimento` missing `VocacionInversora` / `Clase` before it (element order/omission) |
| FONDDERI_202512 | ❌ (287) | `Entidad` missing `CodigoDivisaIIC` |
| FONDPATRIMDISVAR_202512 | ❌ (288) | `Entidad` missing `CodigoDivisaIIC` |
| FONDDERI_201203, FONDTRIM_201203 | ✅ | — |

**Consequence for design:** strict "validate-or-reject" would fail real official
data. Strategy = *lenient parsing + fail-closed unknown detection*:

1. Parse against an "observed schema" derived from the official XSD plus a
   documented deviation registry (each deviation recorded with family, element,
   periods observed).
2. Any element NOT in (official schema ∪ deviation registry) → explicit
   `UNSUPPORTED_SCHEMA` state, never silent skip.
3. Validation results are data-quality metadata, not a gate.

## Filename/casing variance (does not affect schema)

- `FONDCART_201203.XML` (2012–2016) → `FONDCART.XML` (2018) → `FONDCART_202003.xml` (2020+).
- `.XSD`/`.xsd` casing varies. Identify members by normalized prefix + extension, never by exact name.

## Explanatory PDFs

`*_Documento Explicativo.pdf` per family; FONDREGISTRO's changed between 2012
and 2016 (byte size differs); most others identical across years. They document
field semantics — worth extracting text once per version into docs.

## Registry format (proposal)

```json
{
  "family": "FONDCART",
  "schema_versions": [
    {"xsd_sha256": "c5ab271b...", "periods_observed": ["2012-03","2025-12"], "status": "SUPPORTED"}
  ],
  "deviations": [
    {"element": "Entidad/Compartimento/InversionesFinancieras/CodigoISIN",
     "kind": "MISSING_REQUIRED_ELEMENT", "periods": ["2012-03","2025-12"],
     "note": "absent for DescripcionIF=Depositos"}
  ]
}
```
