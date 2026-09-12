from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Mapping
from uuid import uuid4

from src.core.attachment_intake_policy import MAX_ATTACHMENT_FILE_BYTES
from src.core.pilot_store import validate_pilot_database_configuration
from src.paths import REPO_ROOT, data_path


class AirRateDocumentStorageError(RuntimeError):
    pass


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def resolve_air_rate_storage_directory(
    environ: Mapping[str, str] | None = None,
) -> Path:
    env = environ if environ is not None else os.environ
    configured = (env.get("MINAI_AIR_RATE_STORAGE_DIR") or "").strip()
    if configured:
        candidate = Path(configured)
        if _truthy(env.get("MINAI_PILOT_MODE")):
            if not candidate.is_absolute():
                raise AirRateDocumentStorageError(
                    "MINAI_AIR_RATE_STORAGE_DIR must be absolute in pilot mode."
                )
            if _is_within(candidate.resolve(strict=False), REPO_ROOT.resolve()):
                raise AirRateDocumentStorageError(
                    "Pilot air-rate documents must be stored outside the repository."
                )
        return candidate
    if _truthy(env.get("MINAI_PILOT_MODE")):
        return validate_pilot_database_configuration(env).parent / "air-rate-sources"
    return data_path("pilot", "air-rate-sources")


class AirRateDocumentStore:
    """Protected content-addressed storage for verified commercial-air tariff PDFs."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else resolve_air_rate_storage_directory()

    def _ensure_root(self) -> None:
        if self.root.exists() and (self.root.is_symlink() or not self.root.is_dir()):
            raise AirRateDocumentStorageError("Air-rate storage path must be a real directory.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError as exc:
            raise AirRateDocumentStorageError("Could not harden air-rate storage directory permissions.") from exc

    @staticmethod
    def _validate_sha256(sha256_hex: str) -> str:
        normalized = str(sha256_hex or "").strip().lower()
        if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
            raise AirRateDocumentStorageError("Invalid air-rate SHA-256 identity.")
        return normalized

    def path_for_sha256(self, sha256_hex: str) -> Path:
        digest = self._validate_sha256(sha256_hex)
        return self.root / f"{digest}.pdf"

    def store_verified_pdf(self, *, sha256_hex: str, content: bytes) -> Path:
        if not content:
            raise AirRateDocumentStorageError("Air-rate PDF content must not be empty.")
        if len(content) > MAX_ATTACHMENT_FILE_BYTES:
            raise AirRateDocumentStorageError("Air-rate PDF exceeds the controlled file-size limit.")
        digest = hashlib.sha256(content).hexdigest()
        if digest != self._validate_sha256(sha256_hex):
            raise AirRateDocumentStorageError("Air-rate PDF fingerprint mismatch.")
        self._ensure_root()
        target = self.path_for_sha256(digest)
        if target.exists():
            if target.is_symlink() or not target.is_file():
                raise AirRateDocumentStorageError("Stored air-rate document path is not a regular file.")
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise AirRateDocumentStorageError("Stored air-rate PDF failed fingerprint verification.")
            target.chmod(0o600)
            return target
        temporary = self.root / f".{digest}.{uuid4().hex}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            target.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def is_stored(self, sha256_hex: str) -> bool:
        path = self.path_for_sha256(sha256_hex)
        if not path.exists() or path.is_symlink() or not path.is_file():
            return False
        size = path.stat().st_size
        return 0 < size <= MAX_ATTACHMENT_FILE_BYTES

    def read_verified_pdf(self, sha256_hex: str) -> bytes:
        path = self.path_for_sha256(sha256_hex)
        if not self.is_stored(sha256_hex):
            raise AirRateDocumentStorageError("Air-rate PDF is not available in protected storage.")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != self._validate_sha256(sha256_hex):
            raise AirRateDocumentStorageError("Stored air-rate PDF failed fingerprint verification.")
        return content
