"""G1 ingest orchestration: CNMV index -> artifact -> FONDCART -> Parquet."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cnmv_iic.acquisition.client import CnmvClient
from cnmv_iic.adapters.fondcart import parse_fondcart, reconcile
from cnmv_iic.adapters.fondregistro import parse_fondregistro
from cnmv_iic.artifacts.store import ArtifactStore, SourceArtifact, member_family
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
    positions: int
    quality_rows: int
    funds: int
    share_classes: int
    fondcart_present: bool


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

    manifest_path = Path(dataset_root) / "manifests" / f"{period}.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    needs_positions = manifest.get("dataset_fingerprint") is None
    needs_registry = manifest.get("registry_fingerprint") is None
    if not is_new and not (needs_positions or needs_registry):
        return UpdateResult(
            period=period, artifact=artifact, artifact_new=False,
            exported=False,
            dataset_fingerprint=manifest["dataset_fingerprint"],
            registry_fingerprint=manifest.get("registry_fingerprint"),
            positions=manifest["positions"],
            quality_rows=manifest["quality_rows"],
            funds=manifest.get("funds", 0),
            share_classes=manifest.get("share_classes", 0),
            fondcart_present=manifest.get("fondcart_present", True),
        )

    zf = zipfile.ZipFile(store.raw_path(artifact))

    # XSD fingerprint gate — fail closed on unknown schema generations.
    for fam in ("FONDCART", "FONDPATRIMDISVAR", "FONDREGISTRO"):
        sha = artifact.xsd_sha256.get(fam)
        if sha is not None:
            check_xsd(fam, sha)

    snaps = []
    cart = _member_xml(zf, "FONDCART")
    if cart is not None:
        cart_name, cart_xml = cart
        pdv = _member_xml(zf, "FONDPATRIMDISVAR")
        snaps = parse_fondcart(
            cart_xml,
            artifact=artifact,
            member_name=cart_name,
            member_sha256=_member_sha(artifact, cart_name),
        )
        reconcile(snaps, pdv[1] if pdv else None)

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
    if cart is None and records is None:
        raise ParseError(
            f"artifact {artifact.source_id} has neither FONDCART nor "
            f"FONDREGISTRO members"
        )

    manifest = write_period(
        dataset_root, snaps, period=period,
        artifact_id=artifact.source_id, records=records,
    )
    return UpdateResult(
        period=period, artifact=artifact, artifact_new=is_new,
        exported=True,
        dataset_fingerprint=manifest["dataset_fingerprint"],
        registry_fingerprint=manifest.get("registry_fingerprint"),
        positions=manifest["positions"],
        quality_rows=manifest["quality_rows"],
        funds=manifest.get("funds", 0),
        share_classes=manifest.get("share_classes", 0),
        fondcart_present=manifest["fondcart_present"],
    )
