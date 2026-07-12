from src.core.commodity_dictionary_validator import validate_commodity_dictionary_file
from src.core.supplier_capability_validator import validate_supplier_capabilities_file
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.hs_commodity_map_validator import validate_hs_commodity_map_file
from src.core.data_health import build_data_health_summary
from src.core.data_health_labels import get_data_health_check_label
from src.core.data_health_registry import get_data_health_check_keys, get_data_health_check_labels, get_data_health_checks


def determine_result_type(result: dict) -> str:
    if result.get("management_review_draft"):
        return "management_review"

    if result.get("clarification_draft"):
        return "clarification"

    if result.get("quote_draft"):
        return "quote"

    return "unknown"


def evaluate_test_result(test_case: dict, result: dict) -> dict:
    expected = test_case.get("expected", {})
    failures = []

    shipment = result["shipment"]
    equipment_decision = result["equipment_decision"]
    risk_assessment = result["risk_assessment"]
    missing_info = result.get("missing_info")
    action_recommendation = result.get("action_recommendation")
    supplier_selection = result.get("supplier_selection")
    supplier_quote = result.get("supplier_quote")
    operational_consistency = result.get("operational_consistency")
    commodity_profile = result.get("commodity_profile")

    actual_result_type = determine_result_type(result)

    expected_result_type = expected.get("result_type")
    if expected_result_type and actual_result_type != expected_result_type:
        failures.append(
            f"result_type expected {expected_result_type}, got {actual_result_type}"
        )

    expected_equipment = expected.get("equipment")
    if expected_equipment and equipment_decision.selected_equipment != expected_equipment:
        failures.append(
            f"equipment expected {expected_equipment}, got {equipment_decision.selected_equipment}"
        )

    expected_service_type = expected.get("service_type")
    if expected_service_type and shipment.service_type != expected_service_type:
        failures.append(
            f"service_type expected {expected_service_type}, got {shipment.service_type}"
        )

    expected_commodity = expected.get("commodity")
    if expected_commodity and shipment.commodity != expected_commodity:
        failures.append(
            f"commodity expected {expected_commodity}, got {shipment.commodity}"
        )

    expected_commodity_profile = expected.get("commodity_profile")
    if expected_commodity_profile:
        actual_profile_commodity = (
            commodity_profile.get("canonical_commodity")
            if isinstance(commodity_profile, dict)
            else None
        )

        if actual_profile_commodity != expected_commodity_profile:
            failures.append(
                f"commodity_profile expected {expected_commodity_profile}, got {actual_profile_commodity}"
            )

    expected_commodity_profile_keys = expected.get("commodity_profile_keys")
    if expected_commodity_profile_keys:
        actual_operational_profile = (
            commodity_profile.get("operational_profile", {})
            if isinstance(commodity_profile, dict)
            else {}
        )

        for key in expected_commodity_profile_keys:
            if key not in actual_operational_profile:
                failures.append(
                    f"commodity_profile operational_profile key expected {key}, got keys {sorted(actual_operational_profile.keys())}"
                )

    expected_commodity_profile_missing_fields = expected.get("commodity_profile_missing_fields")
    if expected_commodity_profile_missing_fields:
        actual_operational_profile = (
            commodity_profile.get("operational_profile", {})
            if isinstance(commodity_profile, dict)
            else {}
        )
        actual_profile_missing_fields = actual_operational_profile.get("missing_info_fields", [])

        for field in expected_commodity_profile_missing_fields:
            if field not in actual_profile_missing_fields:
                failures.append(
                    f"commodity_profile missing_info field expected {field}, got {actual_profile_missing_fields}"
                )

    expected_commodity_profile_action_checklist_contains = expected.get("commodity_profile_action_checklist_contains")
    if expected_commodity_profile_action_checklist_contains:
        actual_operational_profile = (
            commodity_profile.get("operational_profile", {})
            if isinstance(commodity_profile, dict)
            else {}
        )
        actual_profile_checklist = actual_operational_profile.get("action_checklist", [])

        for expected_item in expected_commodity_profile_action_checklist_contains:
            if not any(expected_item in checklist_item for checklist_item in actual_profile_checklist):
                failures.append(
                    f"commodity_profile action checklist item containing {expected_item} not found; got {actual_profile_checklist}"
                )

    for field_name in [
        "gtip_code",
        "hs_chapter",
        "hs_heading",
        "hs_subheading",
        "gtip_detected_from_email",
    ]:
        if field_name in expected:
            expected_value = expected.get(field_name)
            actual_value = getattr(shipment, field_name, None)

            if actual_value != expected_value:
                failures.append(
                    f"{field_name} expected {expected_value}, got {actual_value}"
                )

    expected_risk_level = expected.get("risk_level")
    if expected_risk_level and risk_assessment.risk_level != expected_risk_level:
        failures.append(
            f"risk_level expected {expected_risk_level}, got {risk_assessment.risk_level}"
        )
    
    expected_action_type = expected.get("action_type")
    if expected_action_type:
        actual_action_type = (
            action_recommendation.action_type
            if action_recommendation
            else None
        )

        if actual_action_type != expected_action_type:
            failures.append(
                f"action_type expected {expected_action_type}, got {actual_action_type}"
            )
    
    expected_action_checklist_contains = expected.get("action_checklist_contains")
    if expected_action_checklist_contains:
        actual_checklist = (
            action_recommendation.checklist
            if action_recommendation
            else []
        )

        for expected_item in expected_action_checklist_contains:
            if not any(expected_item in checklist_item for checklist_item in actual_checklist):
                failures.append(
                    f"action checklist item containing {expected_item} not found; got {actual_checklist}"
                )
    
    expected_customer_memory_matched = expected.get("customer_memory_matched")
    if expected_customer_memory_matched is not None:
        customer_memory = result.get("customer_memory")
        actual_matched = customer_memory.matched if customer_memory else False

        if actual_matched != expected_customer_memory_matched:
            failures.append(
                f"customer_memory_matched expected {expected_customer_memory_matched}, got {actual_matched}"
            )

    expected_supplier_name = expected.get("expected_supplier_name")
    if expected_supplier_name:
        selected_suppliers = (
            supplier_selection.get("selected_suppliers", [])
            if isinstance(supplier_selection, dict)
            else []
        )

        actual_selected_supplier = (
            selected_suppliers[0].get("supplier_name")
            if selected_suppliers
            else None
        )

        if actual_selected_supplier != expected_supplier_name:
            failures.append(
                f"selected supplier expected {expected_supplier_name}, got {actual_selected_supplier}"
            )

        actual_quote_supplier = (
            supplier_quote.supplier_name
            if supplier_quote
            else None
        )

        if actual_quote_supplier != expected_supplier_name:
            failures.append(
                f"supplier_quote supplier expected {expected_supplier_name}, got {actual_quote_supplier}"
            )

    expected_operational_warning_contains = expected.get("operational_warning_contains")
    if expected_operational_warning_contains:
        actual_warnings = (
            operational_consistency.get("warnings", [])
            if isinstance(operational_consistency, dict)
            else []
        )

        if not any(expected_operational_warning_contains in warning for warning in actual_warnings):
            failures.append(
                f"operational warning containing {expected_operational_warning_contains} not found; got {actual_warnings}"
            )

    expected_operational_error_contains = expected.get("operational_error_contains")
    if expected_operational_error_contains:
        actual_errors = (
            operational_consistency.get("errors", [])
            if isinstance(operational_consistency, dict)
            else []
        )

        if not any(expected_operational_error_contains in error for error in actual_errors):
            failures.append(
                f"operational error containing {expected_operational_error_contains} not found; got {actual_errors}"
            )

    expected_missing_fields = expected.get("missing_fields")
    if expected_missing_fields:
        actual_missing_fields = missing_info.missing_fields if missing_info else []

        for field in expected_missing_fields:
            if field not in actual_missing_fields:
                failures.append(
                    f"missing field expected {field}, got {actual_missing_fields}"
                )

    return {
        "name": test_case["name"],
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_commodity_dictionary_validation() -> dict:
    validation_result = validate_commodity_dictionary_file()
    failures = []

    for error in validation_result.get("errors", []):
        failures.append(error)

    return {
        "name": "Commodity dictionary validation",
        "passed": validation_result.get("valid") is True,
        "failures": failures,
    }


def evaluate_supplier_capability_validation() -> dict:
    validation_result = validate_supplier_capabilities_file()
    failures = []

    for error in validation_result.get("errors", []):
        failures.append(error)

    return {
        "name": "Supplier capability validation",
        "passed": validation_result.get("valid") is True,
        "failures": failures,
    }


def evaluate_customer_memory_validation() -> dict:
    validation_result = validate_customer_memory_file()
    failures = []

    for error in validation_result.get("errors", []):
        failures.append(error)

    return {
        "name": "Customer memory validation",
        "passed": validation_result.get("valid") is True,
        "failures": failures,
    }


def evaluate_hs_commodity_map_validation() -> dict:
    validation_result = validate_hs_commodity_map_file()
    failures = []

    for error in validation_result.get("errors", []):
        failures.append(error)

    return {
        "name": "HS / GTIP commodity map validation",
        "passed": validation_result.get("valid") is True,
        "failures": failures,
    }



def evaluate_data_health_summary() -> dict:
    summary = build_data_health_summary()
    failures = []

    required_top_level_keys = [
        "overall_valid",
        "total_checks",
        "valid_checks",
        "invalid_checks",
        "total_errors",
        "total_warnings",
        "checks",
    ]

    for key in required_top_level_keys:
        if key not in summary:
            failures.append(f"missing data health summary key: {key}")

    checks = summary.get("checks")

    if not isinstance(checks, dict):
        failures.append("checks must be a dictionary")
        checks = {}

    expected_checks = set(get_data_health_check_keys())

    missing_checks = expected_checks - set(checks.keys())

    for check_name in sorted(missing_checks):
        failures.append(f"missing data health check: {check_name}")

    if summary.get("total_checks") != len(checks):
        failures.append(
            f"total_checks expected {len(checks)}, got {summary.get('total_checks')}"
        )

    expected_valid_checks = sum(
        1
        for result in checks.values()
        if isinstance(result, dict) and result.get("valid") is True
    )
    expected_invalid_checks = len(checks) - expected_valid_checks
    expected_total_errors = sum(
        len(result.get("errors") or [])
        for result in checks.values()
        if isinstance(result, dict)
    )
    expected_total_warnings = sum(
        len(result.get("warnings") or [])
        for result in checks.values()
        if isinstance(result, dict)
    )

    if summary.get("valid_checks") != expected_valid_checks:
        failures.append(
            f"valid_checks expected {expected_valid_checks}, got {summary.get('valid_checks')}"
        )

    if summary.get("invalid_checks") != expected_invalid_checks:
        failures.append(
            f"invalid_checks expected {expected_invalid_checks}, got {summary.get('invalid_checks')}"
        )

    if summary.get("total_errors") != expected_total_errors:
        failures.append(
            f"total_errors expected {expected_total_errors}, got {summary.get('total_errors')}"
        )

    if summary.get("total_warnings") != expected_total_warnings:
        failures.append(
            f"total_warnings expected {expected_total_warnings}, got {summary.get('total_warnings')}"
        )

    expected_overall_valid = expected_invalid_checks == 0

    if summary.get("overall_valid") is not expected_overall_valid:
        failures.append(
            f"overall_valid expected {expected_overall_valid}, got {summary.get('overall_valid')}"
        )

    return {
        "name": "Data health summary regression",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_data_health_label_mapping() -> dict:
    expected_labels = get_data_health_check_labels()

    failures = []

    for check_name, expected_label in expected_labels.items():
        actual_label = get_data_health_check_label(check_name)

        if actual_label != expected_label:
            failures.append(
                f"label for {check_name} expected {expected_label}, got {actual_label}"
            )

    fallback_label = get_data_health_check_label("unknown_validator_key")

    if fallback_label != "Unknown Validator Key":
        failures.append(
            f"fallback label expected Unknown Validator Key, got {fallback_label}"
        )

    return {
        "name": "Data health label mapping",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_data_health_registry_integrity() -> dict:
    checks = get_data_health_checks()
    failures = []

    if not checks:
        failures.append("data health registry must not be empty")

    keys = []
    labels = []

    for index, check in enumerate(checks, start=1):
        if not check.key or not isinstance(check.key, str):
            failures.append(f"check #{index} has invalid key: {check.key}")

        if not check.label or not isinstance(check.label, str):
            failures.append(f"check #{index} has invalid label: {check.label}")

        if not callable(check.validator):
            failures.append(f"check #{index} validator is not callable")

        keys.append(check.key)
        labels.append(check.label)

        if callable(check.validator):
            try:
                result = check.validator()
            except Exception as error:
                failures.append(
                    f"validator for {check.key} raised {type(error).__name__}: {error}"
                )
                continue

            if not isinstance(result, dict):
                failures.append(f"validator for {check.key} must return dict")

            elif "valid" not in result:
                failures.append(f"validator for {check.key} missing valid key")

    duplicate_keys = sorted(
        key
        for key in set(keys)
        if keys.count(key) > 1
    )

    duplicate_labels = sorted(
        label
        for label in set(labels)
        if labels.count(label) > 1
    )

    for key in duplicate_keys:
        failures.append(f"duplicate data health registry key: {key}")

    for label in duplicate_labels:
        failures.append(f"duplicate data health registry label: {label}")

    return {
        "name": "Data health registry integrity",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_data_health_summary_check_metadata() -> dict:
    summary = build_data_health_summary()
    expected_labels = get_data_health_check_labels()
    failures = []

    checks = summary.get("checks")

    if not isinstance(checks, dict):
        failures.append("data health summary checks must be a dictionary")
        checks = {}

    for check_name, expected_label in expected_labels.items():
        result = checks.get(check_name)

        if not isinstance(result, dict):
            failures.append(
                f"summary result for {check_name} must be a dictionary"
            )
            continue

        if "label" not in result:
            failures.append(
                f"summary result for {check_name} missing label metadata"
            )
            continue

        actual_label = result.get("label")

        if actual_label != expected_label:
            failures.append(
                f"summary label for {check_name} "
                f"expected {expected_label}, got {actual_label}"
            )

    return {
        "name": "Data health summary check metadata",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def print_test_report(test_results: list[dict]) -> None:
    print("\n\n==============================")
    print("AUTOMATED TEST REPORT")
    print("==============================")

    passed_count = 0
    failed_count = 0

    for index, test_result in enumerate(test_results, start=1):
        status = "PASS" if test_result["passed"] else "FAIL"

        if test_result["passed"]:
            passed_count += 1
        else:
            failed_count += 1

        print(f"AI TEST {index}: {status} - {test_result['name']}")

        for failure in test_result["failures"]:
            print(f"  - {failure}")

    print("\nSUMMARY:")
    print(f"{passed_count} passed, {failed_count} failed")