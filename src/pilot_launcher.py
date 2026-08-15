from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from pathlib import Path

import uvicorn

from src.core.pilot_access import (
    PilotAccessConfigurationError,
    pilot_mode_enabled,
    validate_pilot_configuration,
)
from src.core.operational_data import (
    OperationalDataSourceConfigurationError,
    operational_data_sources_from_environment,
)


PILOT_ASGI_APP = "src.api:app"
DEFAULT_PILOT_PORT = 8000
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def _load_pilot_port(environ: Mapping[str, str]) -> int:
    raw_port = (environ.get("MINAI_PILOT_PORT") or "").strip()
    if not raw_port:
        return DEFAULT_PILOT_PORT
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_PORT must be an integer between 1 and 65535."
        ) from exc
    if not 1 <= port <= 65535:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_PORT must be an integer between 1 and 65535."
        )
    return port


def _load_pilot_tls_configuration(
    environ: Mapping[str, str],
    host: str,
) -> tuple[str | None, str | None]:
    bind_ip = ipaddress.ip_address(host)

    if bind_ip.is_loopback:
        return None, None

    raw_cert = (
        environ.get("MINAI_PILOT_TLS_CERTFILE")
        or ""
    ).strip()
    raw_key = (
        environ.get("MINAI_PILOT_TLS_KEYFILE")
        or ""
    ).strip()

    if not raw_cert or not raw_key:
        raise PilotAccessConfigurationError(
            "Private-network pilot binding requires "
            "TLS certificate and key files."
        )

    resolved_files: list[Path] = []

    for raw_path in (raw_cert, raw_key):
        resolved = Path(
            raw_path
        ).expanduser().resolve()

        if not resolved.is_file():
            raise PilotAccessConfigurationError(
                "Pilot TLS certificate or key file "
                "is missing."
            )

        try:
            resolved.relative_to(
                REPOSITORY_ROOT
            )
        except ValueError:
            pass
        else:
            raise PilotAccessConfigurationError(
                "Pilot TLS files must remain outside "
                "the repository."
            )

        resolved_files.append(resolved)

    return (
        str(resolved_files[0]),
        str(resolved_files[1]),
    )


def run(environ: Mapping[str, str] | None = None) -> None:
    env = environ if environ is not None else os.environ
    if not pilot_mode_enabled(env):
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_MODE must be enabled for the shadow pilot launcher."
        )

    validate_pilot_configuration(env)
    try:
        operational_data_sources_from_environment(
            env,
            require_external=True,
        )
    except OperationalDataSourceConfigurationError as exc:
        raise PilotAccessConfigurationError(
            "Controlled pilot operational data configuration is invalid."
        ) from exc

    host = (env.get("MINAI_PILOT_BIND_HOST") or "").strip()
    port = _load_pilot_port(env)
    tls_certfile, tls_keyfile = (
        _load_pilot_tls_configuration(
            env,
            host,
        )
    )

    uvicorn_options = {
        "app": PILOT_ASGI_APP,
        "host": host,
        "port": port,
        "reload": False,
        "proxy_headers": False,
        "forwarded_allow_ips": "",
    }

    if (
        tls_certfile is not None
        and tls_keyfile is not None
    ):
        uvicorn_options.update(
            {
                "ssl_certfile": tls_certfile,
                "ssl_keyfile": tls_keyfile,
            }
        )

    uvicorn.run(**uvicorn_options)


if __name__ == "__main__":
    run()
