"""cnmv-iic verify — offline dataset integrity + fingerprint check.

Two verification strategies, both fully offline:

* Period manifests (positions/quality/daily/quarterly/patrimony/
  derivatives contain decimal/date columns whose canonical
  serialization is not stable under parquet round-trip): the source
  artifact is re-parsed through the exact same adapter pipeline used
  at export time, and every recorded fingerprint is recomputed from
  the re-derived row dicts. This is the true reproducibility check —
  same artifact bytes + parser version -> same fingerprint.

* Provider / adjudication / lifecycle manifests (string+int tables,
  round-trip stable): fingerprints are recomputed directly from the
  stored parquet rows.

Never acquires source data, never rewrites anything.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from cnmv_iic.artifacts.store import ArtifactStore, SourceArtifact
from cnmv_iic.storage import (
    canonical_fingerprint,
    compartment_rows,
    daily_rows,
    derivative_coverage_rows,
    derivative_rows,
    fund_rows,
    patrimony_rows,
    position_rows,
    quality_rows,
    quarterly_rows,
    share_class_rows,
)
from cnmv_iic.versions import contract

_LIFECYCLE_FP_TABLES = {
    "ledger_fingerprint": [
        "lifecycle/source_documents", "lifecycle/source_observations",
        "lifecycle/assertions", "lifecycle/entity_resolutions",
        "lifecycle/candidate_links",
    ],
    "participants_fingerprint": ["lifecycle/assertion_participants"],
    "candidates_fingerprint": ["lifecycle/candidates"],
    "adjudications_fingerprint": ["lifecycle/adjudications"],
    "lineage_edges_fingerprint": ["lineage/edges"],
}

_VOLATILE_COLS = {"adjudicated_at"}   # stamped after fingerprinting

Verdict = Literal[
    "SAME_SOURCE_SET_SAME_DATASET",
    "SOURCE_REVISION_DETECTED",
    "LOCAL_DERIVATION_MISMATCH",
    "MISSING_SOURCE_ARTIFACT",
]


def source_set_fingerprint(artifacts: list[SourceArtifact]) -> str:
    """Canonical fingerprint of the source-artifact set alone —
    (period, source_family, sha256) triples, canonically ordered.

    A third-party build over the same source bytes produces the same
    value; a different value means CNMV (or a provider) published
    different bytes — a source revision, not a reproducibility loss.
    """
    h = sha256()
    for p, f, s in sorted(
            (a.period, a.source_family, a.sha256) for a in artifacts):
        h.update(f"{p}|{f}|{s}\n".encode())
    return h.hexdigest()


def _read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = pq.read_table(path).to_pylist()
    return rows


def _part_rows(root: Path, table: str, **part: str) -> list[dict]:
    """All rows of `table` under partition dirs matching **part."""
    tdir = root / table
    if not tdir.is_dir():
        return []
    rows: list[dict] = []
    for p in sorted(tdir.glob("**/*.parquet")):
        rel = p.relative_to(tdir)
        if all(f"{k}={v}" in rel.parts for k, v in part.items()):
            rows.extend(pq.read_table(p).to_pylist())
    return rows


def _fp(*row_sets: list[dict]) -> str:
    return canonical_fingerprint(*row_sets)


def _period_fingerprints(parsed: dict) -> dict[str, str]:
    """Recompute every period fingerprint from re-parsed domain
    objects — identical to what write_period recorded."""
    out: dict[str, str] = {}
    snaps = parsed["snaps"]
    out["dataset_fingerprint"] = _fp(
        position_rows(snaps), quality_rows(snaps))
    if parsed["records"] is not None:
        rec = parsed["records"]
        out["registry_fingerprint"] = _fp(
            fund_rows(rec), compartment_rows(rec), share_class_rows(rec))
    if parsed["daily"] is not None:
        out["daily_fingerprint"] = _fp(daily_rows(parsed["daily"]))
    if parsed["quarterly"] is not None:
        out["quarterly_fingerprint"] = _fp(
            quarterly_rows(parsed["quarterly"]))
    if parsed["patrimony"] is not None:
        out["patrimony_fingerprint"] = _fp(
            patrimony_rows(parsed["patrimony"]))
    if (parsed["derivatives"] is not None
            or parsed["derivative_coverage"] is not None):
        out["derivatives_fingerprint"] = _fp(
            derivative_rows(parsed["derivatives"] or []),
            derivative_coverage_rows(
                parsed["derivative_coverage"] or []))
    return out


def verify_dataset(
    root: Path | str,
    artifacts_root: Path | str | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Recompute all recorded fingerprints; return a check report.

    ``root`` is the dataset directory; ``artifacts_root`` the sibling
    artifact store (required to re-derive period fingerprints)."""
    from cnmv_iic.ingest import _parse_artifact_members

    root = Path(root)
    store = (ArtifactStore(artifacts_root)
             if artifacts_root is not None
             and Path(artifacts_root).is_dir() else None)
    checks: list[dict] = []
    skipped: list[str] = []
    verdicts: dict[str, Verdict] = {}

    def check(name: str, ok: bool, expected: str, actual: str) -> None:
        checks.append({
            "name": name, "ok": ok,
            "expected": expected, "actual": actual,
        })

    mdir = root / "manifests"
    if not mdir.is_dir():
        return {"ok": False, "checks": [], "skipped": skipped,
                "verdicts": verdicts,
                "source_set_fingerprint": None,
                "verdict": "MISSING_SOURCE_ARTIFACT",
                "problems": [f"no manifests directory at {mdir}"]}

    all_arts = store.load() if store else []
    ledger = {a.sha256: a for a in all_arts}
    ssfp = source_set_fingerprint(all_arts) if store else None
    parsed_cache: dict[str, dict] = {}

    for mpath in sorted(mdir.glob("*.json")):
        m = json.loads(mpath.read_text(encoding="utf-8"))
        name = mpath.name

        if "dataset_fingerprint" in m or "period" in m:
            period = m["period"]
            # registry tables are string-only — parquet round-trip is
            # faithful even without the source artifact
            if "registry_fingerprint" in m:
                got = _fp(
                    _part_rows(root, "funds", period=period),
                    _part_rows(root, "compartments", period=period),
                    _part_rows(root, "share_classes", period=period))
                check(f"{name}:registry_fingerprint",
                      got == m["registry_fingerprint"],
                      m["registry_fingerprint"], got)

            aid = m.get("source_artifact_id") or ""
            sha = aid.rsplit("/", 1)[-1] if "/" in aid else aid
            art = ledger.get(sha) if store else None
            if art is None or store is None:
                verdicts[period] = "MISSING_SOURCE_ARTIFACT"
                check(f"{name}:source_artifact", False, sha,
                      "<absent from store>")
                for key in ("dataset_fingerprint", "daily_fingerprint",
                            "quarterly_fingerprint",
                            "patrimony_fingerprint",
                            "derivatives_fingerprint"):
                    if key in m:
                        skipped.append(f"{name}:{key} "
                                       "(artifact not in store)")
                continue
            verdicts[period] = "SAME_SOURCE_SET_SAME_DATASET"

            # a newer artifact for the same period means the source
            # itself was republished — different input bytes, not a
            # local derivation error
            latest = store.latest_for_period(period)
            if latest is not None and latest.sha256 != sha:
                verdicts[period] = "SOURCE_REVISION_DETECTED"
                check(f"{name}:source_revision", False, sha,
                      f"latest in store: {latest.sha256}")

            if on_progress:
                on_progress(period)
            if sha not in parsed_cache:
                try:
                    parsed_cache[sha] = _parse_artifact_members(
                        store, art)
                except Exception as exc:    # report, never abort
                    parsed_cache[sha] = {"__error__": str(exc)}
            if "__error__" in parsed_cache[sha]:
                verdicts[period] = "LOCAL_DERIVATION_MISMATCH"
                for key in ("dataset_fingerprint", "daily_fingerprint",
                            "quarterly_fingerprint",
                            "patrimony_fingerprint",
                            "derivatives_fingerprint"):
                    if key in m:
                        check(f"{name}:{key}", False, m[key],
                              f"re-parse failed: "
                              f"{parsed_cache[sha]['__error__']}")
                continue
            got_map = _period_fingerprints(parsed_cache[sha])
            mismatch = False
            for key in ("dataset_fingerprint", "daily_fingerprint",
                        "quarterly_fingerprint", "patrimony_fingerprint",
                        "derivatives_fingerprint"):
                if key in m:
                    ok = got_map.get(key) == m[key]
                    mismatch = mismatch or not ok
                    check(f"{name}:{key}", ok,
                          m[key], got_map.get(key, "<absent>"))
            if mismatch and verdicts[period] == \
                    "SAME_SOURCE_SET_SAME_DATASET":
                verdicts[period] = "LOCAL_DERIVATION_MISMATCH"
            continue

        if "adjudication_fingerprint" in m:
            version = m["adjudication_version"]
            bkey = m["evidence_bundle_fingerprint"][:16]
            got = _fp(
                [{k: v for k, v in r.items() if k not in _VOLATILE_COLS}
                 for r in _part_rows(
                     root, "security_resolution",
                     version=version, bundle=bkey)],
                [{k: v for k, v in r.items() if k not in _VOLATILE_COLS}
                 for r in _part_rows(
                     root, "instrument_family_resolution",
                     version=version, bundle=bkey)])
            check(f"{name}:adjudication_fingerprint",
                  got == m["adjudication_fingerprint"],
                  m["adjudication_fingerprint"], got)
            continue

        if "instrument_fingerprint" in m:
            got = _fp(
                _part_rows(root, "instrument_observations",
                           provider=m["provider"],
                           retrieval=m["campaign"]),
                _part_rows(root, "instrument_candidates",
                           provider=m["provider"],
                           retrieval=m["campaign"]))
            check(f"{name}:instrument_fingerprint",
                  got == m["instrument_fingerprint"],
                  m["instrument_fingerprint"], got)
            continue

        if "evidence_fingerprint" in m:   # gleif golden
            got = _fp(
                _part_rows(root, "legal_entities",
                           provider="gleif",
                           snapshot=m["provider_snapshot_date"]),
                _part_rows(root, "relationships",
                           provider="gleif",
                           snapshot=m["provider_snapshot_date"]),
                _part_rows(root, "relationship_exceptions",
                           provider="gleif",
                           snapshot=m["provider_snapshot_date"]))
            check(f"{name}:evidence_fingerprint",
                  got == m["evidence_fingerprint"],
                  m["evidence_fingerprint"], got)
            continue

        if "resolution_fingerprint" in m:
            snap = m["provider_snapshot_date"]
            prov = m["provider"]
            sets = [
                _part_rows(root, "resolution_observations",
                           provider=prov, snapshot=snap),
                _part_rows(root, "resolution_candidates",
                           provider=prov, snapshot=snap),
            ]
            if m.get("evidence_records"):
                sets.append(_part_rows(
                    root, "resolution_candidate_evidence",
                    provider=prov, snapshot=snap))
            got = _fp(*sets)
            check(f"{name}:resolution_fingerprint",
                  got == m["resolution_fingerprint"],
                  m["resolution_fingerprint"], got)
            continue

    # -- lifecycle manifest ------------------------------------------------
    lmpath = root / "lifecycle" / "manifest.json"
    if lmpath.exists():
        lm = json.loads(lmpath.read_text(encoding="utf-8"))
        for key, tables in _LIFECYCLE_FP_TABLES.items():
            if key not in lm:
                continue
            got = _fp(*(_read_rows(root / t / "part-0.parquet")
                        for t in tables))
            check(f"lifecycle:{key}", got == lm[key], lm[key], got)

        # compatibility contract recorded at build time
        rec = lm.get("versions")
        cur = contract()
        check("lifecycle:versions", rec == cur,
              json.dumps(rec, sort_keys=True) if rec else "<absent>",
              json.dumps(cur, sort_keys=True))

        # structural lifecycle invariants — same gates as G9-F
        adj = _read_rows(root / "lifecycle" / "adjudications"
                         / "part-0.parquet")
        edges = _read_rows(root / "lineage" / "edges" / "part-0.parquet")
        absorbed = {a["candidate_id"] for a in adj
                    if a["adjudication"] == "ADJUDICATED_ABSORBED_BY"}
        edge_ok = (
            all(e["edge_type"] == "ABSORBED_BY" for e in edges)
            and all(e["candidate_id"] in absorbed for e in edges)
            and len({e["candidate_id"] for e in edges}) == len(edges)
            and len({e["candidate_id"] for e in edges})
            == len(absorbed & {e["candidate_id"] for e in edges}))
        check("lifecycle:edge_invariants", edge_ok,
              "edges ⊆ adjudicated ABSORBED_BY, out_degree ≤ 1",
              f"{len(edges)} edges / {len(absorbed)} absorbed")

    problems = [c["name"] for c in checks if not c["ok"]]
    # worst-case aggregation: MISSING > MISMATCH > REVISION > SAME
    order: dict[Verdict, int] = {
        "MISSING_SOURCE_ARTIFACT": 3,
        "LOCAL_DERIVATION_MISMATCH": 2,
        "SOURCE_REVISION_DETECTED": 1,
        "SAME_SOURCE_SET_SAME_DATASET": 0,
    }
    verdict: Verdict = "SAME_SOURCE_SET_SAME_DATASET"
    for v in verdicts.values():
        if order[v] > order[verdict]:
            verdict = v
    return {
        "ok": not problems, "checks": checks, "skipped": skipped,
        "problems": problems,
        "verdicts": verdicts,
        "verdict": verdict,
        "source_set_fingerprint": ssfp,
    }
