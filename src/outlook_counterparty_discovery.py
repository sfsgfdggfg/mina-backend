from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import dotenv_values

from src.core.master_data_repository import InMemoryMasterDataRepository
from src.integrations.microsoft_auth import (
    CLIENT_ID_ENV,
    MAILBOX_ID_ENV,
    OUTLOOK_BASIC_READ_SCOPES,
    TENANT_ID_ENV,
    TOKEN_CACHE_PATH_ENV,
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationError,
    interactive_device_login,
)
from src.integrations.outlook_graph import (
    MAX_COUNTERPARTY_DISCOVERY_DAYS,
    MAX_HISTORY_MESSAGES,
    MIN_COUNTERPARTY_DISCOVERY_MESSAGES,
    OutlookGraphReadError,
)
from src.paths import REPO_ROOT
from src.workflow.counterparty_discovery import (
    CounterpartyDiscoveryAuthorizationError,
    run_outlook_counterparty_discovery,
)


AUTH_PROFILE_KEYS = frozenset({
    TENANT_ID_ENV,
    CLIENT_ID_ENV,
    MAILBOX_ID_ENV,
    TOKEN_CACHE_PATH_ENV,
})


class OutlookDiscoveryProfileError(RuntimeError):
    pass


def _resolve_external_profile(raw_path: str | Path) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        raise OutlookDiscoveryProfileError(
            "Outlook discovery auth profile must use an absolute path."
        )
    if not candidate.is_file():
        raise OutlookDiscoveryProfileError(
            "Outlook discovery auth profile is missing."
        )
    current = candidate
    while current != current.parent:
        if current.is_symlink():
            raise OutlookDiscoveryProfileError(
                "Outlook discovery auth profile must not traverse symlinks."
            )
        current = current.parent
    resolved = candidate.resolve(strict=True)
    if os.name == "posix" and resolved.stat().st_mode & 0o077:
        raise OutlookDiscoveryProfileError(
            "Outlook discovery auth profile permissions must be owner-only."
        )
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise OutlookDiscoveryProfileError(
        "Outlook discovery auth profile must remain outside the repository."
    )


def build_readonly_auth_config(
    auth_env_file: str | Path,
) -> MicrosoftAuthConfig:
    profile_path = _resolve_external_profile(auth_env_file)
    parsed = dotenv_values(profile_path, interpolate=False)
    values: dict[str, str] = {}
    for key, value in parsed.items():
        if key not in AUTH_PROFILE_KEYS:
            raise OutlookDiscoveryProfileError(
                f"Outlook discovery auth profile contains forbidden key: {key}"
            )
        if value is None:
            raise OutlookDiscoveryProfileError(
                f"Outlook discovery auth profile key {key} has no value."
            )
        values[str(key)] = str(value)

    missing = sorted(key for key in AUTH_PROFILE_KEYS if not values.get(key))
    if missing:
        raise OutlookDiscoveryProfileError(
            "Outlook discovery auth profile is missing required keys: "
            + ", ".join(missing)
        )

    cache_literal = values[TOKEN_CACHE_PATH_ENV].strip()
    if not Path(cache_literal).is_absolute():
        raise OutlookDiscoveryProfileError(
            "Outlook discovery token-cache path must be a literal absolute path."
        )

    values["MINAI_OUTBOUND_MODE"] = "shadow"
    try:
        validated = MicrosoftAuthConfig.from_environment(values)
    except MicrosoftAuthConfigurationError as exc:
        raise OutlookDiscoveryProfileError(str(exc)) from exc
    config = MicrosoftAuthConfig(
        tenant_id=validated.tenant_id,
        client_id=validated.client_id,
        mailbox_id=validated.mailbox_id,
        token_cache_path=validated.token_cache_path,
        scopes=OUTLOOK_BASIC_READ_SCOPES,
    )
    if tuple(config.scopes) != OUTLOOK_BASIC_READ_SCOPES:
        raise OutlookDiscoveryProfileError(
            "Outlook discovery authorization must resolve to Mail.ReadBasic only."
        )
    return config


def _parse_timestamp(raw: str) -> datetime:
    normalized = raw.strip().replace("Z", "+00:00")
    try:
        value = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "Timestamp must be ISO 8601 with an explicit timezone."
        ) from exc
    if value.tzinfo is None:
        raise argparse.ArgumentTypeError(
            "Timestamp must include an explicit timezone."
        )
    return value


def _validate_window(start_at: datetime, end_at: datetime) -> None:
    if end_at <= start_at:
        raise ValueError("History end must be after history start.")
    if end_at - start_at > timedelta(days=MAX_COUNTERPARTY_DISCOVERY_DAYS):
        raise ValueError(
            "Counterparty discovery history window cannot exceed "
            f"{MAX_COUNTERPARTY_DISCOVERY_DAYS} days."
        )


def _safe_check_payload(
    *, config: MicrosoftAuthConfig, auth_env_file: str | Path,
) -> dict[str, object]:
    return {
        "auth_profile": _resolve_external_profile(auth_env_file).name,
        "mailbox_id": config.mailbox_id,
        "permissions": list(config.scopes),
        "token_cache_exists": config.token_cache_path.exists(),
        "outbound_mode": "shadow",
        "raw_message_storage": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only Outlook counterparty discovery before MINAI pilot cutover."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("check", "auth"):
        command = subparsers.add_parser(name)
        command.add_argument("--auth-env", required=True)

    discover = subparsers.add_parser("discover")
    discover.add_argument("--auth-env", required=True)
    discover.add_argument("--start-at", required=True, type=_parse_timestamp)
    discover.add_argument("--end-at", required=True, type=_parse_timestamp)
    discover.add_argument("--max-messages", type=int, default=5000)
    discover.add_argument(
        "--agency-alias",
        action="append",
        default=[],
        help="Additional agency mailbox alias; may be repeated.",
    )
    discover.add_argument(
        "--authorization-confirmed",
        action="store_true",
        help="Confirm explicit authorization to read the selected mailbox history.",
    )
    return parser


def _run_check(args: argparse.Namespace) -> int:
    config = build_readonly_auth_config(args.auth_env)
    print(json.dumps(_safe_check_payload(config=config, auth_env_file=args.auth_env)))
    return 0


def _run_auth(args: argparse.Namespace) -> int:
    config = build_readonly_auth_config(args.auth_env)
    interactive_device_login(config)
    print("Outlook read-only authorization cached securely.")
    print("Permissions cached: " + ", ".join(config.scopes) + ".")
    return 0


def _run_discover(args: argparse.Namespace) -> int:
    _validate_window(args.start_at, args.end_at)
    if not (
        MIN_COUNTERPARTY_DISCOVERY_MESSAGES
        <= args.max_messages
        <= MAX_HISTORY_MESSAGES
    ):
        raise ValueError(
            "max-messages must be between "
            f"{MIN_COUNTERPARTY_DISCOVERY_MESSAGES} and {MAX_HISTORY_MESSAGES}."
        )
    config = build_readonly_auth_config(args.auth_env)
    payload = run_outlook_counterparty_discovery(
        config=config,
        start_at=args.start_at,
        end_at=args.end_at,
        max_messages=args.max_messages,
        authorization_confirmed=args.authorization_confirmed,
        master_repository=InMemoryMasterDataRepository(),
        agency_addresses=args.agency_alias,
    )
    print(json.dumps(payload, default=str, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            return _run_check(args)
        if args.command == "auth":
            return _run_auth(args)
        if args.command == "discover":
            return _run_discover(args)
        raise ValueError("Unsupported discovery command.")
    except OutlookDiscoveryProfileError as exc:
        print(f"Outlook discovery: FAIL ({exc})")
        return 2
    except CounterpartyDiscoveryAuthorizationError:
        print("Outlook discovery: FAIL (historical_mailbox_authorization_required)")
        return 2
    except MicrosoftAuthenticationError as exc:
        print(f"Outlook discovery: FAIL ({exc.code})")
        return 2
    except OutlookGraphReadError as exc:
        print(f"Outlook discovery: FAIL ({exc.code})")
        return 2
    except ValueError as exc:
        print(f"Outlook discovery: FAIL ({exc})")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
