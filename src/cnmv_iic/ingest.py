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
    positions: int
    quality_rows: int
    funds: int
    share_classes: int
    daily_observations: int
    quarterly_metrics: int
    patrimony_records: int
    fondcart_present: bool
    fondmens_present: bool
    fondtrim_present: bool
    fondpatrimdisvar_present: bool


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
    needs_daily = manifest.get("daily_fingerprint") is None
    needs_quarterly = manifest.get("quarterly_fingerprint") is None
    needs_patrimony = manifest.get("patrimony_fingerprint") is None
    if not is_new and not (
        needs_positions or needs_registry or needs_daily
        or needs_quarterly or needs_patrimony
    ):
        return UpdateResult(
            period=period, artifact=artifact, artifact_new=False,
            exported=False,
            dataset_fingerprint=manifest["dataset_fingerprint"],
            registry_fingerprint=manifest.get("registry_fingerprint"),
            daily_fingerprint=manifest.get("daily_fingerprint"),
            quarterly_fingerprint=manifest.get("quarterly_fingerprint"),
            patrimony_fingerprint=manifest.get("patrimony_fingerprint"),
            positions=manifest["positions"],
            quality_rows=manifest["quality_rows"],
            funds=manifest.get("funds", 0),
            share_classes=manifest.get("share_classes", 0),
            daily_observations=manifest.get("daily_observations", 0),
            quarterly_metrics=manifest.get("quarterly_metrics", 0),
            patrimony_records=manifest.get("patrimony_records", 0),
            fondcart_present=manifest.get("fondcart_present", True),
            fondmens_present=manifest.get("fondmens_present", False),
            fondtrim_present=manifest.get("fondtrim_present", False),
            fondpatrimdisvar_present=manifest.get(
                "fondpatrimdisvar_present", False),
        )

    zf = zipfile.ZipFile(store.raw_path(artifact))

    # XSD fingerprint gate — fail closed on unknown schema generations.
    for fam in ("FONDCART", "FONDPATRIMDISVAR", "FONDREGISTRO", "FONDMENS",
                "FONDTRIM"):
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
    )
    return UpdateResult(
        period=period, artifact=artifact, artifact_new=is_new,
        exported=True,
        dataset_fingerprint=manifest["dataset_fingerprint"],
        registry_fingerprint=manifest.get("registry_fingerprint"),
        daily_fingerprint=manifest.get("daily_fingerprint"),
        quarterly_fingerprint=manifest.get("quarterly_fingerprint"),
        patrimony_fingerprint=manifest.get("patrimony_fingerprint"),
        positions=manifest["positions"],
        quality_rows=manifest["quality_rows"],
        funds=manifest.get("funds", 0),
        share_classes=manifest.get("share_classes", 0),
        daily_observations=manifest.get("daily_observations", 0),
        quarterly_metrics=manifest.get("quarterly_metrics", 0),
        patrimony_records=manifest.get("patrimony_records", 0),
        fondcart_present=manifest["fondcart_present"],
        fondmens_present=manifest.get("fondmens_present", False),
        fondtrim_present=manifest.get("fondtrim_present", False),
        fondpatrimdisvar_present=manifest.get(
            "fondpatrimdisvar_present", False),
    )
