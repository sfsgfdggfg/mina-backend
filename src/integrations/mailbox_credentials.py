from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Literal, Mapping

from cryptography.fernet import Fernet, InvalidToken
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from src.paths import REPO_ROOT

MAILBOX_CREDENTIAL_KEY_ENV = "MINAI_MAILBOX_CREDENTIAL_KEY"
MAILBOX_CREDENTIAL_PATH_ENV = "MINAI_MAILBOX_CREDENTIAL_PATH"
IMAP_DEFAULT_HOST_ENV = "MINAI_IMAP_DEFAULT_HOST"
IMAP_DEFAULT_PORT_ENV = "MINAI_IMAP_DEFAULT_PORT"
IMAP_DEFAULT_USERNAME_ENV = "MINAI_IMAP_DEFAULT_USERNAME"
IMAP_DEFAULT_CERTIFICATE_ENV = "MINAI_IMAP_DEFAULT_CERTIFICATE_SHA256"
SCHEMA_VERSION = "1.0"
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")


class MailboxCredentialConfigurationError(RuntimeError):
    pass


class MailboxCredentialStoreError(RuntimeError):
    pass


def resolve_imap_setup_defaults(
    mailbox_id: str | None = None, environ: Mapping[str, str] | None = None,
) -> dict:
    env = environ if environ is not None else os.environ
    mailbox = (mailbox_id or "").strip().casefold()
    host = (env.get(IMAP_DEFAULT_HOST_ENV) or "").strip().lower().rstrip(".")
    if not host and mailbox.count("@") == 1:
        domain = mailbox.rsplit("@", 1)[1]
        if domain and not any(ch.isspace() for ch in domain):
            host = f"mail.{domain}"
    raw_port = (env.get(IMAP_DEFAULT_PORT_ENV) or "993").strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise MailboxCredentialConfigurationError(
            f"{IMAP_DEFAULT_PORT_ENV} must be an integer."
        ) from exc
    if not 1 <= port <= 65535:
        raise MailboxCredentialConfigurationError(
            f"{IMAP_DEFAULT_PORT_ENV} must be between 1 and 65535."
        )
    username = (env.get(IMAP_DEFAULT_USERNAME_ENV) or "").strip() or mailbox
    certificate = normalize_certificate_fingerprint(env.get(IMAP_DEFAULT_CERTIFICATE_ENV))
    return {
        "host": host or None, "port": port, "username": username or None,
        "certificate_sha256": certificate,
        "host_source": "deployment_default" if env.get(IMAP_DEFAULT_HOST_ENV) else (
            "mailbox_domain_fallback" if host else "unavailable"
        ),
    }


def normalize_certificate_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace(":", "")
    if not normalized:
        return None
    if not _FINGERPRINT_RE.fullmatch(normalized):
        raise ValueError("IMAP certificate SHA-256 fingerprint must contain 64 hex characters.")
    return normalized


class ImapMailboxCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["imap"] = "imap"
    mailbox_id: str = Field(min_length=3, max_length=254)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=993, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=320)
    password: SecretStr
    certificate_sha256: str | None = None

    @field_validator("mailbox_id")
    @classmethod
    def normalize_mailbox(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
            raise ValueError("IMAP mailbox identity must be a valid email address.")
        return normalized

    @field_validator("host")
    @classmethod
    def normalize_host(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if not normalized or any(ch.isspace() for ch in normalized) or "/" in normalized:
            raise ValueError("IMAP host must be a hostname without scheme or path.")
        return normalized

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or any(ch in normalized for ch in "\r\n\x00"):
            raise ValueError("IMAP username is invalid.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if not raw or any(ch in raw for ch in "\r\n\x00"):
            raise ValueError("IMAP password is required.")
        if len(raw) > 1024:
            raise ValueError("IMAP password is too long.")
        return value

    @field_validator("certificate_sha256", mode="before")
    @classmethod
    def normalize_fingerprint(cls, value):
        return normalize_certificate_fingerprint(value)

    def safe_summary(self) -> dict:
        return {
            "provider": "imap",
            "configured": True,
            "mailbox_id": self.mailbox_id,
            "host": self.host,
            "port": self.port,
            "tls_mode": "implicit_tls",
            "certificate_pin_configured": self.certificate_sha256 is not None,
            "password_exposed": False,
        }


def _external_private_path(raw: str | None) -> Path:
    value = (raw or "").strip()
    if not value:
        raise MailboxCredentialConfigurationError(
            f"{MAILBOX_CREDENTIAL_PATH_ENV} is required for IMAP mailbox setup."
        )
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise MailboxCredentialConfigurationError("Mailbox credential path must be absolute.")
    if path.exists() and path.is_symlink():
        raise MailboxCredentialConfigurationError("Mailbox credential path must not be a symlink.")
    parent = path.parent
    if not parent.is_dir():
        raise MailboxCredentialConfigurationError("Mailbox credential directory is unavailable.")
    current = Path(path.anchor)
    for part in path.parts[1:-1]:
        current = current / part
        if current.is_symlink():
            raise MailboxCredentialConfigurationError(
                "Mailbox credential path contains a symlink."
            )
    try:
        parent.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise MailboxCredentialConfigurationError(
            "Mailbox credentials must be stored outside the repository."
        )
    return path


def _fernet(raw: str | None) -> Fernet:
    value = (raw or "").strip()
    if not value:
        raise MailboxCredentialConfigurationError(
            f"{MAILBOX_CREDENTIAL_KEY_ENV} is required for encrypted IMAP credentials."
        )
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise MailboxCredentialConfigurationError(
            f"{MAILBOX_CREDENTIAL_KEY_ENV} must be a valid Fernet key."
        ) from exc


class MailboxCredentialStore:
    def __init__(self, *, path: Path, fernet: Fernet) -> None:
        self.path = path
        self.fernet = fernet

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "MailboxCredentialStore":
        env = environ if environ is not None else os.environ
        return cls(
            path=_external_private_path(env.get(MAILBOX_CREDENTIAL_PATH_ENV)),
            fernet=_fernet(env.get(MAILBOX_CREDENTIAL_KEY_ENV)),
        )

    def configured(self) -> bool:
        return self.path.is_file()

    def _require_private_file(self) -> None:
        if not self.path.exists():
            return
        if not self.path.is_file() or self.path.is_symlink():
            raise MailboxCredentialStoreError("Mailbox credential file is invalid.")
        if os.name == "posix" and self.path.stat().st_mode & 0o077:
            raise MailboxCredentialStoreError(
                "Mailbox credential file permissions must be owner-only."
            )

    def save_imap(self, credential: ImapMailboxCredential) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "provider": "imap",
            "mailbox_id": credential.mailbox_id,
            "host": credential.host,
            "port": credential.port,
            "username": credential.username,
            "password": credential.password.get_secret_value(),
            "certificate_sha256": credential.certificate_sha256,
        }
        plaintext = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        token = self.fernet.encrypt(plaintext)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self.path.parent,
                prefix=".minai-mailbox-credentials-",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                if os.name == "posix":
                    os.fchmod(handle.fileno(), 0o600)
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            if os.name == "posix":
                os.chmod(self.path, 0o600)
        except OSError as exc:
            raise MailboxCredentialStoreError(
                "Encrypted mailbox credentials could not be written."
            ) from exc
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def load_imap(self) -> ImapMailboxCredential:
        self._require_private_file()
        if not self.path.exists():
            raise MailboxCredentialStoreError("IMAP mailbox credentials are not configured.")
        try:
            token = self.path.read_bytes()
            plaintext = self.fernet.decrypt(token)
            payload = json.loads(plaintext.decode("utf-8"))
        except (OSError, InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
            raise MailboxCredentialStoreError(
                "Encrypted mailbox credentials could not be read."
            ) from exc
        if payload.get("schema_version") != SCHEMA_VERSION or payload.get("provider") != "imap":
            raise MailboxCredentialStoreError("Mailbox credential schema is unsupported.")
        try:
            return ImapMailboxCredential.model_validate(
                {
                    "provider": "imap",
                    "mailbox_id": payload.get("mailbox_id"),
                    "host": payload.get("host"),
                    "port": payload.get("port"),
                    "username": payload.get("username"),
                    "password": payload.get("password"),
                    "certificate_sha256": payload.get("certificate_sha256"),
                }
            )
        except ValueError as exc:
            raise MailboxCredentialStoreError("Mailbox credential payload is invalid.") from exc
