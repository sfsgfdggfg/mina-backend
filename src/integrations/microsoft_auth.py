from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import msal

from src.paths import REPO_ROOT


TENANT_ID_ENV = "MINAI_OUTLOOK_TENANT_ID"
CLIENT_ID_ENV = "MINAI_OUTLOOK_CLIENT_ID"
MAILBOX_ID_ENV = "MINAI_OUTLOOK_MAILBOX_ID"
TOKEN_CACHE_PATH_ENV = (
    "MINAI_OUTLOOK_TOKEN_CACHE_PATH"
)

AUTHORITY_BASE = (
    "https://login.microsoftonline.com"
)
CONSUMERS_TENANT = "consumers"

OUTLOOK_SCOPES = (
    "Mail.Read",
    "Mail.Send",
)


class MicrosoftAuthConfigurationError(
    ValueError
):
    pass


class MicrosoftAuthenticationError(
    RuntimeError
):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class MicrosoftAuthConfig:
    tenant_id: str
    client_id: str
    mailbox_id: str
    token_cache_path: Path

    @property
    def authority(self) -> str:
        return (
            f"{AUTHORITY_BASE}/"
            f"{self.tenant_id}"
        )

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> "MicrosoftAuthConfig":
        env = (
            environ
            if environ is not None
            else os.environ
        )

        tenant_id = _tenant_identity(
            env.get(TENANT_ID_ENV)
        )

        client_id = _required_uuid(
            env.get(CLIENT_ID_ENV),
            name=CLIENT_ID_ENV,
        )

        mailbox_id = _mailbox_identity(
            env.get(MAILBOX_ID_ENV)
        )

        cache_path = _external_cache_path(
            env.get(TOKEN_CACHE_PATH_ENV)
        )

        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            mailbox_id=mailbox_id,
            token_cache_path=cache_path,
        )


def _tenant_identity(
    value: str | None,
) -> str:
    normalized = (value or "").strip().lower()

    if normalized == CONSUMERS_TENANT:
        return CONSUMERS_TENANT

    return _required_uuid(
        normalized,
        name=TENANT_ID_ENV,
    )


def _required_uuid(
    value: str | None,
    *,
    name: str,
) -> str:
    normalized = (value or "").strip()

    if not normalized:
        raise MicrosoftAuthConfigurationError(
            f"{name} is required."
        )

    try:
        parsed = UUID(normalized)
    except ValueError as exc:
        raise MicrosoftAuthConfigurationError(
            f"{name} must be a UUID."
        ) from exc

    return str(parsed)


def _mailbox_identity(
    value: str | None,
) -> str:
    normalized = (value or "").strip().lower()

    if (
        not normalized
        or "@" not in normalized
        or any(
            character.isspace()
            for character in normalized
        )
    ):
        raise MicrosoftAuthConfigurationError(
            "MINAI_OUTLOOK_MAILBOX_ID must "
            "be a mailbox sign-in identity."
        )

    return normalized


def _external_cache_path(
    value: str | None,
) -> Path:
    raw = (value or "").strip()

    if not raw:
        raise MicrosoftAuthConfigurationError(
            "MINAI_OUTLOOK_TOKEN_CACHE_PATH "
            "is required."
        )

    path = Path(raw).expanduser()

    if not path.is_absolute():
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache path must "
            "be absolute."
        )

    if path.exists() and path.is_symlink():
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache must not "
            "be a symlink."
        )

    parent = path.parent

    if not parent.is_dir():
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache parent "
            "directory is unavailable."
        )

    current = Path(path.anchor)

    for part in path.parts[1:-1]:
        current = current / part

        if current.is_symlink():
            raise MicrosoftAuthConfigurationError(
                "Outlook token cache path "
                "contains a symlink."
            )

    resolved_parent = parent.resolve()
    repo_root = REPO_ROOT.resolve()

    try:
        resolved_parent.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache must be "
            "stored outside the repository."
        )

    return path


def _require_private_existing_cache(
    path: Path,
) -> None:
    if not path.exists():
        return

    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache metadata "
            "could not be read."
        ) from exc

    if os.name == "posix":
        if mode & 0o077:
            raise MicrosoftAuthConfigurationError(
                "Outlook token cache permissions "
                "must be owner-only."
            )


def _load_cache(
    path: Path,
):
    _require_private_existing_cache(path)

    cache = msal.SerializableTokenCache()

    if not path.exists():
        return cache

    try:
        serialized = path.read_text(
            encoding="utf-8"
        )
    except (OSError, UnicodeError) as exc:
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache could not "
            "be read."
        ) from exc

    try:
        cache.deserialize(serialized)
    except Exception as exc:
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache is invalid."
        ) from exc

    return cache


def _persist_cache(
    path: Path,
    cache,
) -> None:
    if not cache.has_state_changed:
        return

    serialized = cache.serialize()

    temp_path: Path | None = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".minai-outlook-cache-",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)

            if os.name == "posix":
                os.fchmod(
                    handle.fileno(),
                    0o600,
                )

            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temp_path,
            path,
        )

        if os.name == "posix":
            os.chmod(
                path,
                0o600,
            )

    except OSError as exc:
        raise MicrosoftAuthConfigurationError(
            "Outlook token cache could not "
            "be written."
        ) from exc

    finally:
        if (
            temp_path is not None
            and temp_path.exists()
        ):
            try:
                temp_path.unlink()
            except OSError:
                pass


def _application(
    config: MicrosoftAuthConfig,
    cache,
):
    return msal.PublicClientApplication(
        client_id=config.client_id,
        authority=config.authority,
        token_cache=cache,
    )


def _matching_accounts(
    app,
    mailbox_id: str,
) -> list[dict]:
    accounts = app.get_accounts(
        username=mailbox_id
    )

    return [
        account
        for account in accounts
        if (
            str(
                account.get(
                    "username",
                    "",
                )
            )
            .strip()
            .lower()
            == mailbox_id
        )
    ]


def acquire_silent_access_token(
    config: MicrosoftAuthConfig,
) -> str:
    cache = _load_cache(
        config.token_cache_path
    )

    app = _application(
        config,
        cache,
    )

    accounts = _matching_accounts(
        app,
        config.mailbox_id,
    )

    if len(accounts) != 1:
        raise MicrosoftAuthenticationError(
            "outlook_reauthentication_required"
        )

    result = app.acquire_token_silent(
        list(OUTLOOK_SCOPES),
        account=accounts[0],
    )

    _persist_cache(
        config.token_cache_path,
        cache,
    )

    if (
        not isinstance(result, dict)
        or not isinstance(
            result.get("access_token"),
            str,
        )
        or not result["access_token"].strip()
    ):
        raise MicrosoftAuthenticationError(
            "outlook_reauthentication_required"
        )

    return result["access_token"]


def interactive_device_login(
    config: MicrosoftAuthConfig,
    *,
    output_fn: Callable[[str], None] = print,
) -> None:
    cache = _load_cache(
        config.token_cache_path
    )

    app = _application(
        config,
        cache,
    )

    flow = app.initiate_device_flow(
        scopes=list(OUTLOOK_SCOPES)
    )

    if (
        not isinstance(flow, dict)
        or not flow.get("user_code")
        or not isinstance(
            flow.get("message"),
            str,
        )
    ):
        raise MicrosoftAuthenticationError(
            "outlook_device_flow_unavailable"
        )

    output_fn(flow["message"])

    result = app.acquire_token_by_device_flow(
        flow
    )

    if (
        not isinstance(result, dict)
        or not isinstance(
            result.get("access_token"),
            str,
        )
        or not result["access_token"].strip()
    ):
        raise MicrosoftAuthenticationError(
            "outlook_device_login_failed"
        )

    accounts = _matching_accounts(
        app,
        config.mailbox_id,
    )

    if len(accounts) != 1:
        raise MicrosoftAuthenticationError(
            "outlook_authorized_account_mismatch"
        )

    _persist_cache(
        config.token_cache_path,
        cache,
    )
