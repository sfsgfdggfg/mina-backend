"""Focused regressions for the canonical pilot regression runner itself."""

from __future__ import annotations

import io
import os
import socket
from unittest.mock import patch

from src.simulation.pilot_regression_suite import CANONICAL_SUITES, Suite, run_suites


OBSOLETE_EVALUATORS = {
    "evaluate_quote_case_workflow_persistence",
    "evaluate_quote_case_api_contract",
    "evaluate_quote_send_safety_regression",
    "evaluate_final_quote_consistency_block",
    "evaluate_supplier_response_required_state",
}


def evaluate_pilot_regression_suite_regressions() -> dict:
    failures: list[str] = []

    output = io.StringIO()
    if run_suites((Suite("pass", lambda: {"passed": True}),), output) != 0:
        failures.append("all-pass run did not return zero")

    executed: list[str] = []
    output = io.StringIO()
    suites = (
        Suite("first failure", lambda: {"passed": False, "failures": ["expected"]}),
        Suite("subsequent", lambda: executed.append("subsequent") or {"passed": True}),
    )
    if run_suites(suites, output) == 0:
        failures.append("failed run returned zero")
    if executed != ["subsequent"]:
        failures.append("runner stopped after a failure")
    if "Failed suites: first failure" not in output.getvalue():
        failures.append("summary did not name failed suite")

    secret = "runner-regression-secret-value"
    output = io.StringIO()

    def raise_secret() -> object:
        raise RuntimeError(secret)

    with patch.dict(os.environ, {"OPENAI_API_KEY": secret}, clear=False):
        if run_suites((Suite("exception", raise_secret),), output) == 0:
            failures.append("exception did not become a failure")
    if "raised RuntimeError" not in output.getvalue():
        failures.append("exception type was not safely summarized")
    if secret in output.getvalue():
        failures.append("secret value was printed")

    output = io.StringIO()
    run_suites(
        (Suite("secret result", lambda: {"passed": False, "failures": [secret]}),),
        output,
    )
    if secret in output.getvalue():
        failures.append("secret value from a failure result was printed")

    names = {suite.name.lower() for suite in CANONICAL_SUITES}
    required_areas = {
        "privacy", "pilot access", "pilot launcher", "safe api",
        "extraction confirmation", "customer identity", "data provenance",
        "repository data path normalization",
        "operational data injection",
        "synthetic pilot rehearsal",
        "sanitized historical replay",
        "pilot readiness assessment",
        "guided pilot readiness evidence",
        "pilot scope", "persistence", "recovery", "atomic",
        "state transition concurrency", "supplier rfq lifecycle",
        "manual rfq sent", "supplier response ingestion", "quote approval",
        "pricing policy",
        "microsoft delegated outlook authentication",
        "read-only outlook graph ingestion",
        "controlled outlook inbound gate",
        "supplier response privacy boundary",
        "deterministic outlook inbound router",
        "controlled outlook supplier reply pull",
        "live outlook smoke evidence contract",
        "controlled live outlook smoke runner",
        "global outlook route history idempotency",
        "controlled outlook operator pull",
        "quote case repository", "final customer quote output",
        "pilot operator", "runtime reproducibility preflight",
    }
    for area in required_areas:
        if not any(area in name for name in names):
            failures.append(f"canonical membership lacks required area: {area}")

    callable_names = {suite.run.__name__ for suite in CANONICAL_SUITES}
    stale = sorted(OBSOLETE_EVALUATORS.intersection(callable_names))
    if stale:
        failures.append("obsolete evaluators are canonical: " + ", ".join(stale))

    network_attempts: list[object] = []

    def reject_network(*args: object, **kwargs: object) -> object:
        network_attempts.append((args, kwargs))
        raise AssertionError("external network attempted")

    with patch.dict(os.environ, {}, clear=True), patch.object(socket, "create_connection", reject_network), patch.object(socket.socket, "connect", reject_network):
        smoke_output = io.StringIO()
        smoke_code = run_suites(CANONICAL_SUITES, smoke_output)
    if smoke_code != 0:
        failures.append("canonical suites do not pass without OPENAI_API_KEY")
    if network_attempts:
        failures.append("runner attempted external network access")

    return {
        "name": "Canonical pilot regression runner",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pilot_regression_suite_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
