# Commercial / product landscape — Spanish fund data

Goal: establish what already exists, not to copy it.

| Provider | What it offers | Holdings? | Open? |
|---|---|---|---|
| **CNMV web** (official) | Per-fund pages (`portal/Consultas/IIC/Fondo.aspx?nif=…`): registry data, VL history, published PDF quarterly/semiannual reports (which contain the same portfolio tables); bulk XML/ZIP download page (this project's source) | Yes, per-fund, as PDF reports + bulk XML | Public, free; not a queryable API; no cross-fund search |
| **VDOS** | Proprietary Spanish fund-data vendor. Feeds from gestoras + CNMV + DGSFP. 60k products, 350 gestoras. Proprietary categories/ratings, NAV history, MiFID/ESG data | Holdings data yes (commercial) | Closed, paid |
| **Morningstar ES** | NAV, ratings, analyst coverage, portfolio "cobertura de datos" metrics, comparables | Yes (licensed/estimated coverage) | Closed, paid tiers |
| **Finect** | Consumer web tools: top-20 positions per fund, "which funds hold stock X" reverse lookup, fund comparators | Current snapshot only, top-N display | Free web UI; no bulk/API/history |
| **Allfunds** | Fund distribution platform + data services for institutional clients | Yes | Closed, B2B |
| **Inverco** | Industry association — aggregate statistics, not position-level | No | Aggregate reports |
| **cnmv-xbrl (OSS)** | Python lib for CNMV XBRL financial statements | Partial (estados cartera) | MIT, code OSS — but different surface, per-entity filings not bulk dissemination |
| **datos.gob.es** | Catalogs some CNMV datasets (e.g. "Información financiera intermedia de IIC") | No | Metadata only |

## Feature matrix vs. envisioned product

| Capability | Exists openly? | Where |
|---|---|---|
| Fund comparison/discovery | yes (many) | Finect, Morningstar, VDOS, CNMV |
| NAV history | yes | CNMV bulk XML (raw), Finect/MStar UI |
| Regulatory documents | yes | CNMV per-fund PDF reports |
| **Position-level holdings, machine-readable, all funds** | **only raw XML** — no tool normalizes it | CNMV FONDCART/SOCCART (unparsed) |
| **Historical holdings (2012→)** | **no product exposes this openly** | source data exists; nobody builds the ledger |
| Security → funds reverse lookup | partial (Finect top-N, current only) | — |
| Issuer exposure aggregation | no open tool | — |
| Portfolio diff across periods | no | — |
| Provenance/auditability, reproducible pipeline | no | — |
| Open bulk dataset + open pipeline | no | — |

## Gap statement (H5)

The unserved layer is **not** fund comparison/NAV — it is the
machine-readable, historical, provenance-preserving **holdings ledger** and
the cross-sectional queries it enables (security→funds, issuer exposure,
snapshot diff). Finect demonstrates demand for security→fund lookup but only
as a current top-N web widget. Nothing open exposes position-level history
back to 2012. H5 SUPPORTED, with the cadence caveat (quarterly →2022,
semiannual 2023+).
