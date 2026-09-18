# G9-B-R — Causal Source Coverage Probe

Status: **PASS** (research gate closed)
Base: G9-A2 `8213913` — measurement fingerprint
`1de46aaf15ee31c09bb57589b7f85d98fada517e9115b41216f09317118b0fe4`

Scope: source coverage and semantics research only. No lifecycle
adjudication, no canonical `MERGED_INTO`/`LIQUIDATED`, no production
tables. All findings below are **source assertions**, not adjudicated
events.

---

## 1. Samples

### Blind holdout — sealed

| field | value |
|---|---|
| count | 250 `FUND_DISAPPEARED` |
| selection | `sha256("g9-blind-holdout-v1\|" + candidate_id)` asc, first 250 of 2,523 |
| fingerprint | `546db3a1c615567d8e6059b78a2b72a8eac350fb768c67b10b8b3a9d90f05642` |
| manifest | `docs/g9/blind-holdout-manifest.json` |
| contents | observational fields only (candidate_id, fund_key, periods, lifespan, manager regnum, stratum) |
| inspected | **no** — sealed until post-G9-E rule freeze |

### Coverage sample

| field | value |
|---|---|
| count | 298 of 2,273 non-holdout disappearances |
| fingerprint | `09e11e2f0b80ba92e6d1ba9ff910c874b429b352efcd54da36904499a19127d6` |
| strata | all years 2012–2026 (min 10/yr), lifespan bands, Jul/Sep vs other months, high-volume vs ordinary exit months |
| weights | `sample_weight` per candidate (stratum_n / sampled_n); total weight 2,242 |

### Stress sample

| field | value |
|---|---|
| count | 85 (8 overlap with coverage sample — stress drawn from full non-holdout pool) |
| fingerprint | `6c5993895ffb63c3ac987f59f4bc9dfe7fc0038854bc239463927b23a2a9848a` |
| reasons | single_observation 32, short_lived 15, high_volume_exit_month 15, multi_fund_same_manager_exit 15, era_2024_2026 8 |

Determinism: identical G9-A2 fingerprint + sample version reproduces
all three sets byte-identical.

---

## 2. CNMV_WEEKLY_REGISTRY_BULLETIN

| aspect | finding |
|---|---|
| listing URL | `https://internet.cnmv.es/portal/publicaciones/cnmvinforma?lang=es` |
| week enumeration | ASP.NET `<select name="ctl00$ContentPrincipal$ddlFechas">`, 1,133 week options, value = numeric week id |
| oldest week | `02/11/2004 al 08/11/2004` (id 49) |
| latest week | rolling current week (observed `08/09/2026 al 14/09/2026`, id 7188) |
| selection mechanics | POST form fields `ddlFechas=<week_id>` **plus** `ctl00$ContentPrincipal$btnFechas=Buscar` (plain dropdown postback does **not** switch the document links — verified failure mode) |
| document links | per selected week: `lnkBoletinCompleto`, `lnkEmisiones`, `lnkRegistro`, `lnkHechos`, `lnkOpas` → `webservices/verdocumento/ver?e=<opaque token>` (token deterministic per document) |
| relevant document | `lnkRegistro` = "Operaciones de los Registros Semanales" — investment-fund section with `NUEVAS INSCRIPCIONES`, `BAJAS`, `MODIFICACIONES EN REGLAMENTOS`, `ACTUALIZACIÓN DE ELEMENTOS ESENCIALES DE FOLLETOS INFORMATIVOS`, `FUSIÓN DE FONDOS DE INVERSIÓN`, `ACUERDO DE DELEGACIÓN/REVOCACIÓN DE LA GESTIÓN DE ACTIVOS` |
| identity | exact CNMV register number in BAJAS table (`Denominación / Gestora / Depositaria / Nº Registro`) and inside merger prose (`número NNNN`) |
| date semantics | registry week only (`Del dd/mm/yyyy al dd/mm/yyyy`); **no explicit effective date** in baja rows |
| templates/eras | two document-packaging eras: pre-~2010 weeks expose **only** `lnkBoletinCompleto` (fund section still present inside); 2012+ era exposes the split documents. PDF versions differ (1.3 vs 1.7); section taxonomy stable across 2012–2026. PDF text extraction shows column interleave — section boundaries are unreliable, but name+regnum matching is unaffected |
| corrections | none observed in sample (fund sections carry acts, not rectifications) |
| gaps | 615 weeks probed: 614 via `lnkRegistro`, 1 week (7169, 28/04–04/05/2026) had **no** `lnkRegistro` — recovered via `lnkBoletinCompleto` (same section inside) |

### Probe result (transition-window weeks per candidate)

| metric | coverage n=298 | weighted |
|---|---|---|
| exact identity hit (name + regnum) | 297 | 99.7% |
| hit in merger context | 256 | 85.7% |
| no hit | 1 | — |

Single no-hit: `FI:3628 BANKIA BONOS CORTO PLAZO (II)` — merger
authorized 23/03/2018 (HR), disappeared 2018-06; no registry act in
the June weeks + trailing week. Consistent with publication lag
beyond the probed window.

---

## 3. CNMV_IIC_RELEVANT_INFORMATION

| aspect | finding |
|---|---|
| search URL | `https://www.cnmv.es/Portal/hr/busquedahr?division=2` |
| query | ASP.NET POST: `txtDenominacion` (entity denomination) + optional `fecha_desde/fecha_hasta` (dd/mm/yyyy, **verified working** — narrows results and pagination) + event-category checkboxes (57 categories incl. `Fusión de IIC`, `Baja/Disolución/Liquidación/Absorción`, `Revocación de IIC`, `Ecuación de canje definitiva en fusiones de IIC`, `Rectificación Hecho Relevante`) |
| identity path | `fund_key → numero_registro + denominacion (FONDREGISTRO) → HR denominacion search → ResultadoBusquedaHR?nif=<NIF> → event history`. Works for **dead** entities (verified: dissolved fund resolved to NIF). Denomination is navigation only; acceptance requires corroboration |
| corroboration | event prose contains `inscrito en el Registro ... con el número NNNN` — exact regnum match. Entity detail page (`fondo.aspx?nif=`) shows `Nº Registro oficial` **only for live funds** — unusable for dead entities |
| entity header | page title/header sometimes carries `baja dd.mm.yyyy` (explicit deregistration date) — sparse: 0.7% of coverage sample |
| results | paginated list: registration date + time, category, verbatim summary, optional `verdocumento` attachment, HR event register number (`Número de registro: NNNNNN`) — stable per-event identifier |
| advertised history | `desde 01/07/1988` on every entity page; oldest events observed in sample: 2008 (window-limited) |
| assertion stages observed | `Autorizar` → AUTHORIZED (dominant: 467 lc-events), `Verificar y registrar`/`Inscribir` → REGISTERED (165), `ejecución de la fusión y ecuación de canje definitiva` → EXECUTED (45 across all events; often filed as `Otros hechos relevantes`), `disolución` → DISSOLUTION (11), gestora communications → REPORTED |
| exact successor | merger prose pattern `fusión por absorción de A (número 1519), B (número 3119), … por S (número 3030)` — the `por`-clause regnum is the absorbing fund's exact register number |
| effective dates | explicit dates inside lifecycle-relevant text: **2.0%**. `baja` header marker: **0.7%**. Effective date is essentially absent; registration datetime is the bound |
| corrections | `Rectificación Hecho Relevante` is a real category (1 instance: 16/04/2007, reg 79131). Renunciation/desistimiento prose exists (1 instance). Rare but real — ledger must preserve supersession chains |
| unresolved | 22/375 unique candidates: entity search returned nothing — concentrated in 2021+ (recent era) and special names (foreign-vehicle, renamed-before-death). Never resolved by fuzzy matching |

### Probe result

| metric | coverage n=298 | weighted |
|---|---|---|
| entity resolved (NIF) | 277 | 94.4% |
| identity corroborated (regnum in prose) | 273 | 93.4% |
| lifecycle-relevant event | 275 | 93.8% |
| exact successor regnum (`por`-clause) | 260 | 88.7% |
| baja_date marker | 2 | 0.9% |
| explicit effective date in text | 6 | 1.9% |
| resolved but not corroborated (ambiguous) | 4 | — |

Window distribution of lifecycle events: `before_transition` 416,
`inside_transition_window` 3, `outside` 281 (inside the fetched
−14/+4 month band). **HR registration essentially never lands in
the disappearance month** — authorizations precede execution by
months; the bulletin is what lands inside the transition window.

---

## 4. Combined coverage (coverage sample, n=298)

| metric | count | weighted |
|---|---|---|
| any causal evidence | 298 | 100.0% |
| bulletin only | 23 | — |
| HR only | 1 | — |
| both | 274 | — |
| neither | 0 | — |
| ambiguous (resolved, not corroborated) | 4 | — |
| contradictory (merger + dissolution events) | 5 | — |
| unresolved | 0 | — |

The dominant disappearance cause in the sample is **merger by
absorption** (85.7% bulletin merger-context, 87.2% exact successor).

### By era

| era | n | bulletin | HR lifecycle | successor |
|---|---|---|---|---|
| 2012–2014 | 78 | 100% | 98% | 96% |
| 2015–2017 | 70 | 100% | 98% | 90% |
| 2018–2020 | 55 | 98% | 100% | 94% |
| 2021–2023 | 48 | 100% | 77% | 72% |
| 2024–2026 | 47 | 100% | 78% | 74% |

### By lifespan

| band | n | bulletin | HR lifecycle |
|---|---|---|---|
| single_observation | 3 | 100% | 100% |
| 2–6 months | 14 | 100% | 100% |
| 7–24 months | 48 | 100% | 95% |
| >24 months | 233 | 99% | 90% |

### By cluster

| dimension | n | bulletin | HR lifecycle |
|---|---|---|---|
| Jul/Sep exits | 90 | 100% | 91% |
| other months | 208 | 99% | 92% |
| high-volume exit months | 127 | 100% | 96% |
| ordinary months | 171 | 99% | 88% |

(Jul/Sep remains an observation, not a labelled cause.)

### Stress sample (n=85)

bulletin 100% | HR resolved 98% | lifecycle 98% | successor 91%.
All stress strata ≥93% bulletin coverage — including the 32
single-observation funds (which are **not** `NEVER_OBSERVED_ACTIVE`:
they have real registry acts and HR histories).

---

## 5. Source classification

| source | decision | reason |
|---|---|---|
| weekly registry bulletin | **SPINE** | chronological coverage 2004→present; ~100% exact-regnum identity hits inside transition weeks across all eras; machine-checkable acts; the only source that lands inside the transition window |
| relevant information | **SECONDARY** | per-entity crawl (not chronological); 93–94% resolution; supplies what the spine lacks — assertion stages (AUTHORIZED→EXECUTED), exact successor regnum, corrections; fails on ~6% of entities (recent-era/rename gaps) |

## 6. Unexpected findings

1. **FONDREGISTRO `denominacion` itself carries terminal status
   markers**: `baja dd.mm.yy` (20/2,523 universe) and
   `(EN LIQUIDACION)` (39/2,523). The registry name field is itself
   a source-level terminal assertion with an explicit date.
2. **HR coverage dips in the recent era** (77–78% for 2021+ vs
   ~98% for 2012–2020) — the gap is modern, not historical; causes
   observed: entity search returning nothing (renamed/dead without
   HR filings), not missing history.
3. **Stage asymmetry**: AUTHORIZED ≫ EXECUTED — merger
   authorizations are abundant (461 before-transition) while
   execution/canje confirmations are sparse (45). An absorbed fund
   typically has authorization evidence; execution confirmation is
   not guaranteed — adjudication must treat authorized≠executed.
4. **Effective dates are essentially absent** (~2%): neither source
   provides a reliable exact effective date. `effective_at` stays
   mostly NULL; precision available is registry-week (bulletin) and
   registration-datetime (HR).
5. **Successor is usually exact**: the `por <fund> (número N)`
   clause gives the absorbing fund's register number in ~87% of
   coverage cases — no fuzzy matching needed.
6. PDF column interleave makes bulletin **section** attribution
   unreliable, but name+regnum exact matching is unaffected.

## 7. G9-B-R verdict

**PASS** — all ten gate items measured reproducibly:

1. discovery: both sources fully mechanised (postback, search POST, pagination, date filters);
2. historical coverage: bulletin 2004→present, HR advertised 1988→present;
3. identifiers: exact CNMV regnum in both; NIF obtainable via HR resolution; HR event register number per entry; opaque but stable `verdocumento` doc tokens;
4. templates/eras: bulletin split-docs ≥2012 vs completo-only earlier; HR category taxonomy includes pre/post-Circular-4/2009 sets;
5. assertion stages: AUTHORIZED / REGISTERED / EXECUTED / DISSOLUTION / REPORTED / RECTIFIED observed;
6. exact successor: 87.2% coverage;
7. effective date: weak (~2%) — measured, documented;
8. corrections: `Rectificación Hecho Relevante` category + renunciation prose exist, rare;
9. residual: 0 unresolved in coverage sample (4 ambiguous identities, 5 contradictory event sets, 1 bulletin-window miss, 22 HR-unresolved entities — all enumerated);
10. architecture: SPINE + SECONDARY justified by measured incremental value (bulletin_only 23, hr_only 1, both 274, neither 0).

## 8. Proposed G9-B architecture (not implemented)

```text
CNMV_WEEKLY_REGISTRY_BULLETIN   (SPINE — chronological)
  acts: ALTA / BAJA / FUSIÓN / MODIFICACIÓN / DELEGACIÓN
  identity: exact regnum; date: registry week
CNMV_IIC_RELEVANT_INFORMATION   (SECONDARY — per entity)
  assertions: AUTHORIZED / REGISTERED / EXECUTED / DISSOLUTION /
              RENOUNCED / RECTIFIED / REPORTED
  successor: por-clause exact regnum; date: registration datetime
FONDREGISTRO denominacion markers (baja / EN LIQUIDACION)
  as additional source-level assertions
```

Separate layer per preregistered contract:

```text
source assertions (what each document says, verbatim + provenance)
        ≠ adjudicated lifecycle events (G9-C/D rules, later)
```

`effective_at` only from explicit official dates; otherwise NULL.
Corrections preserved as supersession chains, never deleted.

## 9. Next executable step

G9-B design: a source-assertion evidence ledger — research probe
patterns hardened into acquisition + adapters keyed by exact
regnum, week-crawl spine + per-entity HR resolution. No canonical
lifecycle events until the assertion layer is measured again.

---

### Provenance

Raw probe bytes (615 bulletin PDFs, per-candidate HR extracts):
`.research/g9b/` — gitignored by policy.
Probe machinery: `.research/g9b_probe_bulletin.py`,
`.research/g9b_probe_hr.py`, `.research/g9b_analyze.py`.
Metrics: `.research/g9b/metrics.json`,
`.research/g9b/probe_results.json` (verbatim snippets preserved).
