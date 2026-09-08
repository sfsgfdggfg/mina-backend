from __future__ import annotations

import argparse
import json
import os
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path

from dotenv import dotenv_values

from src.core.pilot_access import PilotAccessConfigurationError
from src.paths import REPO_ROOT
from src.pilot_launcher import build_uvicorn_options, run as run_pilot


class PilotProfileConfigurationError(RuntimeError):
    pass


ALLOWED_OVERLAY_KEYS = frozenset({
    "MINAI_PILOT_BIND_HOST",
    "MINAI_PILOT_PORT",
    "MINAI_PILOT_BASE_URL",
    "MINAI_PILOT_TLS_CERTFILE",
    "MINAI_PILOT_TLS_KEYFILE",
})
ALLOWED_OVERLAY_PREFIXES = (
    "MINAI_WEB_",
)
REQUIRED_CORE_KEYS = (
    "MINAI_PILOT_MODE",
    "MINAI_PILOT_DB_PATH",
    "MINAI_PILOT_DATA_DIR",
)
HOST_ENV_ALLOWLIST = frozenset({
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "TEMP",
    "TMP",
    "TMPDIR",
    "TZ",
})


def _allowed_overlay_key(key: str) -> bool:
    return (
        key in ALLOWED_OVERLAY_KEYS
        or any(key.startswith(prefix) for prefix in ALLOWED_OVERLAY_PREFIXES)
    )


def _resolve_external_env_file(raw_path: str | Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        raise PilotProfileConfigurationError(
            "Pilot profile env files must use absolute paths."
        )
    if not candidate.is_file():
        raise PilotProfileConfigurationError(
            "Pilot profile env file is missing."
        )
    current = candidate
    while current != current.parent:
        if current.is_symlink():
            raise PilotProfileConfigurationError(
                "Pilot profile env files must not traverse symlinks."
            )
        current = current.parent
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise PilotProfileConfigurationError(
        "Pilot profile env files must remain outside the repository."
    )


def _load_env_file(path: Path) -> dict[str, str]:
    parsed = dotenv_values(path, interpolate=False)
    values: dict[str, str] = {}
    for key, value in parsed.items():
        if value is None:
            raise PilotProfileConfigurationError(
                f"Pilot profile key {key} has no value."
            )
        normalized = str(value)
        if (
            normalized.startswith(("\\{", "\\["))
            and normalized.endswith(("\\}", "\\]"))
        ):
            parts = shlex.split(normalized, posix=True)
            if len(parts) != 1:
                raise PilotProfileConfigurationError(
                    f"Pilot profile key {key} uses invalid shell escaping."
                )
            normalized = parts[0]
        values[str(key)] = normalized
    return values

def _sanitized_base_environment(
    environ: Mapping[str, str],
) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in environ.items()
        if key in HOST_ENV_ALLOWLIST
    }


def build_profile_environment(
    *,
    core_env_file: str | Path,
    overlay_env_files: Sequence[str | Path] = (),
    base_environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    core_path = _resolve_external_env_file(core_env_file)
    core = _load_env_file(core_path)
    missing = [key for key in REQUIRED_CORE_KEYS if not core.get(key)]
    if missing:
        raise PilotProfileConfigurationError(
            "Core pilot profile is missing required keys: " + ", ".join(missing)
        )

    source_environment = (
        os.environ if base_environment is None else base_environment
    )
    effective = _sanitized_base_environment(source_environment)
    effective.update(core)
    source_labels = {key: core_path.name for key in core}

    for raw_overlay in overlay_env_files:
        overlay_path = _resolve_external_env_file(raw_overlay)
        overlay = _load_env_file(overlay_path)
        forbidden = sorted(key for key in overlay if not _allowed_overlay_key(key))
        if forbidden:
            raise PilotProfileConfigurationError(
                "Pilot overlay may define web/transport keys only; rejected: "
                + ", ".join(forbidden)
            )
        effective.update(overlay)
        source_labels.update({key: overlay_path.name for key in overlay})

    return effective, source_labels

def safe_profile_summary(
    environ: Mapping[str, str],
    source_labels: Mapping[str, str],
) -> dict[str, object]:
    return {
        "pilot_mode": (environ.get("MINAI_PILOT_MODE") or "").strip(),
        "database_path": (environ.get("MINAI_PILOT_DB_PATH") or "").strip(),
        "data_pack_root": (environ.get("MINAI_PILOT_DATA_DIR") or "").strip(),
        "outbound_mode": (environ.get("MINAI_OUTBOUND_MODE") or "shadow").strip(),
        "bind_host": (environ.get("MINAI_PILOT_BIND_HOST") or "").strip(),
        "port": (environ.get("MINAI_PILOT_PORT") or "8000").strip(),
        "base_url": (environ.get("MINAI_PILOT_BASE_URL") or "").strip(),
        "web_shell_enabled": (environ.get("MINAI_WEB_SHELL_ENABLED") or "").strip(),
        "database_source": source_labels.get("MINAI_PILOT_DB_PATH"),
        "data_pack_source": source_labels.get("MINAI_PILOT_DATA_DIR"),
    }


def validate_profile_files(
    *,
    core_env_file: str | Path,
    overlay_env_files: Sequence[str | Path] = (),
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, object]:
    effective, sources = build_profile_environment(
        core_env_file=core_env_file,
        overlay_env_files=overlay_env_files,
        base_environment=base_environment,
    )
    build_uvicorn_options(effective)
    return safe_profile_summary(effective, sources)

def launch_profile(
    *,
    core_env_file: str | Path,
    overlay_env_files: Sequence[str | Path] = (),
    base_environment: Mapping[str, str] | None = None,
) -> None:
    effective, _ = build_profile_environment(
        core_env_file=core_env_file,
        overlay_env_files=overlay_env_files,
        base_environment=base_environment,
    )
    build_uvicorn_options(effective)
    os.environ.clear()
    os.environ.update(effective)
    run_pilot(os.environ)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch a controlled pilot from isolated external env profiles."
    )
    parser.add_argument("--core-env", required=True)
    parser.add_argument("--overlay-env", action="append", default=[])
    parser.add_argument("--check-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.check_only:
            summary = validate_profile_files(
                core_env_file=args.core_env,
                overlay_env_files=args.overlay_env,
            )
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0
        launch_profile(
            core_env_file=args.core_env,
            overlay_env_files=args.overlay_env,
        )
    except (PilotProfileConfigurationError, PilotAccessConfigurationError) as exc:
        print(f"Pilot profile configuration error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
