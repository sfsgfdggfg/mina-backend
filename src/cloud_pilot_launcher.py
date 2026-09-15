from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from src.core.pilot_access import PilotAccessConfigurationError
from src.pilot_launcher import build_uvicorn_options, run as run_pilot


DEFAULT_CLOUD_STORAGE_ROOT = Path("/data")
CLOUD_STORAGE_ROOT_ENV = "MINAI_CLOUD_STORAGE_ROOT"


def _resolve_storage_root(environ: Mapping[str, str]) -> Path:
    raw = (environ.get(CLOUD_STORAGE_ROOT_ENV) or str(DEFAULT_CLOUD_STORAGE_ROOT)).strip()
    root = Path(raw).expanduser()
    if not root.is_absolute():
        raise PilotAccessConfigurationError(
            "MINAI_CLOUD_STORAGE_ROOT must be an absolute path."
        )
    return root.resolve(strict=False)


def _require_under_storage_root(
    environ: Mapping[str, str],
    key: str,
    storage_root: Path,
    *,
    required: bool,
) -> None:
    raw = (environ.get(key) or "").strip()
    if not raw:
        if required:
            raise PilotAccessConfigurationError(
                f"{key} is required for the cloud pilot."
            )
        return
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise PilotAccessConfigurationError(
            f"{key} must be an absolute path for the cloud pilot."
        )
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(storage_root)
    except ValueError as exc:
        raise PilotAccessConfigurationError(
            f"{key} must remain under the persistent cloud storage root."
        ) from exc


def build_cloud_pilot_environment(
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_environment is None else base_environment)

    port = (env.get("PORT") or env.get("MINAI_PILOT_PORT") or "8000").strip()
    try:
        parsed_port = int(port)
    except ValueError as exc:
        raise PilotAccessConfigurationError(
            "Cloud pilot PORT must be an integer between 1 and 65535."
        ) from exc
    if not 1 <= parsed_port <= 65535:
        raise PilotAccessConfigurationError(
            "Cloud pilot PORT must be an integer between 1 and 65535."
        )

    env["MINAI_PILOT_BIND_HOST"] = "0.0.0.0"
    env["MINAI_PILOT_PORT"] = str(parsed_port)
    env["MINAI_PILOT_EDGE_HTTPS"] = "1"

    if (env.get("MINAI_OUTBOUND_MODE") or "shadow").strip().casefold() != "shadow":
        raise PilotAccessConfigurationError(
            "Cloud pilot launcher requires MINAI_OUTBOUND_MODE=shadow."
        )

    storage_root = _resolve_storage_root(env)
    _require_under_storage_root(
        env,
        "MINAI_PILOT_DB_PATH",
        storage_root,
        required=True,
    )
    _require_under_storage_root(
        env,
        "MINAI_PILOT_DATA_DIR",
        storage_root,
        required=True,
    )
    _require_under_storage_root(
        env,
        "MINAI_OUTLOOK_TOKEN_CACHE_PATH",
        storage_root,
        required=False,
    )
    return env


def safe_cloud_summary(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        "pilot_mode": (environ.get("MINAI_PILOT_MODE") or "").strip(),
        "outbound_mode": (environ.get("MINAI_OUTBOUND_MODE") or "shadow").strip(),
        "edge_https": (environ.get("MINAI_PILOT_EDGE_HTTPS") or "").strip(),
        "bind_host": (environ.get("MINAI_PILOT_BIND_HOST") or "").strip(),
        "port": (environ.get("MINAI_PILOT_PORT") or "").strip(),
        "base_url": (environ.get("MINAI_PILOT_BASE_URL") or "").strip(),
        "storage_root": str(_resolve_storage_root(environ)),
        "database_path": (environ.get("MINAI_PILOT_DB_PATH") or "").strip(),
        "data_pack_root": (environ.get("MINAI_PILOT_DATA_DIR") or "").strip(),
        "web_shell_enabled": (environ.get("MINAI_WEB_SHELL_ENABLED") or "").strip(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch or validate the controlled MINAI cloud pilot."
    )
    parser.add_argument("--check-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        effective = build_cloud_pilot_environment()
        if args.check_only:
            build_uvicorn_options(effective)
            print(json.dumps(safe_cloud_summary(effective), ensure_ascii=False, sort_keys=True))
            return 0
        os.environ.clear()
        os.environ.update(effective)
        run_pilot(os.environ)
    except PilotAccessConfigurationError as exc:
        print(f"Cloud pilot configuration error: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
