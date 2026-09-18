# Canonical model (draft — derived from observed CNMV XSDs)

Do not flatten the CNMV hierarchy. Identity ≠ attributes.

## Entities (institutions & vehicles)

```
Institution                    # gestora / depositario / their groups
  cnmv_register_number (key)   # NumeroRegistroGestora / NumeroRegistroDepositario / NumeroGrupo*
  kind: SGIIC|SGC|SAV|... | DEPOSITARY | GROUP
  name (attribute, period-stamped)

Vehicle                        # "Entidad" in source
  (entity_type: FI|FHF|SICAV|SHF, cnmv_register_number)  ← natural key, stable
  attributes per period: denominacion, is_etf, currency (CodigoDivisaIIC where present)

Compartment                    # NumeroCompartimento (0 = structural placeholder)
  belongs to Vehicle
ShareClass (FI) / Series (SICAV)
  belongs to Compartment; NumeroClase|NumeroSerie (0 = placeholder)
  isin (observed in *REGISTRO files; absent in SOCTRIM)
  attributes per period: denominacion, currency
```

## Observations (all period-stamped + artifact-stamped)

```
NavDaily            (class_key, date) → vl, participes|acciones, patrimonio   [FONDMENS]
ClassQuarterFacts   (class_key, period) → vocacion, fees, TER×4, rentabilidad×4,
                    volatilidad×4, num_participaciones, patrimonio, vl, periodicidad [FONDTRIM/SOCTRIM]
CompartmentFlow     (compartment_key, period) → rotacion, DPInv, CartInt, CartExt,
                    dudosas, liquidez, resto, total_patrimonio, flows, P&L breakdown [PATRIMDISVAR]
PortfolioSnapshot   (compartment_key, period)
  └─ SecurityPosition: clase_if(INTERIOR|EXTERIOR|DUDOSAS), descripcion_if,
        isin (OBSERVED|MASKED|ABSENT), descripcion_valor (raw), divisa, valor_mercado
        └─ parsed view (DERIVED): instrument_type, issuer_text, coupon, maturity
  └─ DerivativePosition: descripcion, subyacente, instrumento, importe, objetivo   [DERI]
```

## Relationships worth indexing

- position.isin → security key (when OBSERVED & valid ISO 6166)
- issuer_text → issuer cluster (**DERIVED, versioned, never authoritative**)
- vehicle → gestora / depositario (period-stamped!)
- held-IIC positions whose ISIN resolves to a CNMV class → look-through edges
  (bounded depth, unresolved stays unresolved)

## Deliberately NOT modeled (out of scope)

transactions, prices other than VL, beneficial ownership, foreign-IIC holdings,
pension plans (DGSFP, different regulator).
