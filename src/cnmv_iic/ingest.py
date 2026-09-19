"""G1 ingest orchestration: CNMV index -> artifact -> FONDCART -> Parquet."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cnmv_iic.acquisition.client import CnmvClient, DownloadedPayload
from cnmv_iic.adapters.fondcart import parse_fondcart, reconcile
from cnmv_iic.adapters.fondderi import parse_fondderi
from cnmv_iic.adapters.fondmens import parse_fondmens
from cnmv_iic.adapters.fondpatrimdisvar import parse_fondpatrimdisvar
from cnmv_iic.adapters.fondregistro import parse_fondregistro
from cnmv_iic.adapters.fondtrim import parse_fondtrim
from cnmv_iic.artifacts.store import ArtifactStore, SourceArtifact, member_family
from cnmv_iic.domain import compartment_key, share_class_key
from cnmv_iic.errors import NotFoundError, ParseError
from cnmv_iic.schemas.registry import check_xsd
from cnmv_iic.storage import write_period

INDEX_PAGE = (
    "https://www.cnmv.es/portal/Publicaciones/Descarga-Informacion-Individual.aspx"
)


@dataclass(frozen=True)
class UpdateResult:
    period: str
    artifact: SourceArtifact
    artifact_new: bool
    exported: bool
    dataset_fingerprint: str | None
    registry_fingerprint: str | None
    daily_fingerprint: str | None
    quarterly_fingerprint: str | None
    patrimony_fingerprint: str | None
    derivatives_fingerprint: str | None
    positions: int
    quality_rows: int
    funds: int
    share_classes: int
    daily_observations: int
    quarterly_metrics: int
    patrimony_records: int
    derivative_operations: int
    derivative_coverage_records: int
    fondcart_present: bool
    fondmens_present: bool
    fondtrim_present: bool
    fondpatrimdisvar_present: bool
    fondderi_present: bool


def _atomic_write(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _member_xml(zf: zipfile.ZipFile, family: str) -> tuple[str, bytes] | None:
    for n in zf.namelist():
        if member_family(n) == family and n.lower().endswith(".xml"):
            return n, zf.read(n)
    return None


def _member_sha(artifact: SourceArtifact, name: str) -> str:
    for m in artifact.members:
        if m.name == name:
            return m.sha256
    raise ParseError(f"member {name} not in artifact manifest")


def update_period(
    store: ArtifactStore,
    dataset_root: Path | str,
    period: str,
    *,
    client: CnmvClient | None = None,
) -> UpdateResult:
    """Full vertical slice for one period. Idempotent per artifact bytes."""
    year, month = int(period[:4]), int(period[5:7])
    client = client or CnmvClient()

    index = client.list_months(year)
    url = index.get(month)
    if url is None:
        raise NotFoundError(f"CNMV index has no link for {period}")

    payload = client.download_zip(url)
    artifact, is_new = store.put(
        period=period,
        source_page=f"{INDEX_PAGE}?ejercicio={year}&lang=es",
        source_url=payload.url,
        content_type=payload.content_type,
        data=payload.data,
    )
    return export_artifact(store, dataset_root, artifact, is_new=is_new)


def export_artifact(
    store: ArtifactStore,
    dataset_root: Path | str,
    artifact: SourceArtifact,
    *,
    is_new: bool = False,
) -> UpdateResult:
    """Export canonical tables from a stored artifact — no network."""
    period = artifact.period
    manifest_path = Path(dataset_root) / "manifests" / f"{period}.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    needs_positions = manifest.get("dataset_fingerprint") is None
    needs_registry = manifest.get("registry_fingerprint") is None
    needs_daily = manifest.get("daily_fingerprint") is None
    needs_quarterly = manifest.get("quarterly_fingerprint") is None
    needs_patrimony = manifest.get("patrimony_fingerprint") is None
    needs_derivatives = manifest.get("derivatives_fingerprint") is None
    if not is_new and not (
        needs_positions or needs_registry or needs_daily
        or needs_quarterly or needs_patrimony or needs_derivatives
    ):
        return UpdateResult(
            period=period, artifact=artifact, artifact_new=False,
            exported=False,
            dataset_fingerprint=manifest["dataset_fingerprint"],
            registry_fingerprint=manifest.get("registry_fingerprint"),
            daily_fingerprint=manifest.get("daily_fingerprint"),
            quarterly_fingerprint=manifest.get("quarterly_fingerprint"),
            patrimony_fingerprint=manifest.get("patrimony_fingerprint"),
            derivatives_fingerprint=manifest.get(
                "derivatives_fingerprint"),
            positions=manifest["positions"],
            quality_rows=manifest["quality_rows"],
            funds=manifest.get("funds", 0),
            share_classes=manifest.get("share_classes", 0),
            daily_observations=manifest.get("daily_observations", 0),
            quarterly_metrics=manifest.get("quarterly_metrics", 0),
            patrimony_records=manifest.get("patrimony_records", 0),
            derivative_operations=manifest.get(
                "derivative_operations", 0),
            derivative_coverage_records=manifest.get(
                "derivative_coverage_records", 0),
            fondcart_present=manifest.get("fondcart_present", True),
            fondmens_present=manifest.get("fondmens_present", False),
            fondtrim_present=manifest.get("fondtrim_present", False),
            fondpatrimdisvar_present=manifest.get(
                "fondpatrimdisvar_present", False),
            fondderi_present=manifest.get("fondderi_present", False),
        )

    zf = zipfile.ZipFile(store.raw_path(artifact))

    # XSD fingerprint gate — fail closed on unknown schema generations.
    for fam in ("FONDCART", "FONDPATRIMDISVAR", "FONDREGISTRO", "FONDMENS",
                "FONDTRIM", "FONDDERI"):
        sha = artifact.xsd_sha256.get(fam)
        if sha is not None:
            check_xsd(fam, sha)

    # FONDREGISTRO first: same-period class keys feed the FONDMENS join.
    records = None
    reg = _member_xml(zf, "FONDREGISTRO")
    if reg is not None:
        reg_name, reg_xml = reg
        records = parse_fondregistro(
            reg_xml,
            artifact=artifact,
            member_name=reg_name,
            member_sha256=_member_sha(artifact, reg_name),
        )

    registry_keys = (
        frozenset(
            share_class_key(r.entity_type, r.numero_registro,
                            c.numero_compartimento, cl.numero_clase)
            for r in records
            for c in r.compartments
            for cl in c.classes
        )
        if records is not None else None
    )
    registry_compartment_keys = (
        frozenset(
            compartment_key(r.entity_type, r.numero_registro,
                            c.numero_compartimento)
            for r in records
            for c in r.compartments
        )
        if records is not None else None
    )

    daily = None
    mens = _member_xml(zf, "FONDMENS")
    if mens is not None:
        mens_name, mens_xml = mens
        daily = parse_fondmens(
            mens_xml,
            artifact=artifact,
            member_name=mens_name,
            member_sha256=_member_sha(artifact, mens_name),
            registry_keys=registry_keys,
        )

    quarterly = None
    trim = _member_xml(zf, "FONDTRIM")
    if trim is not None:
        trim_name, trim_xml = trim
        quarterly = parse_fondtrim(
            trim_xml,
            artifact=artifact,
            member_name=trim_name,
            member_sha256=_member_sha(artifact, trim_name),
            registry_keys=registry_keys,
        )

    patrimony = None
    pdv = _member_xml(zf, "FONDPATRIMDISVAR")
    if pdv is not None:
        pdv_name, pdv_xml = pdv
        patrimony = parse_fondpatrimdisvar(
            pdv_xml,
            artifact=artifact,
            member_name=pdv_name,
            member_sha256=_member_sha(artifact, pdv_name),
            registry_compartment_keys=registry_compartment_keys,
        )

    derivatives = None
    derivative_coverage = None
    deri = _member_xml(zf, "FONDDERI")
    if deri is not None:
        deri_name, deri_xml = deri
        derivatives, derivative_coverage = parse_fondderi(
            deri_xml,
            artifact=artifact,
            member_name=deri_name,
            member_sha256=_member_sha(artifact, deri_name),
            registry_compartment_keys=registry_compartment_keys,
        )

    snaps = []
    cart = _member_xml(zf, "FONDCART")
    if cart is not None:
        cart_name, cart_xml = cart
        snaps = parse_fondcart(
            cart_xml,
            artifact=artifact,
            member_name=cart_name,
            member_sha256=_member_sha(artifact, cart_name),
        )
        reconcile(snaps, pdv[1] if pdv else None)

    if cart is None and records is None and daily is None \
            and quarterly is None and patrimony is None:
        raise ParseError(
            f"artifact {artifact.source_id} has no parseable members "
            f"(FONDCART/FONDREGISTRO/FONDMENS/FONDTRIM/"
            f"FONDPATRIMDISVAR all absent)"
        )

    manifest = write_period(
        dataset_root, snaps, period=period,
        artifact_id=artifact.source_id, records=records, daily=daily,
        quarterly=quarterly, patrimony=patrimony,
        derivatives=derivatives,
        derivative_coverage=derivative_coverage,
    )
    return UpdateResult(
        period=period, artifact=artifact, artifact_new=is_new,
        exported=True,
        dataset_fingerprint=manifest["dataset_fingerprint"],
        registry_fingerprint=manifest.get("registry_fingerprint"),
        daily_fingerprint=manifest.get("daily_fingerprint"),
        quarterly_fingerprint=manifest.get("quarterly_fingerprint"),
        patrimony_fingerprint=manifest.get("patrimony_fingerprint"),
        derivatives_fingerprint=manifest.get("derivatives_fingerprint"),
        positions=manifest["positions"],
        quality_rows=manifest["quality_rows"],
        funds=manifest.get("funds", 0),
        share_classes=manifest.get("share_classes", 0),
        daily_observations=manifest.get("daily_observations", 0),
        quarterly_metrics=manifest.get("quarterly_metrics", 0),
        patrimony_records=manifest.get("patrimony_records", 0),
        derivative_operations=manifest.get("derivative_operations", 0),
        derivative_coverage_records=manifest.get(
            "derivative_coverage_records", 0),
        fondcart_present=manifest["fondcart_present"],
        fondmens_present=manifest.get("fondmens_present", False),
        fondtrim_present=manifest.get("fondtrim_present", False),
        fondpatrimdisvar_present=manifest.get(
            "fondpatrimdisvar_present", False),
        fondderi_present=manifest.get("fondderi_present", False),
    )


def _month_range(first: str, last: str) -> list[str]:
    """Inclusive 'YYYY-MM' sequence."""
    y, m = int(first[:4]), int(first[5:])
    y2, m2 = int(last[:4]), int(last[5:])
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


class _IndexCachingClient(CnmvClient):
    """list_months memoized per year across a backfill run; downloads
    delegate unchanged to the wrapped hardened client."""

    def __init__(self, inner: CnmvClient) -> None:
        self._inner = inner
        self._cache: dict[int, dict[int, str]] = {}
        self.request_delay = inner.request_delay

    def list_months(self, year: int) -> dict[int, str]:
        if year not in self._cache:
            self._cache[year] = self._inner.list_months(year)
        return self._cache[year]

    def download_zip(self, url: str) -> DownloadedPayload:
        return self._inner.download_zip(url)


def backfill_periods(
    store: ArtifactStore,
    dataset_root: Path | str,
    first: str,
    last: str,
    *,
    client: CnmvClient | None = None,
) -> dict:
    """G9-A2 — chronological, resumable monthly backfill.

    Per period, exactly one of:
    - manifest complete + artifact present  -> "already_complete"
      (no network at all);
    - artifact stored but export incomplete -> "exported_from_local"
      (no network; export_artifact is itself a no-op if complete);
    - otherwise                            -> update_period (network).

    Per-period failures are isolated and reported, never silent.
    """
    import time as _time

    from cnmv_iic.errors import CnmvIicError

    inner = client or CnmvClient()
    caching = _IndexCachingClient(inner)
    results: list[dict] = []
    for period in _month_range(first, last):
        prior = store.latest_for_period(period)
        manifest_path = Path(dataset_root) / "manifests" / f"{period}.json"
        manifest: dict = {}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text("utf-8"))
        entry: dict = {"period": period}
        try:
            if prior is not None and manifest.get("registry_fingerprint"):
                entry["status"] = "already_complete"
                entry["registry_fingerprint"] = manifest[
                    "registry_fingerprint"]
            elif prior is not None and store.raw_path(prior).exists():
                res = export_artifact(store, dataset_root, prior)
                entry["status"] = (
                    "exported_from_local" if res.exported
                    else "already_complete")
                entry["artifact"] = prior.source_id
                entry["registry_fingerprint"] = res.registry_fingerprint
                entry["funds"] = res.funds
            else:
                res = update_period(store, dataset_root, period,
                                    client=caching)
                entry["status"] = (
                    "downloaded" if res.artifact_new
                    else "exported_from_local" if res.exported
                    else "already_complete")
                entry["artifact"] = res.artifact.source_id
                entry["registry_fingerprint"] = res.registry_fingerprint
                entry["funds"] = res.funds
                _time.sleep(inner.request_delay)
        except CnmvIicError as exc:
            entry["status"] = "failed"
            entry["error"] = str(exc)
        results.append(entry)
    return {
        "first": first,
        "last": last,
        "attempted": len(results),
        "downloaded": sum(1 for r in results
                          if r["status"] == "downloaded"),
        "exported_from_local": sum(1 for r in results
                                   if r["status"] == "exported_from_local"),
        "already_complete": sum(1 for r in results
                                if r["status"] == "already_complete"),
        "failed": [r for r in results if r["status"] == "failed"],
        "periods": results,
    }
