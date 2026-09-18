"""G2 identity resolution + mechanical registry diff.

Resolution contract (fail-closed):

- share-class ISIN -> EXACT_SHARE_CLASS (ISINs verified unique per period)
- FI:9:0:1 key  -> EXACT_SHARE_CLASS
- FI:9:0        -> EXACT_COMPARTMENT
- FI:9 / '9'    -> EXACT_FUND (all compartments)
- anything else / zero or >1 candidates -> AMBIGUOUS / NOT_FOUND

Never resolves by name similarity. Temporal join: the registry is resolved
at its observed period; portfolio positions come from FONDCART keyed by
compartment (``portfolio_owner``), so N share classes map to ONE portfolio
— never duplicated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from cnmv_iic.domain import (
    FundRecord,
    IdentityEvent,
    IdentityEventKind,
    IsinState,
    Resolution,
    ResolutionKind,
    classify_isin,
    compartment_key,
    fund_key,
    share_class_key,
)

_KEY_RE = re.compile(r"^([A-Z]{1,4}):(\d+)(?::(\d+))?(?::(\d+))?$")


@dataclass(frozen=True)
class ShareClassRow:
    """Flat resolution row (mirrors the share_classes parquet table)."""

    share_class_key: str
    fund_key: str
    compartment_key: str
    isin_raw: str | None
    isin_state: str
    denominacion_clase: str | None
    xml_locator: str
    source_artifact_id: str


def resolve(
    identifier: str,
    share_classes: list[ShareClassRow],
    funds: dict[str, tuple[str, ...]],
) -> Resolution:
    """Resolve an identifier to portfolio-owner compartment keys.

    ``funds``: fund_key -> tuple of compartment keys (portfolio owners).
    """
    ident = identifier.strip()

    # 1) ISIN candidate — 12 chars, alpha prefix (covers format-valid AND
    # format-invalid candidates). The identifier itself is classified first:
    # a masked/invalid ISIN is an invalid_identifier, NOT ambiguous —
    # ambiguity is reserved for >1 plausible resolutions.
    if len(ident) == 12 and ident[:2].isalpha():
        state = classify_isin(ident)
        if state is not IsinState.VALID:
            return Resolution(
                kind=ResolutionKind.INVALID_IDENTIFIER, requested=ident,
                portfolio_owners=(),
                note=f"identifier ISIN state is {state.value} "
                     "(masked, absent, malformed or bad check digit) — "
                     "never resolved or corrected",
            )
        hits = [r for r in share_classes if r.isin_raw == ident]
        if not hits:
            return Resolution(
                kind=ResolutionKind.NOT_FOUND, requested=ident,
                portfolio_owners=(), note="ISIN not in registry at period",
            )
        if len(hits) > 1:
            return Resolution(
                kind=ResolutionKind.AMBIGUOUS, requested=ident,
                portfolio_owners=(),
                note=f"ISIN maps to {len(hits)} share classes",
            )
        h = hits[0]
        return Resolution(
            kind=ResolutionKind.EXACT_SHARE_CLASS, requested=ident,
            portfolio_owners=(h.compartment_key,),
            share_class_key=h.share_class_key, share_class_isin=ident,
            fund_key=h.fund_key,
            registry_artifact_id=h.source_artifact_id,
            registry_locator=h.xml_locator,
        )

    # 2) canonical keys FI:9[:0[:1]]
    m = _KEY_RE.fullmatch(ident)
    if m:
        tipo, nreg, ncomp, nclase = m.groups()
        fk = fund_key(tipo, nreg)
        if nclase is not None:
            sck = share_class_key(tipo, nreg, ncomp, nclase)
            hits = [r for r in share_classes if r.share_class_key == sck]
            if not hits:
                return Resolution(
                    kind=ResolutionKind.NOT_FOUND, requested=ident,
                    portfolio_owners=(), note="share-class key not in registry",
                )
            h = hits[0]
            return Resolution(
                kind=ResolutionKind.EXACT_SHARE_CLASS, requested=ident,
                portfolio_owners=(h.compartment_key,),
                share_class_key=sck, share_class_isin=h.isin_raw,
                fund_key=fk, registry_artifact_id=h.source_artifact_id,
                registry_locator=h.xml_locator,
            )
        if ncomp is not None:
            ck = compartment_key(tipo, nreg, ncomp)
            if ck not in funds.get(fk, ()):
                return Resolution(
                    kind=ResolutionKind.NOT_FOUND, requested=ident,
                    portfolio_owners=(), note="compartment not in registry",
                )
            return Resolution(
                kind=ResolutionKind.EXACT_COMPARTMENT, requested=ident,
                portfolio_owners=(ck,), fund_key=fk,
            )
        comps = funds.get(fk)
        if comps is None:
            return Resolution(
                kind=ResolutionKind.NOT_FOUND, requested=ident,
                portfolio_owners=(), note="fund not in registry",
            )
        return Resolution(
            kind=ResolutionKind.EXACT_FUND, requested=ident,
            portfolio_owners=tuple(comps), fund_key=fk,
        )

    # 3) bare numero_registro — G1 behaviour, defaults to FI
    if ident.isdigit():
        comps = funds.get(fund_key("FI", ident))
        if comps is None:
            return Resolution(
                kind=ResolutionKind.NOT_FOUND, requested=ident,
                portfolio_owners=(), note="fund not in registry",
            )
        return Resolution(
            kind=ResolutionKind.EXACT_FUND, requested=ident,
            portfolio_owners=tuple(comps), fund_key=fund_key("FI", ident),
        )

    return Resolution(
        kind=ResolutionKind.NOT_FOUND, requested=ident,
        portfolio_owners=(), note="unrecognized identifier format",
    )


def diff_registry(
    old: list[FundRecord], new: list[FundRecord]
) -> list[IdentityEvent]:
    """Mechanical identity diff between two observed registry snapshots.

    Reports WHAT changed — never WHY (no merger/rebranding inference).
    """
    events: list[IdentityEvent] = []
    new_by_key = {r.key: r for r in new}
    old_by_key = {r.key: r for r in old}
    from_period = old[0].period if old else "?"
    to_period = new[0].period if new else "?"

    for key in sorted(set(old_by_key) | set(new_by_key)):
        o, n = old_by_key.get(key), new_by_key.get(key)
        if o is None or n is None:
            continue  # fund added/removed entirely: out of gate-5 scope
        if o.denominacion != n.denominacion:
            events.append(IdentityEvent(
                IdentityEventKind.NAME_CHANGED, key, "denominacion",
                o.denominacion, n.denominacion, from_period, to_period))
        if (o.gestora.numero_registro, o.gestora.denominacion) != (
                n.gestora.numero_registro, n.gestora.denominacion):
            events.append(IdentityEvent(
                IdentityEventKind.MANAGER_CHANGED, key, "gestora",
                f"{o.gestora.numero_registro}|{o.gestora.denominacion}",
                f"{n.gestora.numero_registro}|{n.gestora.denominacion}",
                from_period, to_period))
        if (o.depositario.numero_registro, o.depositario.denominacion) != (
                n.depositario.numero_registro, n.depositario.denominacion):
            events.append(IdentityEvent(
                IdentityEventKind.DEPOSITARY_CHANGED, key, "depositario",
                f"{o.depositario.numero_registro}|{o.depositario.denominacion}",
                f"{n.depositario.numero_registro}|{n.depositario.denominacion}",
                from_period, to_period))
        if o.etf != n.etf:
            events.append(IdentityEvent(
                IdentityEventKind.ETF_CHANGED, key, "etf",
                o.etf, n.etf, from_period, to_period))

        o_comps = {c.numero_compartimento: c for c in o.compartments}
        n_comps = {c.numero_compartimento: c for c in n.compartments}
        for nc in sorted(set(n_comps) - set(o_comps)):
            events.append(IdentityEvent(
                IdentityEventKind.COMPARTMENT_ADDED, key,
                "numero_compartimento", None, nc, from_period, to_period))
            for cl in sorted(n_comps[nc].classes,
                             key=lambda c: int(c.numero_clase)):
                events.append(IdentityEvent(
                    IdentityEventKind.SHARE_CLASS_ADDED, key,
                    f"compartimento[{nc}].clase", None, cl.numero_clase,
                    from_period, to_period))
        for nc in sorted(set(o_comps) - set(n_comps)):
            events.append(IdentityEvent(
                IdentityEventKind.COMPARTMENT_REMOVED, key,
                "numero_compartimento", nc, None, from_period, to_period))
            for cl in sorted(o_comps[nc].classes,
                             key=lambda c: int(c.numero_clase)):
                events.append(IdentityEvent(
                    IdentityEventKind.SHARE_CLASS_REMOVED, key,
                    f"compartimento[{nc}].clase", cl.numero_clase, None,
                    from_period, to_period))
        for nc in sorted(set(o_comps) & set(n_comps)):
            oc, ncc = o_comps[nc], n_comps[nc]
            o_cls = {c.numero_clase: c for c in oc.classes}
            n_cls = {c.numero_clase: c for c in ncc.classes}
            for k in sorted(set(n_cls) - set(o_cls), key=lambda x: int(x)):
                events.append(IdentityEvent(
                    IdentityEventKind.SHARE_CLASS_ADDED, key,
                    f"compartimento[{nc}].clase", None, k,
                    from_period, to_period))
            for k in sorted(set(o_cls) - set(n_cls), key=lambda x: int(x)):
                events.append(IdentityEvent(
                    IdentityEventKind.SHARE_CLASS_REMOVED, key,
                    f"compartimento[{nc}].clase", k, None,
                    from_period, to_period))
            for k in sorted(set(o_cls) & set(n_cls), key=lambda x: int(x)):
                oi, ni = o_cls[k].isin_raw, n_cls[k].isin_raw
                if oi != ni:
                    events.append(IdentityEvent(
                        IdentityEventKind.ISIN_CHANGED, key,
                        f"compartimento[{nc}].clase[{k}].isin",
                        oi, ni, from_period, to_period))
    return events
