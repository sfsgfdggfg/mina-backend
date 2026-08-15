from __future__ import annotations

import ast
import importlib
from pathlib import Path


ROOT_MAIN_PATH = Path(__file__).resolve().parents[2] / "main.py"
LEGACY_RAW_EMAIL_PATHS = {"/parse-email", "/parse-email/"}


def evaluate_safe_api_entrypoint_regressions() -> dict:
    failures: list[str] = []

    root_main = importlib.import_module("main")
    controlled_api = importlib.import_module("src.api")

    if root_main.app is not controlled_api.app:
        failures.append("root main.app is not the controlled src.api.app object")

    route_paths = {
        route.path
        for route in controlled_api.app.routes
        if hasattr(route, "path")
    }
    exposed_legacy_paths = sorted(route_paths.intersection(LEGACY_RAW_EMAIL_PATHS))
    if exposed_legacy_paths:
        failures.append(
            "legacy raw-email route is still exposed: "
            + ", ".join(exposed_legacy_paths)
        )

    if "/run-test-suite" in route_paths:
        failures.append("HTTP regression execution route is still exposed")

    if "/supplier-rfqs/{rfq_id}/simulate-response" in route_paths:
        failures.append("supplier response simulation route is still exposed")

    api_source = (
        Path(__file__).resolve().parents[1] / "api.py"
    ).read_text(encoding="utf-8")

    forbidden_runtime_imports = (
        "src.simulation.ai_email_test_cases",
        "src.simulation.test_reporter",
        "src.simulation.supplier_simulator",
        "_regressions import",
    )

    if any(item in api_source for item in forbidden_runtime_imports):
        failures.append(
            "controlled API still imports regression execution harness"
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
        failures.append("root main.py constructs a second FastAPI application")

    return {
        "name": "Single controlled FastAPI entry point",
        "passed": len(failures) == 0,
        "failures": failures,
    }
