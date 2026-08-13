from __future__ import annotations

import os
from collections.abc import Mapping

import uvicorn

from src.core.pilot_access import (
    PilotAccessConfigurationError,
    pilot_mode_enabled,
    validate_pilot_configuration,
)


PILOT_ASGI_APP = "src.api:app"
DEFAULT_PILOT_PORT = 8000


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


def run(environ: Mapping[str, str] | None = None) -> None:
    env = environ if environ is not None else os.environ
    if not pilot_mode_enabled(env):
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_MODE must be enabled for the shadow pilot launcher."
        )

    validate_pilot_configuration(env)
    host = (env.get("MINAI_PILOT_BIND_HOST") or "").strip()
    port = _load_pilot_port(env)

    uvicorn.run(
        app=PILOT_ASGI_APP,
        host=host,
        port=port,
        reload=False,
        proxy_headers=False,
        forwarded_allow_ips="",
    )


if __name__ == "__main__":
    run()
