"""Focused deterministic regressions for the synthetic pilot rehearsal."""

from __future__ import annotations

import io
import os
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src.core.pricing_policy import AGENCY_PRICING_POLICY_ENV
from src.paths import data_path
from src.simulation.pilot_rehearsal import TOKEN, main as rehearsal_main, run_rehearsal


def _data_snapshot() -> dict[str, bytes]:
    root = data_path()
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@contextmanager
def _without_external_rehearsal_authority():
    keys = ("OPENAI_API_KEY", AGENCY_PRICING_POLICY_ENV)
    saved = {key: os.environ.pop(key, None) for key in keys}
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)


def evaluate_pilot_rehearsal_regressions() -> dict:
    failures: list[str] = []
    before = _data_snapshot()
    with _without_external_rehearsal_authority():
        result = run_rehearsal()
        output = io.StringIO()
        success_exit = rehearsal_main(output)
        failed_output = io.StringIO()
        failure_exit = rehearsal_main(failed_output, injected_failure="after-confirmation")
    after = _data_snapshot()

    expected_checks = {
        "temporary DB only": "temporary DB was not isolated",
        "network isolation": "network was not blocked",
        "pilot authentication": "synthetic bearer-token authorization failed",
        "authenticated synthetic operator": "authenticated operator was not the synthetic operator",
        "body identity conflicts with authenticated identity": "body identity did not conflict with authenticated identity",
        "authenticated authority overrides body": "extraction confirmation used body identity",
        "RFQ authenticated approval": "RFQ approval used body identity",
        "manual send evidence": "manual-send evidence used body identity",
        "quote approval": "quote approval used body identity",
        "durable authenticated authority": "persisted authority did not match authenticated identity",
        "no RFQ before confirmation": "RFQ existed before confirmation",
        "manual send requires approval": "manual-send approval gate failed",
        "quote progression injected data": "quote progression ignored injection",
        "provenance fail-closed": "tampered quote resume did not fail closed",
        "response prerequisite": "supplier response prerequisite failed",
        "durable restart": "state did not survive restart",
        "durable approved current case": "approved case was stale after restart",
        "current quote case": "post-approval case was not current",
        "quote send safety recomputed": "quote-send safety was not refreshed",
        "final manual handoff": "approved final manual handoff was not produced",
        "durable final manual handoff": "final manual handoff did not survive restart",
        "ADR scope": "ADR did not fail closed",
        "reefer scope": "reefer did not fail closed",
        "controlled outbound surface": "controlled outbound route policy was incorrect",
        "no OPENAI_API_KEY": "rehearsal required an OpenAI key",
        "temporary cleanup": "temporary artifacts survived",
    }
    if not result.passed:
        failures.append("full rehearsal did not pass")
    for check, message in expected_checks.items():
        if not result.checks.get(check):
            failures.append(message)
    if before != after:
        failures.append("repository operational/provenance data changed")
    db_path = Path(str(result.evidence.get("db_path", "")))
    if db_path.exists() or db_path == data_path("pilot", "minai_pilot.sqlite3"):
        failures.append("rehearsal database was not temporary and removed")

    if success_exit != 0 or "Synthetic pilot rehearsal: PASS" not in output.getvalue():
        failures.append("success CLI contract failed")
    safe_output = output.getvalue()
    if TOKEN in safe_output or "secret" in safe_output.lower() or "Bearer " in safe_output:
        failures.append("success output exposed credential material")

    if failure_exit == 0:
        failures.append("controlled injected failure exited zero")
    failure_text = failed_output.getvalue()
    if "FAIL injected failure: controlled rehearsal check failed" not in failure_text:
        failures.append("controlled failure was not safely staged")
    if TOKEN in failure_text or "Traceback" in failure_text or "@customer.invalid" in failure_text:
        failures.append("controlled failure output leaked sensitive detail")

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_pilot_rehearsal_regressions()
    if result["passed"]:
        print("Synthetic pilot rehearsal regressions: PASS")
        return 0
    print(f"Synthetic pilot rehearsal regressions: FAIL ({len(result['failures'])} checks)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
