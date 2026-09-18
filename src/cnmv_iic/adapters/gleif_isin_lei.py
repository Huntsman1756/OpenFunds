"""GLEIF/ANNA ISIN->LEI relationship-file adapter (G7-A).

Input: pinned daily full-snapshot ZIP containing one ``lei-isin-*.csv``
member (columns ``LEI,ISIN`` — a relationship row per pair).

Semantics (docs/g7/contract.md):
- The mapping is NNA-program-bound: a missing row means "this snapshot
  contains no ISIN->LEI relationship for this ISIN", never "issuer has
  no LEI".
- ``relationship_semantics`` is verbatim ``isin_issuer_to_lei`` (GLEIF/
  ANNA build the map by comparing the ISIN issuer to the LEI entity).
- Observed snapshots are functional (<=1 LEI per ISIN) but the model
  supports 0/1/N candidates — a future multi-candidate row becomes
  ``multiple_candidates``, not a DB exception.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections.abc import Iterator

from cnmv_iic.domain import (
    TEMPORAL_SEMANTICS,
    ResolutionCandidate,
    ResolutionObservation,
    ResolutionState,
)

PARSER = "cnmv_iic.adapters.gleif_isin_lei"
PARSER_VERSION = "1"
PROVIDER = "gleif_anna_isin_lei"
PROVIDER_DATASET = "isin-lei"
RELATIONSHIP_SEMANTICS = "isin_issuer_to_lei"

_MEMBER_RE = re.compile(r"lei-isin-(\d{8})T\d{6}\.csv$")


def member_snapshot_date(member_name: str) -> str:
    """``lei-isin-20260918T071512.csv`` -> ``2026-09-18``."""
    m = _MEMBER_RE.search(member_name)
    if m is None:
        from cnmv_iic.errors import ParseError
        raise ParseError(
            f"isin-lei member name has no embedded snapshot date: "
            f"{member_name!r}"
        )
    d = m.group(1)
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}"


def csv_member(zf: zipfile.ZipFile) -> str:
    names = [n for n in zf.namelist() if _MEMBER_RE.search(n)]
    if len(names) != 1:
        from cnmv_iic.errors import ParseError
        raise ParseError(
            f"isin-lei zip must contain exactly one lei-isin-*.csv member, "
            f"found {len(names)}"
        )
    return names[0]


def iter_isin_lei(
    zf: zipfile.ZipFile, member_name: str
) -> Iterator[tuple[int, str, str]]:
    """Stream (csv_row_1based, isin, lei). Row 1 = first data row."""
    with zf.open(member_name) as f:
        rdr = csv.reader(io.TextIOWrapper(f, encoding="utf-8"))
        header = next(rdr, None)
        if header != ["LEI", "ISIN"]:
            from cnmv_iic.errors import ParseError
            raise ParseError(
                f"isin-lei csv header {header!r} != expected ['LEI','ISIN']"
            )
        for i, row in enumerate(rdr, start=1):
            if len(row) != 2:
                from cnmv_iic.errors import ParseError
                raise ParseError(f"isin-lei csv row {i}: {len(row)} columns")
            lei, isin = row[0].strip(), row[1].strip()
            if isin:
                yield i, isin, lei


def load_mapping(zf: zipfile.ZipFile, member_name: str) -> dict[str, list]:
    """isin -> [(csv_row, lei), ...] preserving provider row order."""
    out: dict[str, list] = {}
    for row, isin, lei in iter_isin_lei(zf, member_name):
        out.setdefault(isin, []).append((row, lei))
    return out


def build_observations(
    universe: dict[str, tuple[str, ...]],
    mapping: dict[str, list],
    *,
    snapshot_date: str,
    artifact_id: str,
    source_sha256: str,
    member_name: str,
    member_sha256: str,
    retrieved_at: str,
) -> tuple[list[ResolutionObservation], list[ResolutionCandidate]]:
    """Join the corpus ISIN universe against the provider mapping.

    ``universe``: isin -> sorted tuple of corpus periods carrying it.
    Every universe ISIN gets exactly one observation (matched/no_match/
    multiple_candidates); candidates are never collapsed.
    """
    observations: list[ResolutionObservation] = []
    candidates: list[ResolutionCandidate] = []
    for isin in sorted(universe):
        rows = mapping.get(isin, [])
        n = len(rows)
        state = (
            ResolutionState.MATCHED if n == 1
            else ResolutionState.MULTIPLE_CANDIDATES if n > 1
            else ResolutionState.NO_MATCH
        )
        obs_id = f"{PROVIDER}/{snapshot_date}/{isin}"
        observations.append(ResolutionObservation(
            observation_id=obs_id,
            isin=isin,
            provider=PROVIDER,
            provider_dataset=PROVIDER_DATASET,
            provider_snapshot_date=snapshot_date,
            provider_artifact_id=artifact_id,
            state=state,
            candidate_count=n,
            holding_periods=universe[isin],
            temporal_semantics=TEMPORAL_SEMANTICS,
            retrieved_at=retrieved_at,
            source_sha256=source_sha256,
            member_name=member_name,
            member_sha256=member_sha256,
            parser=PARSER,
            parser_version=PARSER_VERSION,
        ))
        for idx, (csv_row, lei) in enumerate(rows, start=1):
            candidates.append(ResolutionCandidate(
                observation_id=obs_id,
                candidate_index=idx,
                candidate_lei=lei,
                relationship_semantics=RELATIONSHIP_SEMANTICS,
                provider_record_locator=f"{member_name}#row={csv_row}",
                raw_json=json.dumps(
                    {"LEI": lei, "ISIN": isin}, sort_keys=True),
            ))
    return observations, candidates
