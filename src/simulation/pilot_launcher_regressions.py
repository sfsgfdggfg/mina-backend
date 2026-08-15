from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.core.pilot_access import PilotAccessConfigurationError
from src.pilot_launcher import run


def _valid_env(
    data_dir: Path,
    host: str = "127.0.0.1",
) -> dict[str, str]:
    return {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": host,
        "MINAI_PILOT_DATA_DIR": str(data_dir),
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32,10.42.0.0/16",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps(
            {"Pilot Operator": "fake-pilot-token-0000000000000000"}
        ),
    }


def _write_pilot_data_pack(root: Path) -> Path:
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    customer = [{
        "customer_name": "Launcher Synthetic Customer",
        "active": True,
        "aliases": [],
        "trusted_sender_addresses": [],
        "trusted_sender_domains": ["launcher.invalid"],
        "operational_notes": [],
    }]

    suppliers = [{
        "supplier_name": "Launcher Synthetic Supplier",
        "active": True,
        "role": "primary",
        "route_regions": ["international"],
        "countries": ["Türkiye", "Almanya"],
        "service_types": ["FTL"],
        "equipment_types": ["Tenteli"],
        "special_capabilities": [],
        "priority_routes": [],
        "contacts": [{
            "email": "quotes@launcher.invalid",
            "active": True,
            "is_primary": True,
        }],
        "reliability_score": 0.9,
        "price_score": 0.8,
        "speed_score": 0.8,
        "notes": "Synthetic launcher fixture.",
    }]

    (data_dir / "customer_memory.json").write_text(
        json.dumps(customer),
        encoding="utf-8",
    )
    (data_dir / "supplier_capabilities.json").write_text(
        json.dumps(suppliers),
        encoding="utf-8",
    )

    # Launcher validates safe pack structure. Semantic provenance
    # authorization remains a separate operational/readiness boundary.
    (data_dir / "provenance_registry.json").write_text(
        "{}",
        encoding="utf-8",
    )

    return root


def evaluate_pilot_launcher_regressions() -> dict:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(
        prefix="minai-pilot-launcher-"
    ) as temporary:
        external_root = Path(temporary)
        data_dir = _write_pilot_data_pack(
            external_root / "pilot-data"
        )

        base_env = _valid_env(data_dir)

        missing_data_dir = dict(base_env)
        missing_data_dir.pop("MINAI_PILOT_DATA_DIR")

        incomplete_dir = external_root / "incomplete"
        incomplete_data_dir = incomplete_dir / "data"
        incomplete_data_dir.mkdir(parents=True)
        (incomplete_data_dir / "customer_memory.json").write_text(
            "{}", encoding="utf-8"
        )

        repo_inside_dir = Path(".pilot-launcher-regression-data")
        try:
            _write_pilot_data_pack(repo_inside_dir)

            rejected_configs = (
                (
                    "absent pilot mode",
                    {
                        k: v
                        for k, v in base_env.items()
                        if k != "MINAI_PILOT_MODE"
                    },
                ),
                (
                    "false pilot mode",
                    {**base_env, "MINAI_PILOT_MODE": "false"},
                ),
                (
                    "missing bind host",
                    {
                        k: v
                        for k, v in base_env.items()
                        if k != "MINAI_PILOT_BIND_HOST"
                    },
                ),
                (
                    "missing pilot data directory",
                    missing_data_dir,
                ),
                (
                    "incomplete pilot data pack",
                    {
                        **base_env,
                        "MINAI_PILOT_DATA_DIR": str(
                            incomplete_dir.resolve()
                        ),
                    },
                ),
                (
                    "repository-owned pilot data",
                    {
                        **base_env,
                        "MINAI_PILOT_DATA_DIR": str(
                            repo_inside_dir.resolve()
                        ),
                    },
                ),
                (
                    "IPv4 wildcard",
                    {**base_env, "MINAI_PILOT_BIND_HOST": "0.0.0.0"},
                ),
                (
                    "IPv6 wildcard",
                    {**base_env, "MINAI_PILOT_BIND_HOST": "::"},
                ),
                (
                    "public IP",
                    {**base_env, "MINAI_PILOT_BIND_HOST": "8.8.8.8"},
                ),
                (
                    "malformed operator JSON",
                    {**base_env, "MINAI_PILOT_OPERATORS_JSON": "{"},
                ),
                (
                    "short operator token",
                    {
                        **base_env,
                        "MINAI_PILOT_OPERATORS_JSON": json.dumps(
                            {"Pilot Operator": "short"}
                        ),
                    },
                ),
                (
                    "invalid allowed network",
                    {
                        **base_env,
                        "MINAI_PILOT_ALLOWED_NETWORKS": "8.8.8.0/24",
                    },
                ),
                (
                    "non-integer port",
                    {**base_env, "MINAI_PILOT_PORT": "eight-thousand"},
                ),
                (
                    "out-of-range port",
                    {**base_env, "MINAI_PILOT_PORT": "65536"},
                ),
            )

            for name, env in rejected_configs:
                with patch(
                    "src.pilot_launcher.uvicorn.run"
                ) as uvicorn_run:
                    try:
                        run(env)
                    except PilotAccessConfigurationError:
                        pass
                    else:
                        failures.append(
                            f"launcher accepted {name}"
                        )
                    if uvicorn_run.called:
                        failures.append(
                            f"Uvicorn started for {name}"
                        )

            valid_configs = (
                (
                    "loopback",
                    _valid_env(data_dir),
                    "127.0.0.1",
                    8000,
                ),
                (
                    "private IP",
                    {
                        **_valid_env(data_dir, "10.42.1.9"),
                        "MINAI_PILOT_PORT": "8123",
                    },
                    "10.42.1.9",
                    8123,
                ),
            )

            for name, env, host, port in valid_configs:
                with patch(
                    "src.pilot_launcher.uvicorn.run"
                ) as uvicorn_run:
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
                    failures.append(
                        f"{name} Uvicorn contract mismatch: {exc}"
                    )
        finally:
            shutil.rmtree(repo_inside_dir, ignore_errors=True)

    return {
        "name": "Fail-closed shadow pilot launcher",
        "passed": len(failures) == 0,
        "failures": failures,
    }



if __name__ == "__main__":
    result = evaluate_pilot_launcher_regressions()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
