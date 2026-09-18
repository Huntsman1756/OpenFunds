"""Immutable artifact store.

Layout under ``root``::

    raw/<sha256>.zip        # content-addressed, write-once
    artifacts.jsonl         # append-only SourceArtifact ledger

Rules (ADR-004):
- Artifact identity is the SHA-256 of the ZIP bytes, not the token URL.
- Same bytes re-downloaded -> same artifact, no new ledger entry.
- Same period with different bytes -> new ledger entry with ``supersedes``
  pointing at the previous artifact id for that period. Never overwrite.
- Atomic write: download to temp file, hash, fsync, rename.
"""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

LEDGER = "artifacts.jsonl"


@dataclass(frozen=True)
class ArtifactMember:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceArtifact:
    source_id: str            # "cnmv-iic-zip/<period>/<sha256>"
    provider: str             # "cnmv"
    source_family: str        # "descarga-informacion-individual"
    period: str               # "YYYY-MM"
    source_page: str
    source_url_ephemeral: str
    retrieved_at: str         # ISO-8601 UTC
    content_type: str | None
    size_bytes: int
    sha256: str
    members: tuple[ArtifactMember, ...]
    xsd_sha256: dict[str, str]
    supersedes: str | None = None

    def member(self, prefix: str) -> ArtifactMember | None:
        p = prefix.upper()
        for m in self.members:
            base = m.name.rsplit("/", 1)[-1].upper()
            stem = base.rsplit(".", 1)[0]
            if stem == p or stem.startswith(p + "_"):
                if m.name.lower().endswith(".xml"):
                    return m
        return None


def member_family(name: str) -> str | None:
    """Normalize 'FONDCART_202512.xml' / 'FONDCART.XML' -> 'FONDCART'."""
    base = name.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0].upper()
    stem = stem.split("_", 1)[0]
    return stem or None


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        (self.root / "raw").mkdir(parents=True, exist_ok=True)

    @property
    def ledger_path(self) -> Path:
        return self.root / LEDGER

    def load(self) -> list[SourceArtifact]:
        if not self.ledger_path.exists():
            return []
        out = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                d["members"] = tuple(ArtifactMember(**m) for m in d["members"])
                out.append(SourceArtifact(**d))
        return out

    def latest_for_period(
        self, period: str, *, provider: str = "cnmv",
        source_family: str | None = None,
    ) -> SourceArtifact | None:
        arts = [
            a for a in self.load()
            if a.period == period and a.provider == provider
            and (source_family is None or a.source_family == source_family)
        ]
        return arts[-1] if arts else None

    def get(self, sha: str) -> SourceArtifact | None:
        for a in self.load():
            if a.sha256 == sha:
                return a
        return None

    def raw_path(self, artifact: SourceArtifact) -> Path:
        return self.root / "raw" / f"{artifact.sha256}.zip"

    def put(
        self,
        *,
        period: str,
        source_page: str,
        source_url: str,
        content_type: str | None,
        data: bytes,
        retrieved_at: datetime | None = None,
        provider: str = "cnmv",
        source_family: str = "descarga-informacion-individual",
        source_id_prefix: str = "cnmv-iic-zip",
    ) -> tuple[SourceArtifact, bool]:
        """Store artifact bytes; returns (artifact, created_new_version).

        Idempotent: identical bytes for an already-registered
        (period, provider, source_family) return the existing artifact
        and ``False``. ``period`` is the artifact's natural dedupe key —
        a CNMV publication month or a provider snapshot date.
        """
        digest = sha256(data).hexdigest()
        prior = self.latest_for_period(
            period, provider=provider, source_family=source_family)
        if prior is not None and prior.sha256 == digest:
            return prior, False

        raw = self.root / "raw" / f"{digest}.zip"
        if not raw.exists():
            fd, tmp = tempfile.mkstemp(dir=self.root / "raw", suffix=".part")
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, raw)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)

        zf = zipfile.ZipFile(raw)
        members = tuple(
            ArtifactMember(i.filename, i.file_size, sha256(zf.read(i)).hexdigest())
            for i in zf.infolist()
        )
        xsd_hashes = {}
        for m in members:
            if m.name.lower().endswith(".xsd"):
                fam = member_family(m.name)
                if fam:
                    xsd_hashes[fam] = m.sha256

        artifact = SourceArtifact(
            source_id=f"{source_id_prefix}/{period}/{digest}",
            provider=provider,
            source_family=source_family,
            period=period,
            source_page=source_page,
            source_url_ephemeral=source_url,
            retrieved_at=(retrieved_at or datetime.now(UTC)).isoformat(),
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            members=members,
            xsd_sha256=xsd_hashes,
            supersedes=prior.source_id if prior else None,
        )
        with open(self.ledger_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(artifact), sort_keys=True) + "\n")
        return artifact, True

    def verify_integrity(self, artifact: SourceArtifact) -> bool:
        raw = self.raw_path(artifact)
        return raw.exists() and sha256(raw.read_bytes()).hexdigest() == artifact.sha256
