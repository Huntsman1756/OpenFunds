# Contributing to cnmv-iic

## Project contract

This project is evidence-first and fail-closed. Before contributing, read:

- `docs/architecture/principles.md` — OBSERVED vs DERIVED, no invented data
- `docs/architecture/provenance.md` — row-level provenance requirements
- `docs/decisions/` — ADRs (schema strategy, storage, naming)

Hard rules:

1. **Never redistribute raw CNMV bytes.** Tests use synthetic fixtures only;
   `.research/` and `data/` stay local. `tools/g0_probe.py` is the
   reproducibility path for live evidence.
2. **Decimal, never float** for source monetary/percentage values.
3. **Fail closed.** Unknown XSD fingerprint, unknown XML element, or
   unregistered structural deviation must raise — never silently skip.
   New *official* deviations get registered in
   `src/cnmv_iic/schemas/registry.py` with observed periods and a note.
4. **No silent inference.** Masked/absent/malformed identifiers stay
   explicitly marked (`isin_state`), never synthesized.
5. **Determinism.** Same artifact + same parser version => same ordered
   rows and same `dataset_fingerprint`.

## Development setup

```bash
pip install -e ".[dev]"
python -m pytest tests/
python -m ruff check src tests
python -m mypy src
```

## Pull request checklist

- [ ] `pytest`, `ruff`, `mypy` all green
- [ ] No CNMV raw bytes, ZIPs, or bulk derived data in the diff
- [ ] New source elements/deviations registered + documented
- [ ] OBSERVED fields never mixed with DERIVED values
- [ ] Provenance fields populated for any new emitted row
- [ ] Docs updated (ADR if an architectural decision was made)

## Terminology

- "positions" = *reported portfolio positions* — never "holdings of holders",
  and never imply beneficial ownership.
- `funds-holding` lists funds *reporting a position in* an instrument.
