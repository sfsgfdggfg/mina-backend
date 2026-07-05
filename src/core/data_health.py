from __future__ import annotations

from typing import Any, Dict

from src.core.commodity_dictionary_validator import validate_commodity_dictionary_file
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.hs_commodity_map_validator import validate_hs_commodity_map_file
from src.core.supplier_capability_validator import validate_supplier_capabilities_file


def build_data_health_summary() -> Dict[str, Any]:
    checks = {
        "commodity_dictionary": validate_commodity_dictionary_file(),
        "supplier_capabilities": validate_supplier_capabilities_file(),
        "customer_memory": validate_customer_memory_file(),
        "hs_commodity_map": validate_hs_commodity_map_file(),
    }

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
