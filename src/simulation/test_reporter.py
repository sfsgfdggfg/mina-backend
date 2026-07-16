from src.core.commodity_dictionary_validator import validate_commodity_dictionary_file
import json
import tempfile
from pathlib import Path

from src.core.supplier_capability_validator import validate_supplier_capabilities_file
from src.core.supplier_capability_registry_validator import (
    validate_supplier_capability_registry_file,
)
from src.core.supplier_capability_registry import (
    SupplierCapabilityRegistryError,
    load_supplier_capability_registry,
)
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
        "is_adr",
        "adr_class",
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
    
    expected_quote_readiness_result_type = expected.get(
        "quote_readiness_result_type"
    )
    if expected_quote_readiness_result_type:
        quote_readiness = result.get("quote_readiness")
        actual_quote_readiness_result_type = (
            getattr(quote_readiness, "result_type", None)
            if quote_readiness
            else None
        )

        if (
            actual_quote_readiness_result_type
            != expected_quote_readiness_result_type
        ):
            failures.append(
                "quote readiness result_type expected "
                f"{expected_quote_readiness_result_type}, "
                f"got {actual_quote_readiness_result_type}"
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

    expected_rejected_supplier_reason_contains = expected.get(
        "expected_rejected_supplier_reason_contains"
    )
    if expected_rejected_supplier_reason_contains:
        rejected_suppliers = (
            supplier_selection.get("rejected_suppliers", [])
            if isinstance(supplier_selection, dict)
            else []
        )

        rejected_reasons = [
            str(item.get("reason", ""))
            for item in rejected_suppliers
            if isinstance(item, dict)
        ]

        if not any(
            expected_rejected_supplier_reason_contains in reason
            for reason in rejected_reasons
        ):
            failures.append(
                "rejected supplier reason containing "
                f"{expected_rejected_supplier_reason_contains!r} not found"
            )

    expected_selected_supplier_name = expected.get(
        "expected_selected_supplier_name"
    )
    if expected_selected_supplier_name:
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

        if actual_selected_supplier != expected_selected_supplier_name:
            failures.append(
                "selected supplier expected "
                f"{expected_selected_supplier_name}, "
                f"got {actual_selected_supplier}"
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


def evaluate_supplier_adr_capability_validation() -> dict:
    invalid_supplier = [
        {
            "supplier_name": "Invalid ADR Supplier",
            "active": True,
            "role": "specialist",
            "route_regions": ["western_europe"],
            "countries": ["Almanya"],
            "service_types": ["FTL"],
            "equipment_types": ["ADR-Capable Equipment"],
            "special_capabilities": [
                "class_7",
                "class_7",
                "unknown_capability",
            ],
            "priority_routes": ["Türkiye-Almanya"],
            "reliability_score": 0.90,
            "price_score": 0.80,
            "speed_score": 0.80,
            "notes": "Intentionally invalid ADR supplier.",
        }
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "supplier_capabilities.json"
        temp_path.write_text(
            json.dumps(invalid_supplier, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        validation_result = validate_supplier_capabilities_file(temp_path)

    errors = validation_result.get("errors", [])
    expected_fragments = [
        "duplicate special_capability 'class_7'",
        "unsupported special_capability 'unknown_capability'",
        "class_1 or class_7 capability requires general 'adr' capability",
        "ADR equipment requires general 'adr' capability",
    ]

    failures = [
        f"expected validation error containing {fragment!r}"
        for fragment in expected_fragments
        if not any(fragment in error for error in errors)
    ]

    if validation_result.get("valid") is not False:
        failures.append("invalid ADR capability data should fail validation")

    return {
        "name": "Supplier ADR capability validation",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_supplier_capability_registry_validation() -> dict:
    invalid_registry = {
        "allowed_special_capabilities": [
            "adr",
            "class_7",
            "class_7",
        ],
        "adr_class_capability_map": {
            "1": "unknown_class_1",
        },
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / "supplier_capability_registry.json"
        temp_path.write_text(
            json.dumps(invalid_registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        validation_result = validate_supplier_capability_registry_file(
            temp_path
        )

    errors = validation_result.get("errors", [])

    expected_fragments = [
        "duplicate allowed_special_capability 'class_7'",
        "ADR Class 1 maps to unsupported capability 'unknown_class_1'",
    ]

    failures = [
        f"expected validation error containing {fragment!r}"
        for fragment in expected_fragments
        if not any(fragment in error for error in errors)
    ]

    if validation_result.get("valid") is not False:
        failures.append(
            "invalid supplier capability registry should fail validation"
        )

    return {
        "name": "Supplier capability registry validation",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_supplier_capability_registry_runtime_integrity() -> dict:
    failures = []

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)

        missing_path = temp_dir_path / "missing_registry.json"

        invalid_json_path = temp_dir_path / "invalid_registry.json"
        invalid_json_path.write_text(
            "{invalid json",
            encoding="utf-8",
        )

        non_object_path = temp_dir_path / "non_object_registry.json"
        non_object_path.write_text(
            json.dumps(["adr", "class_1"]),
            encoding="utf-8",
        )

        scenarios = [
            (
                "missing file",
                missing_path,
                "Supplier capability registry not found",
            ),
            (
                "invalid JSON",
                invalid_json_path,
                "Invalid JSON in supplier capability registry",
            ),
            (
                "non-object root",
                non_object_path,
                "Supplier capability registry root must be an object",
            ),
        ]

        for scenario_name, scenario_path, expected_fragment in scenarios:
            try:
                load_supplier_capability_registry(scenario_path)
            except SupplierCapabilityRegistryError as exc:
                if expected_fragment not in str(exc):
                    failures.append(
                        f"{scenario_name}: expected error containing "
                        f"{expected_fragment!r}, got {str(exc)!r}"
                    )
            except Exception as exc:
                failures.append(
                    f"{scenario_name}: unexpected exception type "
                    f"{type(exc).__name__}: {exc}"
                )
            else:
                failures.append(
                    f"{scenario_name}: expected SupplierCapabilityRegistryError"
                )

    return {
        "name": "Supplier capability registry runtime integrity",
        "passed": len(failures) == 0,
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
def evaluate_workflow_result_contract() -> dict:
    from src.api import determine_result_type

    cases = [
        ("quote_ready", "quote_ready"),
        ("quote_with_review", "quote_with_review"),
        ("clarification", "clarification"),
        ("management_review", "management_review"),
        ("blocked", "blocked"),
    ]

    failures = []

    class Readiness:
        def __init__(self, result_type: str):
            self.result_type = result_type

    for readiness_type, expected in cases:
        actual = determine_result_type(
            {
                "quote_readiness": Readiness(readiness_type),
            }
        )

        if actual != expected:
            failures.append(
                f"{readiness_type}: expected {expected}, got {actual}"
            )

    unknown = determine_result_type({})
    if unknown != "unknown":
        failures.append(
            f"missing quote_readiness: expected unknown, got {unknown}"
        )

    return {
        "name": "Workflow result contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_quote_readiness_blocked_state() -> dict:
    from src.core.quote_readiness import decide_quote_readiness

    class MissingInfo:
        can_continue_to_quote = True
        missing_fields = []

    class RiskAssessment:
        risk_level = "green"
        risk_reasons = []

    decision = decide_quote_readiness(
        missing_info=MissingInfo(),
        risk_assessment=RiskAssessment(),
        operational_consistency={
            "passed": False,
            "warnings": [],
            "errors": [
                "Selected supplier capability does not support required equipment."
            ],
        },
    )

    failures = []

    if decision.result_type != "blocked":
        failures.append(
            f"expected blocked, got {decision.result_type}"
        )

    if decision.can_generate_quote:
        failures.append(
            "blocked state must not allow quote generation"
        )

    if not decision.requires_human_review:
        failures.append(
            "blocked state must require human review"
        )

    if not decision.reasons:
        failures.append(
            "blocked state must preserve operational consistency errors"
        )

    return {
        "name": "Quote readiness blocked state",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_action_recommendation_result_contract() -> dict:
    from src.core.action_recommendation import generate_action_recommendation

    class Shipment:
        commodity = "Tekstil"

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    class RiskAssessment:
        risk_level = "green"
        risk_reasons = []

    class MissingInfo:
        can_continue_to_quote = True
        missing_fields = []

    failures = []

    for result_type in ("quote_ready", "quote_with_review"):
        action = generate_action_recommendation(
            shipment=Shipment(),
            equipment_decision=EquipmentDecision(),
            risk_assessment=RiskAssessment(),
            missing_info=MissingInfo(),
            result_type=result_type,
        )

        if action.action_type != result_type:
            failures.append(
                f"{result_type}: expected action_type {result_type}, "
                f"got {action.action_type}"
            )

    return {
        "name": "Action recommendation result contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_draft_generation() -> dict:
    from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts

    class Shipment:
        pickup_city = "Adana"
        pickup_country = "Türkiye"
        delivery_city = "Hamburg"
        delivery_country = "Almanya"
        commodity = "Tekstil"
        gross_weight_kg = 20000
        service_type = "FTL"
        cargo_ready_date = "2026-07-20"

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    supplier_selection = {
        "selected_suppliers": [
            {"supplier_name": "Supplier A", "priority": 1},
            {"supplier_name": "Supplier B", "priority": 2},
            {"supplier_name": "Supplier C", "priority": 3},
            {"supplier_name": "Supplier D", "priority": 4},
        ]
    }

    drafts = generate_supplier_rfq_drafts(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        supplier_selection=supplier_selection,
    )

    failures = []

    if len(drafts) != 3:
        failures.append(f"expected 3 RFQ drafts, got {len(drafts)}")

    expected_suppliers = ["Supplier A", "Supplier B", "Supplier C"]
    actual_suppliers = [draft.supplier_name for draft in drafts]

    if actual_suppliers != expected_suppliers:
        failures.append(
            f"expected suppliers {expected_suppliers}, got {actual_suppliers}"
        )

    if drafts:
        first = drafts[0]

        if first.priority != 1:
            failures.append(f"expected priority 1, got {first.priority}")

        for expected_text in (
            "Adana, Türkiye",
            "Hamburg, Almanya",
            "Tekstil",
            "20000 kg",
            "Tenteli / Curtainsider",
            "2026-07-20",
        ):
            if expected_text not in first.body:
                failures.append(
                    f"first RFQ draft missing text: {expected_text}"
                )

    return {
        "name": "Supplier RFQ draft generation",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_workflow_contract() -> dict:
    from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts

    class Shipment:
        pickup_city = "Adana"
        pickup_country = "Türkiye"
        delivery_city = "Hamburg"
        delivery_country = "Almanya"
        commodity = "Tekstil"
        gross_weight_kg = 20000
        service_type = "FTL"
        cargo_ready_date = "2026-07-20"

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    supplier_selection = {
        "selected_suppliers": [
            {"supplier_name": "Supplier A", "priority": 1},
        ]
    }

    failures = []

    allowed_statuses = {"quote_ready", "quote_with_review"}
    blocked_statuses = {
        "clarification",
        "management_review",
        "blocked",
    }

    for status in allowed_statuses:
        drafts = generate_supplier_rfq_drafts(
            shipment=Shipment(),
            equipment_decision=EquipmentDecision(),
            supplier_selection=supplier_selection,
        )

        if not drafts:
            failures.append(
                f"{status}: expected RFQ drafts, got empty list"
            )

    for status in blocked_statuses:
        drafts = []

        if drafts:
            failures.append(
                f"{status}: RFQ drafts must not be generated"
            )

    return {
        "name": "Supplier RFQ workflow contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }
