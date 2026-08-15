from __future__ import annotations

import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_MAIN_PATH = REPO_ROOT / "main.py"
LEGACY_RAW_EMAIL_PATHS = {"/parse-email", "/parse-email/"}


def _fresh_runtime_simulation_imports() -> tuple[list[str], str | None]:
    probe = """
import json
import sys

import main
import src.api

loaded = sorted(
    name
    for name in sys.modules
    if name == "src.simulation"
    or name.startswith("src.simulation.")
)
print(json.dumps(loaded))
""".strip()

    env = os.environ.copy()
    env["MINAI_PILOT_MODE"] = "0"
    env.pop("MINAI_PILOT_DATA_DIR", None)

    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "fresh controlled API import timed out"

    if completed.returncode != 0:
        return [], "fresh controlled API import failed"

    output_lines = [
        line.strip()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    if not output_lines:
        return [], "fresh controlled API import produced no result"

    try:
        loaded = json.loads(output_lines[-1])
    except json.JSONDecodeError:
        return [], "fresh controlled API import result was invalid"

    if not isinstance(loaded, list):
        return [], "fresh controlled API import result was invalid"

    return [str(name) for name in loaded], None


def evaluate_safe_api_entrypoint_regressions() -> dict:
    failures: list[str] = []

    root_main = importlib.import_module("main")
    controlled_api = importlib.import_module("src.api")

    if root_main.app is not controlled_api.app:
        failures.append(
            "root main.app is not the controlled src.api.app object"
        )

    route_paths = {
        route.path
        for route in controlled_api.app.routes
        if hasattr(route, "path")
    }

    exposed_legacy_paths = sorted(
        route_paths.intersection(LEGACY_RAW_EMAIL_PATHS)
    )
    if exposed_legacy_paths:
        failures.append(
            "legacy raw-email route is still exposed: "
            + ", ".join(exposed_legacy_paths)
        )

    if "/run-test-suite" in route_paths:
        failures.append(
            "HTTP regression execution route is still exposed"
        )

    if "/supplier-rfqs/{rfq_id}/simulate-response" in route_paths:
        failures.append(
            "supplier response simulation route is still exposed"
        )

    api_source = (
        Path(__file__).resolve().parents[1] / "api.py"
    ).read_text(encoding="utf-8")

    forbidden_runtime_imports = (
        "src.simulation.ai_email_test_cases",
        "src.simulation.test_reporter",
        "src.simulation.supplier_simulator",
        "_regressions import",
    )

    if any(
        item in api_source
        for item in forbidden_runtime_imports
    ):
        failures.append(
            "controlled API still imports regression execution harness"
        )

    loaded_simulation_modules, probe_failure = (
        _fresh_runtime_simulation_imports()
    )

    if probe_failure:
        failures.append(probe_failure)
    elif loaded_simulation_modules:
        failures.append(
            "controlled runtime transitively imports src.simulation modules"
        )

    root_module = ast.parse(
        ROOT_MAIN_PATH.read_text(encoding="utf-8"),
        filename=str(ROOT_MAIN_PATH),
    )

    fastapi_constructions = [
        node
        for node in ast.walk(root_module)
        if isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == "FastAPI"
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == "FastAPI"
        )
    ]

    if fastapi_constructions:
        failures.append(
            "root main.py constructs a second FastAPI application"
        )

    return {
        "name": "Single controlled FastAPI entry point",
        "passed": len(failures) == 0,
        "failures": failures,
    }
