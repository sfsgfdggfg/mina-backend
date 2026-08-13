from __future__ import annotations

import json
from unittest.mock import patch

from src.core.pilot_access import PilotAccessConfigurationError
from src.pilot_launcher import run


def _valid_env(host: str = "127.0.0.1") -> dict[str, str]:
    return {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": host,
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32,10.42.0.0/16",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps(
            {"Pilot Operator": "fake-pilot-token-0000000000000000"}
        ),
    }


def evaluate_pilot_launcher_regressions() -> dict:
    failures: list[str] = []

    rejected_configs = (
        ("absent pilot mode", {k: v for k, v in _valid_env().items() if k != "MINAI_PILOT_MODE"}),
        ("false pilot mode", {**_valid_env(), "MINAI_PILOT_MODE": "false"}),
        ("missing bind host", {k: v for k, v in _valid_env().items() if k != "MINAI_PILOT_BIND_HOST"}),
        ("IPv4 wildcard", {**_valid_env(), "MINAI_PILOT_BIND_HOST": "0.0.0.0"}),
        ("IPv6 wildcard", {**_valid_env(), "MINAI_PILOT_BIND_HOST": "::"}),
        ("public IP", {**_valid_env(), "MINAI_PILOT_BIND_HOST": "8.8.8.8"}),
        ("malformed operator JSON", {**_valid_env(), "MINAI_PILOT_OPERATORS_JSON": "{"}),
        ("short operator token", {**_valid_env(), "MINAI_PILOT_OPERATORS_JSON": json.dumps({"Pilot Operator": "short"})}),
        ("invalid allowed network", {**_valid_env(), "MINAI_PILOT_ALLOWED_NETWORKS": "8.8.8.0/24"}),
        ("non-integer port", {**_valid_env(), "MINAI_PILOT_PORT": "eight-thousand"}),
        ("out-of-range port", {**_valid_env(), "MINAI_PILOT_PORT": "65536"}),
    )
    for name, env in rejected_configs:
        with patch("src.pilot_launcher.uvicorn.run") as uvicorn_run:
            try:
                run(env)
            except PilotAccessConfigurationError:
                pass
            else:
                failures.append(f"launcher accepted {name}")
            if uvicorn_run.called:
                failures.append(f"Uvicorn started for {name}")

    valid_configs = (
        ("loopback", _valid_env(), "127.0.0.1", 8000),
        ("private IP", {**_valid_env("10.42.1.9"), "MINAI_PILOT_PORT": "8123"}, "10.42.1.9", 8123),
    )
    for name, env, host, port in valid_configs:
        with patch("src.pilot_launcher.uvicorn.run") as uvicorn_run:
            run(env)
        try:
            uvicorn_run.assert_called_once_with(
                app="src.api:app",
                host=host,
                port=port,
                reload=False,
                proxy_headers=False,
                forwarded_allow_ips="",
            )
        except AssertionError as exc:
            failures.append(f"{name} Uvicorn contract mismatch: {exc}")

    return {
        "name": "Fail-closed shadow pilot launcher",
        "passed": len(failures) == 0,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pilot_launcher_regressions()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
