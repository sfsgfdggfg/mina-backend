from __future__ import annotations

from typing import Any, Dict

from src.core.data_health_registry import run_data_health_checks


def build_data_health_summary() -> Dict[str, Any]:
    checks = run_data_health_checks()

    total_checks = len(checks)
    valid_checks = sum(
        1
        for result in checks.values()
        if result.get("valid") is True
    )
    invalid_checks = total_checks - valid_checks
    total_errors = sum(
        len(result.get("errors") or [])
        for result in checks.values()
    )
    total_warnings = sum(
        len(result.get("warnings") or [])
        for result in checks.values()
    )

    return {
        "overall_valid": invalid_checks == 0,
        "total_checks": total_checks,
        "valid_checks": valid_checks,
        "invalid_checks": invalid_checks,
        "total_errors": total_errors,
        "total_warnings": total_warnings,
        "checks": checks,
    }
