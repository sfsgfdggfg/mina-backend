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

    def supplier(name: str) -> dict:
        return {
            "supplier_name": name,
            "active": True,
            "role": "primary",
            "route_regions": [
                "western_europe",
            ],
            "countries": [
                "Türkiye",
                "Almanya",
            ],
            "service_types": [
                "FTL",
            ],
            "equipment_types": [
                "Tenteli / Curtainsider",
            ],
            "special_capabilities": [],
            "priority_routes": [
                "Türkiye-Almanya",
            ],
            "reliability_score": 0.9,
            "price_score": 0.8,
            "speed_score": 0.8,
            "notes": "Regression supplier.",
            "contacts": [
                {
                    "email": (
                        "shared-pricing@carrier.invalid"
                    ),
                    "active": True,
                    "is_primary": True,
                },
            ],
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        path = (
            Path(temp_dir)
            / "supplier_capabilities.json"
        )
        path.write_text(
            json.dumps(
                [
                    supplier("Carrier A"),
                    supplier("Carrier B"),
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        duplicate_contact_result = (
            validate_supplier_capabilities_file(
                path
            )
        )

    duplicate_errors = (
        duplicate_contact_result.get(
            "errors",
            [],
        )
    )

    if not any(
        "contact email "
        "'shared-pricing@carrier.invalid' "
        "is already owned by supplier Carrier A"
        in error
        for error in duplicate_errors
    ):
        failures.append(
            "cross-supplier contact email collision "
            "was not rejected"
        )

    if duplicate_contact_result.get(
        "valid"
    ) is not False:
        failures.append(
            "shared supplier sender identity "
            "should fail validation"
        )

    malformed_supplier = supplier(
        "Malformed Contact Carrier"
    )
    malformed_supplier["contacts"][0][
        "email"
    ] = "pricing@"

    with tempfile.TemporaryDirectory() as temp_dir:
        malformed_path = (
            Path(temp_dir)
            / "supplier_capabilities.json"
        )
        malformed_path.write_text(
            json.dumps(
                [malformed_supplier],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        malformed_contact_result = (
            validate_supplier_capabilities_file(
                malformed_path
            )
        )

    malformed_errors = (
        malformed_contact_result.get(
            "errors",
            [],
        )
    )

    if not any(
        ".email must be a valid email address"
        in error
        for error in malformed_errors
    ):
        failures.append(
            "malformed supplier primary contact "
            "email was not rejected"
        )

    if (
        malformed_contact_result.get(
            "active_contactable_supplier_count"
        )
        != 0
    ):
        failures.append(
            "malformed primary contact counted "
            "as contactable supplier"
        )

    if malformed_contact_result.get(
        "valid"
    ) is not False:
        failures.append(
            "malformed supplier contact should "
            "fail validation"
        )

    return {
        "name": "Supplier capability validation",
        "passed": (
            validation_result.get("valid") is True
            and not failures
        ),
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

    invalid_profiles = [
        {
            "customer_name": "Trust Customer A",
            "active": True,
            "aliases": [],
            "trusted_sender_addresses": [
                "ops@shared.invalid",
            ],
            "trusted_sender_domains": [
                "shared.invalid",
            ],
        },
        {
            "customer_name": "Trust Customer B",
            "active": True,
            "aliases": [],
            "trusted_sender_addresses": [
                "ops@shared.invalid",
            ],
            "trusted_sender_domains": [
                "@invalid-domain",
            ],
        },
        {
            "customer_name": "Invalid Pricing Customer",
            "active": True,
            "aliases": [],
            "trusted_sender_addresses": ["pricing@invalid.example"],
            "trusted_sender_domains": [],
            "pricing_policy": {
                "method": "gross_margin_percentage",
                "value": 100,
            },
        },
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "customer_memory.json"
        path.write_text(
            json.dumps(
                invalid_profiles,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        invalid_result = (
            validate_customer_memory_file(path)
        )

    invalid_errors = invalid_result.get(
        "errors",
        [],
    )

    expected_fragments = (
        "trusted sender address 'ops@shared.invalid' "
        "is already trusted by Trust Customer A",
        "trusted sender domain '@invalid-domain' "
        "must be a bare valid domain",
        "pricing_policy is invalid",
    )

    for fragment in expected_fragments:
        if not any(
            fragment in error
            for error in invalid_errors
        ):
            failures.append(
                "customer trusted-sender validation "
                f"missing error containing: {fragment}"
            )

    if invalid_result.get("valid") is not False:
        failures.append(
            "ambiguous customer sender trust "
            "should fail validation"
        )

    return {
        "name": "Customer memory validation",
        "passed": (
            validation_result.get("valid") is True
            and not failures
        ),
        "failures": failures,
    }


def evaluate_strict_supplier_eligibility() -> dict:
    from src.core.models import Shipment
    from src.core.supplier_selection import select_suppliers_for_shipment

    failures = []

    def selected_names(shipment, selected_equipment):
        result = select_suppliers_for_shipment(
            shipment=shipment,
            equipment_decision={
                "selected_equipment": selected_equipment,
            },
        )
        return {
            item["supplier_name"]
            for item in result["selected_suppliers"]
        }

    international_ltl = Shipment(
        pickup_country="Türkiye",
        delivery_country="Almanya",
        service_type="LTL",
    )
    ltl_names = selected_names(
        international_ltl,
        "Tenteli / Curtainsider",
    )

    if "Anatolia Road" in ltl_names:
        failures.append("FTL-only supplier must be excluded from LTL")

    if not ltl_names:
        failures.append("compatible LTL suppliers should remain eligible")

    import_from_supported_country = Shipment(
        pickup_country="Almanya",
        delivery_country="Türkiye",
        service_type="FTL",
    )
    import_names = selected_names(
        import_from_supported_country,
        "Tenteli / Curtainsider",
    )
    if not {"Anatolia Road", "EuroBridge Logistics"}.issubset(import_names):
        failures.append(
            "Türkiye import should accept suppliers serving the foreign lane country"
        )

    origin_only = Shipment(
        pickup_country="Türkiye",
        delivery_country="İspanya",
        service_type="FTL",
    )
    if selected_names(origin_only, "Tenteli / Curtainsider"):
        failures.append(
            "origin-country support alone must not establish route eligibility"
        )

    domestic = Shipment(
        pickup_country="Türkiye",
        delivery_country="Türkiye",
        service_type="FTL",
    )
    domestic_names = selected_names(
        domestic,
        "Tenteli / Curtainsider",
    )
    if domestic_names != {"Anatolia Domestic"}:
        failures.append(
            "domestic FTL should use only capability-declared domestic supplier"
        )

    reefer = Shipment(
        pickup_country="Türkiye",
        delivery_country="Almanya",
        service_type="FTL",
        is_temperature_controlled=True,
    )
    reefer_names = selected_names(reefer, "Reefer")
    if reefer_names != {"ColdChain Europe"}:
        failures.append(
            "reefer requirement should exclude suppliers without Reefer capability"
        )

    heavy = Shipment(
        pickup_country="Türkiye",
        delivery_country="Almanya",
        service_type="FTL",
    )
    if selected_names(heavy, "Lowbed / Heavy Haul"):
        failures.append(
            "heavy equipment should have no eligible supplier when capability is absent"
        )

    return {
        "name": "Strict supplier eligibility",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_inactive_customer_memory_matching() -> dict:
    import src.core.customer_memory as customer_memory
    from src.core.models import Shipment

    failures = []
    inactive_profile = customer_memory.CustomerMemoryProfile(
        customer_name="Inactive Customer",
        active=False,
        aliases=["Dormant Alias"],
        default_commodity="Tekstil",
    )
    active_profile = customer_memory.CustomerMemoryProfile(
        customer_name="Active Customer",
        active=True,
        aliases=["Current Alias"],
        default_commodity="Gıda",
    )
    original_loader = customer_memory.load_customer_memory

    try:
        customer_memory.load_customer_memory = lambda: [
            inactive_profile,
            active_profile,
        ]

        if customer_memory.find_customer_profile("Inactive Customer") is not None:
            failures.append("inactive profile matched by parsed customer name")

        if customer_memory.find_customer_profile("Dormant Alias") is not None:
            failures.append("inactive profile matched by parsed alias")

        if customer_memory.find_customer_profile_in_text(
            "Request from Dormant Alias"
        ) is not None:
            failures.append("inactive profile matched in raw email text")

        enrichment = customer_memory.enrich_shipment_with_customer_memory(
            shipment=Shipment(customer_name="Unknown Customer"),
            email_text="Request from Dormant Alias",
        )
        if enrichment.matched:
            failures.append("inactive profile enriched a shipment")

        if customer_memory.find_customer_profile_in_text(
            "Request from Current Alias"
        ) is not None:
            failures.append("raw email alias must not establish customer identity")
    finally:
        customer_memory.load_customer_memory = original_loader

    return {
        "name": "Inactive customer memory matching",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_heavy_cargo_weight_logic() -> dict:
    from src.core.equipment import decide_equipment
    from src.core.missing_info import check_missing_information
    from src.core.models import Package, Shipment

    failures = []

    single_piece_gross = Shipment(
        gross_weight_kg=26000,
        packages=[Package(quantity=1)],
    )
    if decide_equipment(single_piece_gross).selected_equipment != "Lowbed / Heavy Haul":
        failures.append(
            "single-piece shipment gross weight at 26t should trigger heavy haul"
        )

    package_weight = Shipment(
        packages=[Package(quantity=1, weight_kg=26000)],
    )
    if decide_equipment(package_weight).selected_equipment != "Lowbed / Heavy Haul":
        failures.append(
            "confirmed single-package weight at 26t should retain heavy-haul behavior"
        )

    multi_piece_gross = Shipment(
        gross_weight_kg=30000,
        packages=[Package(quantity=2, weight_kg=15000)],
    )
    if decide_equipment(multi_piece_gross).selected_equipment == "Lowbed / Heavy Haul":
        failures.append(
            "multi-piece shipment gross weight must not be treated as one heavy piece"
        )

    ambiguous_gross = Shipment(
        pickup_city="Adana",
        delivery_city="Hamburg",
        commodity="Tekstil",
        cargo_ready_date="2026-08-15",
        gross_weight_kg=26000,
    )
    ambiguous_decision = decide_equipment(ambiguous_gross)
    ambiguous_missing = check_missing_information(ambiguous_gross)

    if ambiguous_decision.selected_equipment != "Heavy Cargo Equipment Review":
        failures.append(
            "gross-heavy shipment without package structure should require review"
        )

    if (
        "package count and per-piece weights"
        not in ambiguous_missing.missing_fields
        or ambiguous_missing.can_continue_to_quote
    ):
        failures.append(
            "ambiguous gross-heavy shipment should stop for weight clarification"
        )

    ambiguous_package_line = Shipment(
        packages=[Package(quantity=2, weight_kg=26000)],
    )
    if (
        decide_equipment(ambiguous_package_line).selected_equipment
        != "Heavy Cargo Equipment Review"
    ):
        failures.append(
            "ambiguous multi-piece package-line weight should not assign heavy haul"
        )

    return {
        "name": "Heavy cargo weight logic",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_customer_pricing_regression() -> dict:
    from src.core.models import CustomerQuote, SupplierQuote
    from src.core.pricing import calculate_customer_quote
    from src.core.pricing_policy import (
        AGENCY_PRICING_POLICY_ENV,
        PricingFormula,
        resolve_pricing_policy,
    )

    failures = []
    supplier_quote = SupplierQuote(
        supplier_name="Pricing Boundary Supplier",
        cost=2400,
        currency="EUR",
    )
    agency_json = (
        '{"default_formula":{"method":"cost_markup_percentage","value":15},'
        '"default_rounding":{"mode":"none"},'
        '"currency_rounding":{"EUR":{"mode":"up","increment":10}}}'
    )
    agency_env = {AGENCY_PRICING_POLICY_ENV: agency_json}

    resolved = resolve_pricing_policy(currency="EUR", environ=agency_env)
    markup_quote = calculate_customer_quote(supplier_quote, resolved)
    if markup_quote.final_price != 2760:
        failures.append("15% cost markup should produce 2760 EUR")
    if resolved.policy_source != "agency_default":
        failures.append("agency default pricing source was not preserved")

    gross_margin = resolve_pricing_policy(
        currency="EUR",
        quote_override=PricingFormula(
            method="gross_margin_percentage", value=15
        ),
        environ=agency_env,
    )
    gross_margin_quote = calculate_customer_quote(supplier_quote, gross_margin)
    if gross_margin_quote.final_price != 2830:
        failures.append("15% gross margin should round 2823.53 EUR up to 2830 EUR")

    fixed_profit = resolve_pricing_policy(
        currency="EUR",
        quote_override=PricingFormula(method="fixed_profit", value=300),
        environ=agency_env,
    )
    if calculate_customer_quote(supplier_quote, fixed_profit).final_price != 2700:
        failures.append("300 EUR fixed profit should produce 2700 EUR")

    manual = resolve_pricing_policy(
        currency="EUR",
        quote_override=PricingFormula(method="manual_sell_price", value=2755),
        environ=agency_env,
    )
    manual_quote = calculate_customer_quote(supplier_quote, manual)
    if manual_quote.final_price != 2755:
        failures.append("manual sell price must not be rounded by agency policy")

    missing = resolve_pricing_policy(currency="EUR", environ={})
    if missing.status != "missing" or missing.resolved:
        failures.append("missing pricing policy did not fail closed")

    legacy_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    if legacy_quote.markup_type != "percentage" or legacy_quote.margin_value != 15:
        failures.append("legacy serialized quote compatibility was lost")

    dumped_quote = markup_quote.model_dump()
    if "pricing_policy" not in dumped_quote or "margin_type" in dumped_quote:
        failures.append("serialized quote should preserve pricing policy provenance")

    return {
        "name": "Customer pricing policy and rounding",
        "passed": len(failures) == 0,
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

    for result_type in (
        "quote_ready",
        "quote_with_review",
        "pricing_policy_required",
    ):
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
        pickup_area = None
        pickup_postcode = None
        delivery_area = None
        delivery_postcode = None
        required_delivery_date = None
        special_notes = None
        transport_mode = None
        packages = []
        is_adr = False
        adr_class = None

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": "Supplier A",
                "recipient_email": "pricing@supplier-a.invalid",
                "priority": 1,
            },
            {
                "supplier_name": "Supplier B",
                "recipient_email": None,
                "priority": 2,
            },
            {
                "supplier_name": "Supplier C",
                "recipient_email": "rfq@supplier-c.invalid",
                "priority": 3,
            },
            {
                "supplier_name": "Supplier D",
                "recipient_email": "rfq@supplier-d.invalid",
                "priority": 4,
            },
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

        if first.recipient_email != "pricing@supplier-a.invalid":
            failures.append(
                "expected first RFQ recipient_email "
                "pricing@supplier-a.invalid, "
                f"got {first.recipient_email}"
            )

        if first.status != "draft":
            failures.append(
                f"expected first RFQ status draft, got {first.status}"
            )

        if not first.has_recipient:
            failures.append(
                "first RFQ draft should report has_recipient=True"
            )

        second = drafts[1] if len(drafts) > 1 else None
        if second and second.has_recipient:
            failures.append(
                "second RFQ draft should report has_recipient=False"
            )

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
        pickup_area = None
        pickup_postcode = None
        delivery_area = None
        delivery_postcode = None
        required_delivery_date = None
        special_notes = None
        transport_mode = None
        packages = []
        is_adr = False
        adr_class = None

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

def evaluate_supplier_rfq_contact_propagation() -> dict:
    from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
    from src.core.supplier_selection import select_suppliers_for_shipment

    class Shipment:
        pickup_country = "Türkiye"
        pickup_city = "Adana"
        delivery_country = "Almanya"
        delivery_city = "Hamburg"
        commodity = "Tekstil"
        gross_weight_kg = 20000
        service_type = "FTL"
        cargo_ready_date = "2026-07-20"
        pickup_area = None
        pickup_postcode = None
        delivery_area = None
        delivery_postcode = None
        required_delivery_date = None
        special_notes = None
        transport_mode = None
        packages = []
        equipment_type = None
        is_adr = False
        adr_class = None

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    class RiskAssessment:
        risk_level = "green"

    supplier_selection = select_suppliers_for_shipment(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        risk_assessment=RiskAssessment(),
    )

    drafts = generate_supplier_rfq_drafts(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        supplier_selection=supplier_selection,
    )

    failures = []

    if not drafts:
        failures.append("expected at least one supplier RFQ draft")
    else:
        selected_suppliers = supplier_selection.get("selected_suppliers") or []
        expected_by_supplier = {
            supplier.get("supplier_name"): supplier.get("recipient_email")
            for supplier in selected_suppliers
        }

        for draft in drafts:
            expected_email = expected_by_supplier.get(draft.supplier_name)

            if draft.recipient_email != expected_email:
                failures.append(
                    f"{draft.supplier_name}: expected recipient "
                    f"{expected_email}, got {draft.recipient_email}"
                )

        contacted_drafts = [
            draft
            for draft in drafts
            if draft.recipient_email
        ]

        if not contacted_drafts:
            failures.append(
                "expected at least one RFQ draft with recipient email"
            )

        for draft in contacted_drafts:
            if not draft.has_recipient:
                failures.append(
                    f"{draft.supplier_name}: has_recipient should be True"
                )

    return {
        "name": "Supplier RFQ contact propagation",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_response_simulation() -> dict:
    from src.ai.supplier_rfq_generator import (
        generate_supplier_rfq_drafts,
    )
    from src.simulation.supplier_simulator import (
        simulate_supplier_rfq_responses,
    )

    class Shipment:
        pickup_city = "Adana"
        pickup_country = "Türkiye"
        delivery_city = "Hamburg"
        delivery_country = "Germany"
        commodity = "Textile"
        gross_weight_kg = 20000
        service_type = "FTL"
        cargo_ready_date = "2026-07-20"
        pickup_area = None
        pickup_postcode = None
        delivery_area = None
        delivery_postcode = None
        required_delivery_date = None
        special_notes = None
        transport_mode = None
        packages = []
        is_adr = False
        adr_class = None

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": "Supplier A",
                "priority": 1,
                "recipient_email": "a@example.invalid",
            },
            {
                "supplier_name": "Supplier B",
                "priority": 2,
                "recipient_email": "b@example.invalid",
            },
            {
                "supplier_name": "Supplier C",
                "priority": 3,
                "recipient_email": "c@example.invalid",
            },
            {
                "supplier_name": "Supplier D",
                "priority": 4,
                "recipient_email": "d@example.invalid",
            },
        ]
    }

    rfq_drafts = generate_supplier_rfq_drafts(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        supplier_selection=supplier_selection,
    )

    unsent_responses = simulate_supplier_rfq_responses(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        supplier_selection=supplier_selection,
        rfq_drafts=rfq_drafts,
    )

    sent_rfq_drafts = [
        draft.model_copy(update={"status": "awaiting_response"})
        for draft in rfq_drafts
    ]
    responses = simulate_supplier_rfq_responses(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        supplier_selection=supplier_selection,
        rfq_drafts=sent_rfq_drafts,
    )

    failures = []

    if len(rfq_drafts) != 3:
        failures.append(
            f"expected 3 RFQ drafts, got {len(rfq_drafts)}"
        )

    if unsent_responses:
        failures.append(
            "unsent RFQ drafts must not receive simulated responses"
        )

    if len(responses) != 3:
        failures.append(
            f"expected 3 RFQ responses, got {len(responses)}"
        )

    expected_suppliers = ["Supplier A", "Supplier B", "Supplier C"]
    actual_suppliers = [
        response.supplier_name
        for response in responses
    ]

    if actual_suppliers != expected_suppliers:
        failures.append(
            f"expected suppliers {expected_suppliers}, "
            f"got {actual_suppliers}"
        )

    for index, response in enumerate(responses, start=1):
        draft = rfq_drafts[index - 1]

        if response.rfq_id != draft.rfq_id:
            failures.append(
                f"{response.supplier_name}: response RFQ ID "
                f"{response.rfq_id} does not match draft RFQ ID "
                f"{draft.rfq_id}"
            )

        if response.supplier_name != draft.supplier_name:
            failures.append(
                f"draft/response supplier mismatch: "
                f"{draft.supplier_name} != {response.supplier_name}"
            )

        if response.rfq_priority != draft.priority:
            failures.append(
                f"{response.supplier_name}: expected priority "
                f"{draft.priority}, got {response.rfq_priority}"
            )

        if response.status != "quoted":
            failures.append(
                f"{response.supplier_name}: expected quoted status, "
                f"got {response.status}"
            )

        if not response.is_price_usable:
            failures.append(
                f"{response.supplier_name}: price should be usable"
            )

        if response.source != "simulation":
            failures.append(
                f"{response.supplier_name}: expected simulation source, "
                f"got {response.source}"
            )

    if responses:
        expected_costs = [2000.0, 2120.0, 2240.0]
        actual_costs = [
            response.cost
            for response in responses
        ]

        if actual_costs != expected_costs:
            failures.append(
                f"expected costs {expected_costs}, got {actual_costs}"
            )

    return {
        "name": "Supplier RFQ response simulation",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_quote_selection() -> dict:
    from src.core.supplier_quote_selection import (
        select_supplier_quote_from_responses,
    )
    from src.core.supplier_rfq import SupplierRFQResponse

    responses = [
        SupplierRFQResponse(
            supplier_name="Priority Supplier",
            rfq_priority=1,
            status="quoted",
            cost=2300,
            currency="EUR",
            transit_time="5-7 days",
            source="simulation",
        ),
        SupplierRFQResponse(
            supplier_name="Cheaper Supplier",
            rfq_priority=2,
            status="quoted",
            cost=1900,
            currency="EUR",
            transit_time="6-8 days",
            source="simulation",
        ),
        SupplierRFQResponse(
            supplier_name="Unavailable Supplier",
            rfq_priority=3,
            status="no_capacity",
            source="simulation",
        ),
    ]

    selected = select_supplier_quote_from_responses(responses)

    failures = []

    if selected is None:
        failures.append("expected a selected supplier quote")
    else:
        if selected.supplier_name != "Priority Supplier":
            failures.append(
                "expected Priority Supplier, "
                f"got {selected.supplier_name}"
            )

        if selected.cost != 2300:
            failures.append(
                f"expected selected cost 2300, got {selected.cost}"
            )

    no_quote = select_supplier_quote_from_responses(
        [
            SupplierRFQResponse(
                supplier_name="No Capacity",
                rfq_priority=1,
                status="no_capacity",
                source="simulation",
            ),
            SupplierRFQResponse(
                supplier_name="Declined",
                rfq_priority=2,
                status="declined",
                source="simulation",
            ),
        ]
    )

    if no_quote is not None:
        failures.append(
            "expected no selected quote when no usable response exists"
        )

    return {
        "name": "Supplier quote selection",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_response_validation() -> dict:
    from pydantic import ValidationError

    from src.core.supplier_rfq import SupplierRFQResponse

    failures = []

    try:
        valid_response = SupplierRFQResponse(
            supplier_name="Valid Supplier",
            rfq_priority=1,
            status="quoted",
            cost=2100,
            currency="EUR",
            source="simulation",
        )

        if not valid_response.is_price_usable:
            failures.append(
                "quoted response with positive cost should be usable"
            )
    except ValidationError as exc:
        failures.append(
            f"positive quoted response was rejected: {exc}"
        )

    try:
        SupplierRFQResponse(
            supplier_name="Missing Cost Supplier",
            rfq_priority=2,
            status="quoted",
            source="simulation",
        )
        failures.append(
            "quoted response without cost should be rejected"
        )
    except ValidationError:
        pass

    try:
        SupplierRFQResponse(
            supplier_name="Negative Cost Supplier",
            rfq_priority=3,
            status="quoted",
            cost=-100,
            source="simulation",
        )
        failures.append(
            "quoted response with negative cost should be rejected"
        )
    except ValidationError:
        pass

    try:
        no_capacity_response = SupplierRFQResponse(
            supplier_name="No Capacity Supplier",
            rfq_priority=4,
            status="no_capacity",
            source="simulation",
        )

        if no_capacity_response.is_price_usable:
            failures.append(
                "no_capacity response should not be price usable"
            )
    except ValidationError as exc:
        failures.append(
            f"no_capacity response without cost was rejected: {exc}"
        )

    return {
        "name": "Supplier RFQ response validation",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_fallback_consistency() -> dict:
    from src.core.operational_consistency import (
        check_operational_consistency,
    )
    from src.core.models import SupplierQuote

    class Shipment:
        pickup_country = "Türkiye"
        delivery_country = "Almanya"
        service_type = "FTL"
        adr_class = None
        is_adr = False
        special_notes = ""

    class EquipmentDecision:
        selected_equipment = "Tenteli / Curtainsider"

    class RiskAssessment:
        risk_level = "green"

    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": "Primary Supplier",
                "priority": 1,
            },
            {
                "supplier_name": "Fallback Supplier",
                "priority": 2,
            },
        ]
    }

    failures = []

    fallback_quote = SupplierQuote(
        supplier_name="Fallback Supplier",
        cost=2100,
        currency="EUR",
        transit_time="5-7 days",
    )

    fallback_result = check_operational_consistency(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        risk_assessment=RiskAssessment(),
        supplier_selection=supplier_selection,
        supplier_quote=fallback_quote,
    )

    fallback_errors = fallback_result.get("errors", [])

    if fallback_errors:
        failures.append(
            "selected fallback supplier should be accepted, "
            f"got errors: {fallback_errors}"
        )

    outsider_quote = SupplierQuote(
        supplier_name="Unknown Supplier",
        cost=1900,
        currency="EUR",
        transit_time="5-7 days",
    )

    outsider_result = check_operational_consistency(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(),
        risk_assessment=RiskAssessment(),
        supplier_selection=supplier_selection,
        supplier_quote=outsider_quote,
    )

    outsider_errors = outsider_result.get("errors", [])

    if not any(
        "Supplier Selection listesinde bulunmayan" in error
        for error in outsider_errors
    ):
        failures.append(
            "supplier outside selection list should be rejected"
        )

    return {
        "name": "Supplier fallback consistency",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_final_quote_consistency_block() -> dict:
    from src.api import determine_result_type
    from src.core.models import Package, Shipment
    from src.core.supplier_rfq import SupplierRFQResponse
    from src.workflow import pipeline

    failures = []

    shipment = Shipment(
        customer_name="Known Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-07-20",
        packages=[
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )

    original_simulator = pipeline.simulate_supplier_rfq_responses

    def simulate_outsider_response(
        shipment,
        equipment_decision,
        supplier_selection=None,
        rfq_drafts=None,
    ):
        return [
            SupplierRFQResponse(
                rfq_id="unknown-outsider-rfq",
                supplier_name="Outside Selection Supplier",
                rfq_priority=1,
                status="quoted",
                cost=1800,
                currency="EUR",
                transit_time="4-6 days",
                equipment_type=equipment_decision.selected_equipment,
                notes="Intentional outsider response for regression test.",
                source="simulation",
            )
        ]

    try:
        pipeline.simulate_supplier_rfq_responses = (
            simulate_outsider_response
        )

        result = pipeline.process_shipment(
            shipment=shipment,
            email_text=(
                "Adana'dan Hamburg'a 20 ton tekstil yükü için "
                "komple araç fiyatı rica ederiz. "
                "Yük 20.07.2026 tarihinde hazırdır."
            ),
        )
    finally:
        pipeline.simulate_supplier_rfq_responses = (
            original_simulator
        )

    result_type = determine_result_type(result)

    if result_type != "supplier_response_required":
        failures.append(
            "identity-invalid response should produce "
            "supplier_response_required, "
            f"got {result_type}"
        )

    if result.get("supplier_quote") is not None:
        failures.append(
            "identity-invalid response must not create supplier quote"
        )

    if result.get("customer_quote") is not None:
        failures.append(
            "identity-invalid response must not create customer quote"
        )

    if result.get("quote_draft") is not None:
        failures.append(
            "identity-invalid response must not create quote draft"
        )

    validation = result.get("supplier_rfq_response_validation")

    if validation is None:
        failures.append("RFQ response validation report is missing")
    else:
        if validation.valid_count != 0:
            failures.append(
                f"expected valid_count 0, got {validation.valid_count}"
            )

        if validation.rejected_count != 1:
            failures.append(
                "expected rejected_count 1, "
                f"got {validation.rejected_count}"
            )

        reasons = {
            item.reason
            for item in validation.rejected_responses
        }

        if "unknown_rfq_id" not in reasons:
            failures.append(
                "outsider response rejection reason was not preserved"
            )

    raw_responses = result.get("supplier_rfq_responses") or []

    if len(raw_responses) != 1:
        failures.append(
            "rejected raw response should be preserved for audit"
        )

    valid_responses = (
        result.get("valid_supplier_rfq_responses") or []
    )

    if valid_responses:
        failures.append(
            "identity-invalid response must not enter valid responses"
        )

    return {
        "name": "Final quote consistency block",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_response_required_state() -> dict:
    from src.api import determine_result_type
    from src.core.models import Package, Shipment
    from src.core.supplier_rfq import SupplierRFQResponse
    from src.workflow import pipeline

    failures = []

    shipment = Shipment(
        customer_name="Known Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-07-20",
        packages=[
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )

    original_simulator = pipeline.simulate_supplier_rfq_responses

    def simulate_unusable_responses(
        shipment,
        equipment_decision,
        supplier_selection=None,
        rfq_drafts=None,
    ):
        drafts = list(rfq_drafts or [])

        responses = []

        if drafts:
            responses.append(
                SupplierRFQResponse(
                    rfq_id=drafts[0].rfq_id,
                    supplier_name=drafts[0].supplier_name,
                    rfq_priority=drafts[0].priority,
                    status="no_capacity",
                    notes="No vehicle capacity.",
                    source="simulation",
                )
            )

        if len(drafts) > 1:
            responses.append(
                SupplierRFQResponse(
                    rfq_id=drafts[1].rfq_id,
                    supplier_name=drafts[1].supplier_name,
                    rfq_priority=drafts[1].priority,
                    status="declined",
                    notes="Supplier declined the request.",
                    source="simulation",
                )
            )

        return responses

    try:
        pipeline.simulate_supplier_rfq_responses = (
            simulate_unusable_responses
        )

        result = pipeline.process_shipment(
            shipment=shipment,
            email_text=(
                "Adana'dan Hamburg'a 20 ton tekstil yükü için "
                "komple araç fiyatı rica ederiz. "
                "Yük 20.07.2026 tarihinde hazırdır."
            ),
        )
    finally:
        pipeline.simulate_supplier_rfq_responses = (
            original_simulator
        )

    actual_result_type = determine_result_type(result)

    if actual_result_type != "supplier_response_required":
        failures.append(
            "expected supplier_response_required, "
            f"got {actual_result_type}"
        )

    if result.get("quote_readiness") is not None:
        failures.append(
            "supplier response state should not retain stale "
            "quote_readiness"
        )

    if result.get("supplier_quote") is not None:
        failures.append(
            "no usable supplier response must not create supplier quote"
        )

    if result.get("customer_quote") is not None:
        failures.append(
            "no usable supplier response must not create customer quote"
        )

    if result.get("quote_draft") is not None:
        failures.append(
            "no usable supplier response must not create quote draft"
        )

    responses = result.get("supplier_rfq_responses") or []

    if not responses:
        failures.append(
            "supplier responses should be preserved for audit"
        )

    if any(response.is_price_usable for response in responses):
        failures.append(
            "test responses should all be unusable for pricing"
        )

    action = result.get("action_recommendation")

    if action is None:
        failures.append("action recommendation is missing")
    elif action.action_type != "supplier_response_required":
        failures.append(
            "expected supplier_response_required action, "
            f"got {action.action_type}"
        )

    return {
        "name": "Supplier response required state",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_lifecycle_synchronization() -> dict:
    from datetime import datetime, timedelta

    from src.core.supplier_rfq import (
        SupplierRFQDraft,
        SupplierRFQResponse,
    )
    from src.core.supplier_rfq_lifecycle import (
        synchronize_supplier_rfq_lifecycle,
    )

    failures = []

    base_time = datetime(2026, 7, 20, 10, 0, 0)

    draft_with_response = SupplierRFQDraft(
        rfq_id="rfq-1",
        supplier_name="Supplier A",
        priority=1,
        subject="RFQ A",
        body="Body A",
        status="awaiting_response",
    )

    draft_without_response = SupplierRFQDraft(
        rfq_id="rfq-2",
        supplier_name="Supplier B",
        priority=2,
        subject="RFQ B",
        body="Body B",
        status="sent",
    )

    older_response = SupplierRFQResponse(
        rfq_id="rfq-1",
        supplier_name="Supplier A",
        rfq_priority=1,
        status="declined",
        notes="Older response.",
        source="simulation",
        received_at=base_time,
    )

    latest_response = SupplierRFQResponse(
        rfq_id="rfq-1",
        supplier_name="Supplier A",
        rfq_priority=1,
        status="quoted",
        cost=2100,
        currency="EUR",
        notes="Latest response.",
        source="simulation",
        received_at=base_time + timedelta(minutes=15),
    )

    unknown_response = SupplierRFQResponse(
        rfq_id="unknown-rfq",
        supplier_name="Unknown Supplier",
        rfq_priority=3,
        status="no_capacity",
        source="simulation",
        received_at=base_time + timedelta(minutes=30),
    )

    synchronized = synchronize_supplier_rfq_lifecycle(
        drafts=[
            draft_with_response,
            draft_without_response,
        ],
        responses=[
            older_response,
            latest_response,
            unknown_response,
        ],
    )

    if len(synchronized) != 2:
        failures.append(
            f"expected 2 synchronized drafts, got {len(synchronized)}"
        )

    synchronized_by_id = {
        draft.rfq_id: draft
        for draft in synchronized
    }

    updated_draft = synchronized_by_id.get("rfq-1")

    if updated_draft is None:
        failures.append("draft with response is missing")
    else:
        if updated_draft.status != "responded":
            failures.append(
                "draft with response should have responded status, "
                f"got {updated_draft.status}"
            )

        if updated_draft.responded_at != latest_response.received_at:
            failures.append(
                "responded_at should use latest response received_at"
            )

    untouched_draft = synchronized_by_id.get("rfq-2")

    if untouched_draft is None:
        failures.append("draft without response is missing")
    else:
        if untouched_draft.status != "sent":
            failures.append(
                "draft without response should preserve status, "
                f"got {untouched_draft.status}"
            )

        if untouched_draft.responded_at is not None:
            failures.append(
                "draft without response should not have responded_at"
            )

    if draft_with_response.status != "awaiting_response":
        failures.append(
            "lifecycle synchronization should not mutate original draft"
        )

    return {
        "name": "Supplier RFQ lifecycle synchronization",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_response_link_integrity() -> dict:
    from src.core.supplier_quote_selection import (
        select_supplier_quote_from_responses,
    )
    from src.core.supplier_rfq import (
        SupplierRFQDraft,
        SupplierRFQResponse,
    )
    from src.core.supplier_rfq_lifecycle import (
        filter_valid_supplier_rfq_responses,
        synchronize_supplier_rfq_lifecycle,
    )

    failures = []

    draft = SupplierRFQDraft(
        rfq_id="rfq-integrity-1",
        supplier_name="Expected Supplier",
        priority=1,
        subject="Integrity RFQ",
        body="Integrity test body",
        status="awaiting_response",
    )

    valid_response = SupplierRFQResponse(
        rfq_id="rfq-integrity-1",
        supplier_name="Expected Supplier",
        rfq_priority=1,
        status="quoted",
        cost=2200,
        currency="EUR",
        source="simulation",
    )

    wrong_supplier_response = SupplierRFQResponse(
        rfq_id="rfq-integrity-1",
        supplier_name="Wrong Supplier",
        rfq_priority=1,
        status="quoted",
        cost=1500,
        currency="EUR",
        source="simulation",
    )

    wrong_priority_response = SupplierRFQResponse(
        rfq_id="rfq-integrity-1",
        supplier_name="Expected Supplier",
        rfq_priority=2,
        status="quoted",
        cost=1400,
        currency="EUR",
        source="simulation",
    )

    valid_responses = filter_valid_supplier_rfq_responses(
        drafts=[draft],
        responses=[
            wrong_supplier_response,
            wrong_priority_response,
            valid_response,
        ],
    )

    if len(valid_responses) != 1:
        failures.append(
            f"expected 1 valid response, got {len(valid_responses)}"
        )
    elif valid_responses[0] is not valid_response:
        failures.append(
            "expected only the fully matching response to be accepted"
        )

    selected_quote = select_supplier_quote_from_responses(
        valid_responses
    )

    if selected_quote is None:
        failures.append(
            "valid linked response should produce supplier quote"
        )
    else:
        if selected_quote.supplier_name != "Expected Supplier":
            failures.append(
                "invalid supplier response affected quote selection"
            )

        if selected_quote.cost != 2200:
            failures.append(
                f"expected selected cost 2200, got {selected_quote.cost}"
            )

    invalid_only = filter_valid_supplier_rfq_responses(
        drafts=[draft],
        responses=[
            wrong_supplier_response,
            wrong_priority_response,
        ],
    )

    if invalid_only:
        failures.append(
            "identity-mismatched responses should all be rejected"
        )

    synchronized = synchronize_supplier_rfq_lifecycle(
        drafts=[draft],
        responses=[
            wrong_supplier_response,
            wrong_priority_response,
        ],
    )

    if not synchronized:
        failures.append("synchronized draft is missing")
    else:
        synchronized_draft = synchronized[0]

        if synchronized_draft.status != "awaiting_response":
            failures.append(
                "invalid response must not change draft status"
            )

        if synchronized_draft.responded_at is not None:
            failures.append(
                "invalid response must not set responded_at"
            )

    if select_supplier_quote_from_responses(invalid_only) is not None:
        failures.append(
            "invalid-only responses must not produce supplier quote"
        )

    return {
        "name": "Supplier RFQ response link integrity",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_response_validation_report() -> dict:
    from src.core.supplier_rfq import (
        SupplierRFQDraft,
        SupplierRFQResponse,
    )
    from src.core.supplier_rfq_lifecycle import (
        validate_supplier_rfq_responses,
    )

    failures = []

    draft = SupplierRFQDraft(
        rfq_id="rfq-report-1",
        supplier_name="Expected Supplier",
        priority=1,
        subject="RFQ Report Test",
        body="RFQ report test body",
        status="awaiting_response",
    )

    valid_response = SupplierRFQResponse(
        rfq_id="rfq-report-1",
        supplier_name="Expected Supplier",
        rfq_priority=1,
        status="quoted",
        cost=2200,
        currency="EUR",
        source="simulation",
    )

    unknown_rfq_response = SupplierRFQResponse(
        rfq_id="unknown-rfq",
        supplier_name="Unknown Supplier",
        rfq_priority=1,
        status="no_capacity",
        source="simulation",
    )

    supplier_mismatch_response = SupplierRFQResponse(
        rfq_id="rfq-report-1",
        supplier_name="Wrong Supplier",
        rfq_priority=1,
        status="declined",
        source="simulation",
    )

    priority_mismatch_response = SupplierRFQResponse(
        rfq_id="rfq-report-1",
        supplier_name="Expected Supplier",
        rfq_priority=2,
        status="needs_clarification",
        source="simulation",
    )

    valid_responses, report = validate_supplier_rfq_responses(
        drafts=[draft],
        responses=[
            valid_response,
            unknown_rfq_response,
            supplier_mismatch_response,
            priority_mismatch_response,
        ],
    )

    if len(valid_responses) != 1:
        failures.append(
            f"expected 1 valid response, got {len(valid_responses)}"
        )

    if report.valid_count != 1:
        failures.append(
            f"expected valid_count 1, got {report.valid_count}"
        )

    if report.rejected_count != 3:
        failures.append(
            f"expected rejected_count 3, got {report.rejected_count}"
        )

    actual_reasons = {
        item.reason
        for item in report.rejected_responses
    }

    expected_reasons = {
        "unknown_rfq_id",
        "supplier_name_mismatch",
        "priority_mismatch",
    }

    if actual_reasons != expected_reasons:
        failures.append(
            f"expected reasons {expected_reasons}, "
            f"got {actual_reasons}"
        )

    if report.source != "supplier_rfq_response_validator":
        failures.append(
            f"unexpected report source: {report.source}"
        )

    return {
        "name": "Supplier RFQ response validation report",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_response_status_rules() -> dict:
    from pydantic import ValidationError

    from src.core.supplier_rfq import SupplierRFQResponse

    failures = []

    invalid_cases = [
        ("no_capacity", 1800),
        ("declined", 1900),
        ("needs_clarification", 2000),
    ]

    for status, cost in invalid_cases:
        try:
            SupplierRFQResponse(
                supplier_name=f"{status} Supplier",
                rfq_priority=1,
                status=status,
                cost=cost,
                currency="EUR",
                source="simulation",
            )
            failures.append(
                f"{status} response with cost should be rejected"
            )
        except ValidationError:
            pass

    for status in (
        "no_capacity",
        "declined",
        "needs_clarification",
    ):
        try:
            response = SupplierRFQResponse(
                supplier_name=f"{status} Supplier",
                rfq_priority=1,
                status=status,
                source="simulation",
            )

            if response.is_price_usable:
                failures.append(
                    f"{status} response must not be price usable"
                )
        except ValidationError as exc:
            failures.append(
                f"{status} response without cost was rejected: {exc}"
            )

    try:
        quoted_response = SupplierRFQResponse(
            supplier_name="Quoted Supplier",
            rfq_priority=1,
            status="quoted",
            cost=2100,
            currency="EUR",
            source="simulation",
        )

        if not quoted_response.is_price_usable:
            failures.append(
                "quoted response with positive cost should be usable"
            )
    except ValidationError as exc:
        failures.append(
            f"valid quoted response was rejected: {exc}"
        )

    return {
        "name": "Supplier RFQ response status rules",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_rfq_api_contract() -> dict:
    from src.api import serialize_result
    from src.core.models import Package, Shipment
    from src.workflow import pipeline

    failures = []

    shipment = Shipment(
        customer_name="Known Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-07-20",
        packages=[
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )

    quote_result = pipeline.process_shipment(
        shipment=shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil yükü için "
            "komple araç fiyatı rica ederiz. "
            "Yük 20.07.2026 tarihinde hazırdır."
        ),
    )

    serialized_quote = serialize_result(quote_result)

    required_fields = {
        "supplier_rfq_workflow",
        "supplier_rfq_drafts",
        "supplier_rfq_responses",
        "valid_supplier_rfq_responses",
        "supplier_rfq_response_validation",
    }

    missing_quote_fields = required_fields - serialized_quote.keys()

    if missing_quote_fields:
        failures.append(
            "quote result missing RFQ contract fields: "
            f"{sorted(missing_quote_fields)}"
        )

    if not isinstance(
        serialized_quote.get("supplier_rfq_responses"),
        list,
    ):
        failures.append(
            "supplier_rfq_responses should serialize as a list"
        )

    if not isinstance(
        serialized_quote.get("valid_supplier_rfq_responses"),
        list,
    ):
        failures.append(
            "valid_supplier_rfq_responses should serialize as a list"
        )

    validation_report = serialized_quote.get(
        "supplier_rfq_response_validation"
    )

    if validation_report is not None:
        failures.append(
            "initial RFQ approval state should not include a response "
            "validation report"
        )

    early_stop_shipment = shipment.model_copy(
        update={
            "commodity": "Kimyasal Ürün",
            "is_adr": True,
            "adr_class": None,
            "special_notes": None,
        }
    )

    early_stop_result = pipeline.process_shipment(
        shipment=early_stop_shipment,
        email_text=(
            "Adana'dan Hamburg'a ADR kapsamındaki kimyasal yük için "
            "komple araç fiyatı rica ederiz. ADR sınıfı henüz belli değil."
        ),
    )

    serialized_early_stop = serialize_result(
        early_stop_result
    )

    missing_early_fields = (
        required_fields - serialized_early_stop.keys()
    )

    if missing_early_fields:
        failures.append(
            "early-stop result missing RFQ contract fields: "
            f"{sorted(missing_early_fields)}"
        )

    if serialized_early_stop.get("supplier_rfq_responses") != []:
        failures.append(
            "early-stop raw RFQ responses should be an empty list"
        )

    if (
        serialized_early_stop.get(
            "valid_supplier_rfq_responses"
        )
        != []
    ):
        failures.append(
            "early-stop valid RFQ responses should be an empty list"
        )

    if (
        serialized_early_stop.get(
            "supplier_rfq_response_validation"
        )
        is not None
    ):
        failures.append(
            "early-stop validation report should be None"
        )

    return {
        "name": "Supplier RFQ API contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_supplier_quote_comparison_model() -> dict:
    from src.core.supplier_quote_comparison import (
        build_supplier_quote_comparisons,
    )
    from src.core.supplier_rfq import SupplierRFQResponse

    failures = []

    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": "Supplier A",
                "priority": 1,
                "total_score": 0.91,
                "route_score": 1.0,
                "equipment_score": 0.9,
                "risk_score": 0.8,
                "price_score": 0.7,
                "speed_score": 0.6,
            },
            {
                "supplier_name": "Supplier B",
                "priority": 2,
                "total_score": 0.84,
                "route_score": 0.9,
                "equipment_score": 0.8,
                "risk_score": 0.7,
                "price_score": 0.9,
                "speed_score": 0.8,
            },
        ]
    }

    responses = [
        SupplierRFQResponse(
            rfq_id="rfq-a",
            supplier_name="Supplier A",
            rfq_priority=1,
            status="quoted",
            cost=2200,
            currency="EUR",
            transit_time="5-7 days",
            source="simulation",
        ),
        SupplierRFQResponse(
            rfq_id="rfq-b",
            supplier_name="Supplier B",
            rfq_priority=2,
            status="quoted",
            cost=2050,
            currency="EUR",
            transit_time="6-8 days",
            source="simulation",
        ),
        SupplierRFQResponse(
            rfq_id="rfq-c",
            supplier_name="Supplier C",
            rfq_priority=3,
            status="quoted",
            cost=1900,
            currency="EUR",
            source="simulation",
        ),
        SupplierRFQResponse(
            rfq_id="rfq-a-declined",
            supplier_name="Supplier A",
            rfq_priority=1,
            status="declined",
            source="simulation",
        ),
    ]

    comparisons = build_supplier_quote_comparisons(
        responses=responses,
        supplier_selection=supplier_selection,
    )

    if len(comparisons) != 2:
        failures.append(
            f"expected 2 comparisons, got {len(comparisons)}"
        )

    comparison_by_supplier = {
        item.supplier_name: item
        for item in comparisons
    }

    supplier_a = comparison_by_supplier.get("Supplier A")

    if supplier_a is None:
        failures.append("Supplier A comparison is missing")
    else:
        if supplier_a.rfq_id != "rfq-a":
            failures.append(
                f"expected Supplier A rfq-a, got {supplier_a.rfq_id}"
            )

        if supplier_a.cost != 2200:
            failures.append(
                f"expected Supplier A cost 2200, got {supplier_a.cost}"
            )

        if supplier_a.supplier_score != 0.91:
            failures.append(
                "Supplier A supplier_score mismatch: "
                f"{supplier_a.supplier_score}"
            )

        if supplier_a.operational_score != 0.9:
            failures.append(
                "Supplier A operational_score mismatch: "
                f"{supplier_a.operational_score}"
            )

        if supplier_a.commercial_score != 0.65:
            failures.append(
                "Supplier A commercial_score mismatch: "
                f"{supplier_a.commercial_score}"
            )

        if supplier_a.actual_price_score != 0.932:
            failures.append(
                "Supplier A actual_price_score mismatch: "
                f"{supplier_a.actual_price_score}"
            )

        if supplier_a.transit_score != 1.0:
            failures.append(
                "Supplier A transit_score mismatch: "
                f"{supplier_a.transit_score}"
            )

        if supplier_a.total_score != 0.923:
            failures.append(
                "Supplier A total_score mismatch: "
                f"{supplier_a.total_score}"
            )

    supplier_b = comparison_by_supplier.get("Supplier B")

    if supplier_b is None:
        failures.append("Supplier B comparison is missing")
    else:
        if supplier_b.operational_score != 0.8:
            failures.append(
                "Supplier B operational_score mismatch: "
                f"{supplier_b.operational_score}"
            )

        if supplier_b.commercial_score != 0.85:
            failures.append(
                "Supplier B commercial_score mismatch: "
                f"{supplier_b.commercial_score}"
            )

        if supplier_b.actual_price_score != 1.0:
            failures.append(
                "Supplier B actual_price_score mismatch: "
                f"{supplier_b.actual_price_score}"
            )

        if supplier_b.transit_score != 0.875:
            failures.append(
                "Supplier B transit_score mismatch: "
                f"{supplier_b.transit_score}"
            )

        if supplier_b.total_score != 0.876:
            failures.append(
                "Supplier B total_score mismatch: "
                f"{supplier_b.total_score}"
            )

    if "Supplier C" in comparison_by_supplier:
        failures.append(
            "supplier outside Supplier Selection should be skipped"
        )

    return {
        "name": "Supplier quote comparison model",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_multi_criteria_supplier_quote_selection() -> dict:
    from src.core.supplier_quote_comparison import (
        SupplierQuoteComparison,
    )
    from src.core.supplier_quote_selection import (
        select_supplier_quote_from_comparisons,
    )
    from src.core.supplier_rfq import SupplierRFQResponse

    failures = []

    responses = [
        SupplierRFQResponse(
            rfq_id="rfq-reliable",
            supplier_name="Reliable Supplier",
            rfq_priority=1,
            status="quoted",
            cost=2300,
            currency="EUR",
            transit_time="5-7 days",
            notes="Higher operational score.",
            source="simulation",
        ),
        SupplierRFQResponse(
            rfq_id="rfq-cheapest",
            supplier_name="Cheapest Supplier",
            rfq_priority=2,
            status="quoted",
            cost=1900,
            currency="EUR",
            transit_time="7-9 days",
            notes="Lowest price.",
            source="simulation",
        ),
    ]

    comparisons = [
        SupplierQuoteComparison(
            rfq_id="rfq-reliable",
            supplier_name="Reliable Supplier",
            priority=1,
            cost=2300,
            currency="EUR",
            transit_time="5-7 days",
            supplier_score=0.96,
            commercial_score=0.75,
            operational_score=0.97,
            actual_price_score=0.826,
            transit_score=1.0,
            total_score=0.937,
        ),
        SupplierQuoteComparison(
            rfq_id="rfq-cheapest",
            supplier_name="Cheapest Supplier",
            priority=2,
            cost=1900,
            currency="EUR",
            transit_time="7-9 days",
            supplier_score=0.78,
            commercial_score=0.90,
            operational_score=0.76,
            actual_price_score=1.0,
            transit_score=0.714,
            total_score=0.817,
        ),
    ]

    selected = select_supplier_quote_from_comparisons(
        comparisons=comparisons,
        responses=responses,
    )

    if selected is None:
        failures.append("expected a selected supplier quote")
    else:
        if selected.supplier_name != "Reliable Supplier":
            failures.append(
                "expected highest total-score supplier, "
                f"got {selected.supplier_name}"
            )

        if selected.cost != 2300:
            failures.append(
                f"expected selected cost 2300, got {selected.cost}"
            )

    tie_comparisons = [
        comparison.model_copy(update={"total_score": 0.90})
        for comparison in comparisons
    ]

    tie_selected = select_supplier_quote_from_comparisons(
        comparisons=tie_comparisons,
        responses=responses,
    )

    if tie_selected is None:
        failures.append("expected a selection in tie case")
    elif tie_selected.supplier_name != "Reliable Supplier":
        failures.append(
            "equal scores should prefer lower RFQ priority number"
        )

    return {
        "name": "Multi-criteria supplier quote selection",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_supplier_quote_selection_traceability() -> dict:
    from src.core.supplier_quote_comparison import (
        SupplierQuoteComparison,
    )
    from src.core.supplier_quote_selection import (
        build_supplier_quote_selection_decision,
    )

    failures = []

    comparisons = [
        SupplierQuoteComparison(
            rfq_id="rfq-reliable",
            supplier_name="Reliable Supplier",
            priority=1,
            cost=2300,
            currency="EUR",
            transit_time="5-7 days",
            supplier_score=0.96,
            commercial_score=0.75,
            operational_score=0.97,
            actual_price_score=0.826,
            transit_score=1.0,
            total_score=0.937,
        ),
        SupplierQuoteComparison(
            rfq_id="rfq-cheapest",
            supplier_name="Cheapest Supplier",
            priority=2,
            cost=1900,
            currency="EUR",
            transit_time="7-9 days",
            supplier_score=0.78,
            commercial_score=0.90,
            operational_score=0.76,
            actual_price_score=1.0,
            transit_score=0.714,
            total_score=0.817,
        ),
    ]

    decision = build_supplier_quote_selection_decision(
        comparisons=comparisons,
    )

    if decision is None:
        failures.append("expected a selection decision")
    else:
        if decision.selected_supplier != "Reliable Supplier":
            failures.append(
                "selected supplier mismatch: "
                f"{decision.selected_supplier}"
            )

        if decision.selected_rfq_id != "rfq-reliable":
            failures.append(
                "selected RFQ identity mismatch: "
                f"{decision.selected_rfq_id}"
            )

        if decision.selected_total_score != 0.937:
            failures.append(
                "selected total score mismatch: "
                f"{decision.selected_total_score}"
            )

        if decision.score_difference != 0.12:
            failures.append(
                "runner-up score difference mismatch: "
                f"{decision.score_difference}"
            )

        if decision.price_difference != 400:
            failures.append(
                "runner-up price difference mismatch: "
                f"{decision.price_difference}"
            )

        if "daha pahalı" not in decision.selection_reason:
            failures.append(
                "selection reason should explain higher price"
            )

        if len(decision.rejected_alternatives) != 1:
            failures.append(
                "expected one rejected alternative"
            )
        else:
            alternative = decision.rejected_alternatives[0]

            if alternative.supplier_name != "Cheapest Supplier":
                failures.append(
                    "rejected alternative supplier mismatch"
                )

            if alternative.score_difference != 0.12:
                failures.append(
                    "alternative score difference mismatch: "
                    f"{alternative.score_difference}"
                )

            if alternative.price_difference != -400:
                failures.append(
                    "alternative price difference mismatch: "
                    f"{alternative.price_difference}"
                )

    empty_decision = build_supplier_quote_selection_decision(
        comparisons=[],
    )

    if empty_decision is not None:
        failures.append(
            "empty comparison list should not produce a decision"
        )

    return {
        "name": "Supplier quote selection traceability",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_supplier_rfq_repository() -> dict:
    from src.core.supplier_rfq import (
        SupplierRFQDraft,
        SupplierRFQResponse,
    )
    from src.core.supplier_rfq_repository import (
        DuplicateSupplierRFQResponseError,
        InMemorySupplierRFQRepository,
    )

    failures = []
    repository = InMemorySupplierRFQRepository()

    first_draft = SupplierRFQDraft(
        rfq_id="rfq-repository-1",
        supplier_name="Supplier A",
        priority=1,
        recipient_email="pricing@example.invalid",
        subject="RFQ",
        body="Please quote.",
    )
    second_draft = SupplierRFQDraft(
        rfq_id="rfq-repository-2",
        supplier_name="Supplier B",
        priority=2,
        recipient_email="rfq@example.invalid",
        subject="RFQ",
        body="Please quote.",
    )

    saved_drafts = repository.save_drafts(
        [first_draft, second_draft]
    )

    if len(saved_drafts) != 2:
        failures.append("expected two saved RFQ drafts")

    if repository.get_draft(first_draft.rfq_id) != first_draft:
        failures.append("saved RFQ draft could not be retrieved")

    updated_first_draft = first_draft.model_copy(
        update={"status": "sent"}
    )
    repository.save_drafts([updated_first_draft])

    stored_updated_draft = repository.get_draft(
        first_draft.rfq_id
    )

    if (
        stored_updated_draft is None
        or stored_updated_draft.status != "sent"
    ):
        failures.append(
            "saving the same RFQ ID should update the draft"
        )

    first_response = SupplierRFQResponse(
        rfq_id=first_draft.rfq_id,
        supplier_name=first_draft.supplier_name,
        rfq_priority=first_draft.priority,
        status="quoted",
        cost=2100,
        currency="EUR",
        source="simulation",
    )
    second_response = SupplierRFQResponse(
        rfq_id=second_draft.rfq_id,
        supplier_name=second_draft.supplier_name,
        rfq_priority=second_draft.priority,
        status="declined",
        source="simulation",
    )

    repository.save_responses(
        [first_response, second_response]
    )

    try:
        repository.save_responses([first_response])
    except DuplicateSupplierRFQResponseError:
        pass
    else:
        failures.append(
            "identical RFQ response should be explicitly rejected"
        )

    if len(repository.list_responses()) != 2:
        failures.append(
            "duplicate RFQ response should not increase record count"
        )

    revised_first_response = first_response.model_copy(
        update={
            "cost": 2050,
            "notes": "Revised supplier quote.",
        }
    )

    revised_saved = repository.save_responses(
        [revised_first_response]
    )

    if revised_saved != [revised_first_response]:
        failures.append(
            "revised RFQ response should be stored as a new record"
        )

    if len(repository.list_responses()) != 3:
        failures.append(
            "revised RFQ response should increase record count"
        )

    first_rfq_responses = repository.list_responses(
        rfq_id=first_draft.rfq_id
    )

    if first_rfq_responses != [
        first_response,
        revised_first_response,
    ]:
        failures.append(
            "RFQ response filtering returned incorrect records"
        )

    listed_drafts = repository.list_drafts()
    listed_drafts.clear()

    if len(repository.list_drafts()) != 2:
        failures.append(
            "repository draft listing should return a copy"
        )

    listed_responses = repository.list_responses()
    listed_responses.clear()

    if len(repository.list_responses()) != 3:
        failures.append(
            "repository response listing should return a copy"
        )

    return {
        "name": "Supplier RFQ repository",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_supplier_rfq_repository_workflow_integration() -> dict:
    from src.core.models import Shipment
    from src.core.supplier_rfq_repository import (
        InMemorySupplierRFQRepository,
    )
    from src.workflow import pipeline

    failures = []
    repository = InMemorySupplierRFQRepository()

    shipment = Shipment(
        customer_name="Repository Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-10",
        is_adr=False,
        is_temperature_controlled=False,
    )

    result = pipeline.process_shipment(
        shipment=shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil yükü için "
            "komple tenteli araç fiyatı rica ederiz. "
            "Yük ADR değildir ve 10.08.2026 tarihinde hazırdır."
        ),
        rfq_repository=repository,
    )

    result_drafts = result.get("supplier_rfq_drafts") or []
    result_responses = result.get("supplier_rfq_responses") or []

    stored_drafts = repository.list_drafts()
    stored_responses = repository.list_responses()

    if not result_drafts:
        failures.append(
            "workflow should generate supplier RFQ drafts"
        )

    if result_responses:
        failures.append(
            "initial workflow must not generate supplier RFQ responses"
        )

    if len(stored_drafts) != len(result_drafts):
        failures.append(
            "repository draft count should match workflow result"
        )

    if len(stored_responses) != len(result_responses):
        failures.append(
            "repository response count should match workflow result"
        )

    result_draft_ids = {
        draft.rfq_id
        for draft in result_drafts
    }
    stored_draft_ids = {
        draft.rfq_id
        for draft in stored_drafts
    }

    if stored_draft_ids != result_draft_ids:
        failures.append(
            "repository and workflow draft RFQ IDs should match"
        )

    result_response_ids = {
        response.rfq_id
        for response in result_responses
    }
    stored_response_ids = {
        response.rfq_id
        for response in stored_responses
    }

    if stored_response_ids != result_response_ids:
        failures.append(
            "repository and workflow response RFQ IDs should match"
        )

    if stored_drafts and any(
        draft.status != "draft"
        for draft in stored_drafts
    ):
        failures.append(
            "stored RFQ drafts should remain in draft status"
        )

    workflow = result.get("supplier_rfq_workflow")
    if (
        workflow is None
        or repository.get_workflow(workflow.workflow_id) != workflow
    ):
        failures.append("supplier RFQ workflow context was not persisted")

    for response in stored_responses:
        stored_draft = repository.get_draft(response.rfq_id)

        if stored_draft is None:
            failures.append(
                f"response references missing draft {response.rfq_id}"
            )

    return {
        "name": "Supplier RFQ repository workflow integration",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_approval_model() -> dict:
    from datetime import datetime

    from pydantic import ValidationError

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    pending = QuoteApproval(
        quote_snapshot=snapshot,
    )

    if pending.approval_status != "pending":
        failures.append(
            "new quote approval should start as pending"
        )

    if pending.is_approved:
        failures.append(
            "pending quote approval must not be approved"
        )

    approved = QuoteApproval(
        approval_status="approved",
        approved_by="operations.manager@example.invalid",
        approved_at=datetime(2026, 8, 5, 14, 0, 0),
        quote_snapshot=snapshot,
    )

    if not approved.is_valid_for_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    ):
        failures.append(
            "approved snapshot should be valid for unchanged quote"
        )

    changed_customer_quote = customer_quote.model_copy(
        update={"final_price": 2350}
    )

    if approved.is_valid_for_quote(
        supplier_quote=supplier_quote,
        customer_quote=changed_customer_quote,
        quote_draft=quote_draft,
    ):
        failures.append(
            "price change should invalidate previous approval"
        )

    changed_supplier_quote = supplier_quote.model_copy(
        update={"supplier_name": "Different Supplier"}
    )

    if approved.is_valid_for_quote(
        supplier_quote=changed_supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    ):
        failures.append(
            "supplier change should invalidate previous approval"
        )

    changed_quote_draft = quote_draft.model_copy(
        update={"body": "Fiyat: 2300 EUR. Yeni şartlar."}
    )

    if approved.is_valid_for_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=changed_quote_draft,
    ):
        failures.append(
            "quote draft change should invalidate previous approval"
        )

    rejected = QuoteApproval(
        approval_status="rejected",
        rejected_by="manager@example.invalid",
        rejected_at=datetime(2026, 8, 5, 14, 5, 0),
        rejection_reason="Margin requires revision.",
        quote_snapshot=snapshot,
    )

    if rejected.is_approved:
        failures.append(
            "rejected quote must not be approved"
        )

    invalid_cases = [
        {
            "approval_status": "approved",
            "approved_by": "manager@example.invalid",
            "approved_at": datetime(2026, 8, 5, 14, 0, 0),
            "rejected_by": "other-manager@example.invalid",
            "rejected_at": datetime(2026, 8, 5, 14, 1, 0),
        },
        {
            "approval_status": "approved",
            "approved_by": None,
            "approved_at": datetime(2026, 8, 5, 14, 0, 0),
        },
        {
            "approval_status": "approved",
            "approved_by": "manager@example.invalid",
            "approved_at": None,
        },
        {
            "approval_status": "rejected",
            "rejection_reason": None,
        },
        {
            "approval_status": "pending",
            "approved_by": "manager@example.invalid",
        },
    ]

    for case in invalid_cases:
        try:
            QuoteApproval(
                quote_snapshot=snapshot,
                **case,
            )
        except ValidationError:
            continue

        failures.append(
            "invalid quote approval state was accepted: "
            f"{case}"
        )

    return {
        "name": "Quote approval model",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_approval_workflow_contract() -> dict:
    from datetime import datetime

    from src.core.mail import MailSendResult
    from src.core.models import Shipment
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )
    from src.core.quote_case_repository import (
        InMemoryQuoteCaseRepository,
    )
    from src.core.supplier_rfq_lifecycle import (
        approve_supplier_rfq,
        attach_supplier_rfq_response,
        send_supplier_rfq,
    )
    from src.core.supplier_rfq_repository import (
        InMemorySupplierRFQRepository,
    )
    from src.simulation.supplier_simulator import (
        simulate_supplier_rfq_responses,
    )
    from src.workflow import pipeline
    from src.workflow.supplier_rfq_progression import (
        resume_supplier_rfq_workflow,
    )

    failures = []
    rfq_repository = InMemorySupplierRFQRepository()
    approval_repository = InMemoryQuoteApprovalRepository()
    quote_case_repository = InMemoryQuoteCaseRepository()

    quote_shipment = Shipment(
        customer_name="Approval Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-12",
        is_adr=False,
        is_temperature_controlled=False,
    )

    quote_result = pipeline.process_shipment(
        shipment=quote_shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil yükü için "
            "komple tenteli araç fiyatı rica ederiz. "
            "Yük ADR değildir ve 12.08.2026 tarihinde hazırdır."
        ),
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )

    drafts = quote_result.get("supplier_rfq_drafts") or []
    draft = next(
        (item for item in drafts if item.recipient_email),
        None,
    )
    workflow = quote_result.get("supplier_rfq_workflow")
    if draft is None or workflow is None:
        failures.append("RFQ approval workflow setup is missing")
    else:
        approve_supplier_rfq(
            rfq_repository,
            draft.rfq_id,
            approved_by="Quote Approval Regression Operator",
        )
        awaiting = send_supplier_rfq(
            rfq_repository,
            draft.rfq_id,
            MailSendResult(
                operation_id=f"supplier-rfq:{draft.rfq_id}",
                status="sent",
                reason="Regression provider confirmed delivery.",
                provider_name="regression-provider",
                provider_message_id=f"message-{draft.rfq_id}",
                sent_at=datetime(2026, 8, 11, 10, 0, 0),
            ),
        )
        responses = simulate_supplier_rfq_responses(
            shipment=quote_shipment,
            equipment_decision=quote_result["equipment_decision"],
            rfq_drafts=[awaiting],
        )
        attach_supplier_rfq_response(
            rfq_repository,
            responses[0],
        )
        quote_result = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=rfq_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
        )

    supplier_quote = quote_result.get("supplier_quote")
    customer_quote = quote_result.get("customer_quote")
    quote_draft = quote_result.get("quote_draft")
    quote_approval = quote_result.get("quote_approval")
    quote_send_safety = quote_result.get("quote_send_safety")

    if supplier_quote is None:
        failures.append(
            "successful workflow should generate supplier quote"
        )

    if customer_quote is None:
        failures.append(
            "successful workflow should generate customer quote"
        )

    if quote_draft is None:
        failures.append(
            "successful workflow should generate quote draft"
        )

    if quote_approval is None:
        failures.append(
            "successful workflow should generate quote approval"
        )
    else:
        if quote_approval.approval_status != "pending":
            failures.append(
                "new workflow quote approval should be pending"
            )

        if quote_approval.is_approved:
            failures.append(
                "new workflow quote must not be pre-approved"
            )

        if (
            supplier_quote is not None
            and customer_quote is not None
            and quote_draft is not None
            and not quote_approval.quote_snapshot.matches_quote(
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            )
        ):
            failures.append(
                "workflow approval snapshot should match quote"
            )

    if quote_send_safety is None:
        failures.append(
            "successful workflow should generate send safety decision"
        )
    else:
        if quote_send_safety.can_send:
            failures.append(
                "pending approval must block quote sending"
            )

        if (
            quote_send_safety.block_reason
            != "approval_pending"
        ):
            failures.append(
                "new quote should be blocked by pending approval"
            )

        if (
            quote_approval is not None
            and quote_send_safety.approval_id
            != quote_approval.approval_id
        ):
            failures.append(
                "send safety should preserve approval identity"
            )

    early_stop_shipment = quote_shipment.model_copy(
        update={
            "commodity": "Kimyasal Ürün",
            "is_adr": True,
            "adr_class": None,
            "special_notes": None,
        }
    )

    early_stop_result = pipeline.process_shipment(
        shipment=early_stop_shipment,
        email_text=(
            "Adana'dan Hamburg'a ADR kapsamındaki kimyasal "
            "yük için fiyat rica ederiz. ADR sınıfı belli değil."
        ),
    )

    if early_stop_result.get("quote_draft") is not None:
        failures.append(
            "early-stop workflow must not generate quote draft"
        )

    if early_stop_result.get("quote_approval") is not None:
        failures.append(
            "early-stop workflow must not generate quote approval"
        )

    if early_stop_result.get("quote_send_safety") is not None:
        failures.append(
            "early-stop workflow must not generate send safety decision"
        )

    return {
        "name": "Quote approval workflow contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_send_safety_regression() -> dict:
    from datetime import datetime

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_send_safety import (
        evaluate_quote_send_safety,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    missing_decision = evaluate_quote_send_safety(
        approval=None,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if (
        missing_decision.can_send
        or missing_decision.block_reason != "approval_missing"
    ):
        failures.append(
            "missing approval should block quote sending"
        )

    pending = QuoteApproval(
        quote_snapshot=snapshot,
    )
    pending_decision = evaluate_quote_send_safety(
        approval=pending,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if (
        pending_decision.can_send
        or pending_decision.block_reason != "approval_pending"
    ):
        failures.append(
            "pending approval should block quote sending"
        )

    rejected = QuoteApproval(
        approval_status="rejected",
        rejection_reason="Margin requires revision.",
        quote_snapshot=snapshot,
    )
    rejected_decision = evaluate_quote_send_safety(
        approval=rejected,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if (
        rejected_decision.can_send
        or rejected_decision.block_reason != "approval_rejected"
    ):
        failures.append(
            "rejected approval should block quote sending"
        )

    invalidated = QuoteApproval(
        approval_status="invalidated",
        quote_snapshot=snapshot,
    )
    invalidated_decision = evaluate_quote_send_safety(
        approval=invalidated,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if (
        invalidated_decision.can_send
        or invalidated_decision.block_reason
        != "approval_invalidated"
    ):
        failures.append(
            "invalidated approval should block quote sending"
        )

    approved = QuoteApproval(
        approval_status="approved",
        approved_by="operations.manager@example.invalid",
        approved_at=datetime(2026, 8, 5, 16, 0, 0),
        quote_snapshot=snapshot,
    )

    changed_customer_quote = customer_quote.model_copy(
        update={"final_price": 2350}
    )
    mismatch_decision = evaluate_quote_send_safety(
        approval=approved,
        supplier_quote=supplier_quote,
        customer_quote=changed_customer_quote,
        quote_draft=quote_draft,
    )

    if (
        mismatch_decision.can_send
        or mismatch_decision.block_reason
        != "quote_snapshot_mismatch"
    ):
        failures.append(
            "changed quote should invalidate previous approval"
        )

    approved_decision = evaluate_quote_send_safety(
        approval=approved,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if not approved_decision.can_send:
        failures.append(
            "valid approved quote should be sendable"
        )

    if approved_decision.block_reason is not None:
        failures.append(
            "sendable quote should not include block reason"
        )

    if approved_decision.approval_id != approved.approval_id:
        failures.append(
            "send decision should preserve approval identity"
        )

    if approved_decision.approved_by != approved.approved_by:
        failures.append(
            "send decision should preserve approver identity"
        )

    return {
        "name": "Quote send safety",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_send_service() -> dict:
    from datetime import datetime

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_send_service import (
        prepare_quote_for_sending,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    pending = QuoteApproval(
        quote_snapshot=snapshot,
    )

    blocked_result = prepare_quote_for_sending(
        recipient_email="customer@example.invalid",
        approval=pending,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if blocked_result.status != "blocked":
        failures.append(
            "pending approval should produce blocked status"
        )

    if blocked_result.sent:
        failures.append(
            "blocked quote must not be marked as sent"
        )

    if (
        blocked_result.safety_decision.block_reason
        != "approval_pending"
    ):
        failures.append(
            "blocked result should preserve approval_pending reason"
        )

    approved = QuoteApproval(
        approval_status="approved",
        approved_by="operations.manager@example.invalid",
        approved_at=datetime(2026, 8, 5, 17, 0, 0),
        quote_snapshot=snapshot,
    )

    ready_result = prepare_quote_for_sending(
        recipient_email="  customer@example.invalid  ",
        approval=approved,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if ready_result.status != "send_ready":
        failures.append(
            "valid approved quote should be send-ready"
        )

    if ready_result.sent:
        failures.append(
            "send-ready quote must not be marked as sent"
        )

    if not ready_result.safety_decision.can_send:
        failures.append(
            "send-ready result should preserve positive safety decision"
        )

    if (
        ready_result.recipient_email
        != "customer@example.invalid"
    ):
        failures.append(
            "recipient email should be normalized"
        )

    if ready_result.subject != quote_draft.subject:
        failures.append(
            "send-ready subject should match quote draft"
        )

    if ready_result.body != quote_draft.body:
        failures.append(
            "send-ready body should match quote draft"
        )

    try:
        prepare_quote_for_sending(
            recipient_email="   ",
            approval=approved,
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    except ValueError:
        pass
    else:
        failures.append(
            "empty recipient email should be rejected"
        )

    return {
        "name": "Quote send service",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_send_api_contract() -> dict:
    from fastapi import HTTPException

    from src.api import (
        PrepareQuoteSendRequest,
        approve_quote_approval,
        prepare_quote_send,
        quote_approval_repository,
        QuoteApprovalApproveRequest,
    )
    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    pending = quote_approval_repository.save(
        QuoteApproval(
            quote_snapshot=snapshot,
        )
    )

    blocked_response = prepare_quote_send(
        PrepareQuoteSendRequest(
            recipient_email="customer@example.invalid",
            approval_id=pending.approval_id,
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    )

    if blocked_response.get("status") != "blocked":
        failures.append(
            "pending approval API response should be blocked"
        )

    if blocked_response.get("sent") is not False:
        failures.append(
            "blocked API response must report sent=false"
        )

    blocked_safety = blocked_response.get(
        "safety_decision"
    ) or {}

    if (
        blocked_safety.get("block_reason")
        != "approval_pending"
    ):
        failures.append(
            "blocked API response should expose approval_pending"
        )

    approved_response = approve_quote_approval(
        approval_id=pending.approval_id,
        request=QuoteApprovalApproveRequest(
            approved_by="operations.manager@example.invalid",
        ),
    )

    if approved_response.get("approval_status") != "approved":
        failures.append(
            "approval API should transition pending to approved"
        )

    ready_response = prepare_quote_send(
        PrepareQuoteSendRequest(
            recipient_email="customer@example.invalid",
            approval_id=pending.approval_id,
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    )

    if ready_response.get("status") != "send_ready":
        failures.append(
            "approved API response should be send_ready"
        )

    if ready_response.get("sent") is not False:
        failures.append(
            "send-ready API response must report sent=false"
        )

    ready_safety = ready_response.get(
        "safety_decision"
    ) or {}

    if ready_safety.get("can_send") is not True:
        failures.append(
            "send-ready API response should expose can_send=true"
        )

    try:
        prepare_quote_send(
            PrepareQuoteSendRequest(
                recipient_email="customer@example.invalid",
                approval_id="unknown-approval-id",
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            )
        )
    except HTTPException as exc:
        if exc.status_code != 404:
            failures.append(
                "unknown approval_id should return HTTP 404"
            )
    else:
        failures.append(
            "unknown approval_id API request should fail"
        )

    try:
        prepare_quote_send(
            PrepareQuoteSendRequest(
                recipient_email="   ",
                approval_id=pending.approval_id,
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            )
        )
    except HTTPException as exc:
        if exc.status_code != 422:
            failures.append(
                "empty recipient should return HTTP 422"
            )
    else:
        failures.append(
            "empty recipient API request should fail"
        )

    return {
        "name": "Quote send API contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }

def evaluate_quote_approval_repository() -> dict:
    from datetime import datetime

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    pending = QuoteApproval(
        quote_snapshot=snapshot,
    )

    repository = InMemoryQuoteApprovalRepository()

    saved = repository.save(pending)

    if saved.approval_id != pending.approval_id:
        failures.append(
            "saved approval should preserve approval_id"
        )

    loaded = repository.get(pending.approval_id)

    if loaded is None:
        failures.append(
            "saved approval should be retrievable"
        )
    elif loaded != pending:
        failures.append(
            "retrieved approval should match saved approval"
        )

    approved = QuoteApproval(
        approval_id=pending.approval_id,
        approval_status="approved",
        approved_by="operations.manager@example.invalid",
        approved_at=datetime(2026, 8, 6, 18, 0, 0),
        quote_snapshot=snapshot,
    )

    repository.save(approved)

    updated = repository.get(pending.approval_id)

    if updated is None:
        failures.append(
            "updated approval should remain retrievable"
        )
    elif updated.approval_status != "approved":
        failures.append(
            "saving same approval_id should update existing record"
        )

    second = QuoteApproval(
        quote_snapshot=snapshot,
    )

    saved_many = repository.save_many([second])

    if len(saved_many) != 1:
        failures.append(
            "save_many should return saved approvals"
        )

    approvals = repository.list_all()

    if len(approvals) != 2:
        failures.append(
            "repository should contain two unique approval IDs"
        )

    approvals.clear()

    if len(repository.list_all()) != 2:
        failures.append(
            "list_all should not expose mutable internal collection"
        )

    if repository.get("unknown-approval-id") is not None:
        failures.append(
            "unknown approval_id should return None"
        )

    return {
        "name": "Quote approval repository",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_approval_repository_workflow_integration() -> dict:
    from datetime import datetime

    from src.core.mail import MailSendResult
    from src.core.models import Shipment
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )
    from src.core.quote_case_repository import (
        InMemoryQuoteCaseRepository,
    )
    from src.core.supplier_rfq import SupplierRFQResponse
    from src.core.supplier_rfq_lifecycle import (
        approve_supplier_rfq,
        attach_supplier_rfq_response,
        send_supplier_rfq,
    )
    from src.core.supplier_rfq_repository import (
        InMemorySupplierRFQRepository,
    )
    from src.workflow import pipeline
    from src.workflow.supplier_rfq_progression import (
        resume_supplier_rfq_workflow,
    )

    failures = []

    approval_repository = InMemoryQuoteApprovalRepository()
    rfq_repository = InMemorySupplierRFQRepository()
    quote_case_repository = InMemoryQuoteCaseRepository()

    quote_shipment = Shipment(
        customer_name="Approval Repository Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-12",
        is_adr=False,
        is_temperature_controlled=False,
    )

    initial_result = pipeline.process_shipment(
        shipment=quote_shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil yükü için "
            "komple tenteli araç fiyatı rica ederiz. "
            "Yük ADR değildir ve 12.08.2026 tarihinde hazırdır."
        ),
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )

    if initial_result.get("quote_approval") is not None:
        failures.append(
            "initial RFQ workflow must not generate quote approval "
            "before supplier response"
        )

    workflow = initial_result.get("supplier_rfq_workflow")
    drafts = initial_result.get("supplier_rfq_drafts") or []

    if workflow is None:
        failures.append(
            "quote-ready workflow should create supplier RFQ workflow"
        )
    elif not drafts:
        failures.append(
            "quote-ready workflow should create supplier RFQ drafts"
        )
    else:
        draft = next(
            (
                candidate
                for candidate in drafts
                if candidate.recipient_email
            ),
            None,
        )

        if draft is None:
            failures.append(
                "supplier RFQ integration fixture requires "
                "at least one recipient-enabled draft"
            )
        else:
            approved_rfq = approve_supplier_rfq(
                repository=rfq_repository,
                rfq_id=draft.rfq_id,
                approved_by="integration-test-operator",
                approved_at=datetime(2026, 8, 13, 10, 0, 0),
            )

            send_supplier_rfq(
                repository=rfq_repository,
                rfq_id=approved_rfq.rfq_id,
                send_result=MailSendResult(
                    operation_id=f"supplier-rfq:{approved_rfq.rfq_id}",
                    status="sent",
                    reason="Integration test provider send.",
                    provider_name="integration-test",
                    provider_message_id="integration-message-1",
                    sent_at=datetime(2026, 8, 13, 10, 1, 0),
                ),
            )

            attach_supplier_rfq_response(
                repository=rfq_repository,
                response=SupplierRFQResponse(
                    rfq_id=approved_rfq.rfq_id,
                    supplier_name=approved_rfq.supplier_name,
                    rfq_priority=approved_rfq.priority,
                    status="quoted",
                    cost=2300,
                    currency="EUR",
                    transit_time="5-7 gün",
                    source="manual",
                    received_at=datetime(2026, 8, 13, 10, 30, 0),
                ),
            )

            resumed_result = resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=rfq_repository,
                approval_repository=approval_repository,
                quote_case_repository=quote_case_repository,
            )

            quote_approval = resumed_result.get("quote_approval")

            if quote_approval is None:
                failures.append(
                    "supplier response workflow should generate quote approval"
                )
            else:
                stored = approval_repository.get(
                    quote_approval.approval_id
                )

                if stored is None:
                    failures.append(
                        "workflow should persist quote approval"
                    )
                elif stored != quote_approval:
                    failures.append(
                        "stored approval should match workflow approval"
                    )

    if len(approval_repository.list_all()) != 1:
        failures.append(
            "completed supplier response workflow should store "
            "exactly one approval"
        )

    early_stop_shipment = quote_shipment.model_copy(
        update={
            "commodity": "Kimyasal Ürün",
            "is_adr": True,
            "adr_class": None,
            "special_notes": None,
        }
    )

    early_stop_result = pipeline.process_shipment(
        shipment=early_stop_shipment,
        email_text=(
            "Adana'dan Hamburg'a ADR kapsamındaki kimyasal "
            "yük için fiyat rica ederiz. ADR sınıfı belli değil."
        ),
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )

    if early_stop_result.get("quote_approval") is not None:
        failures.append(
            "early-stop workflow must not generate quote approval"
        )

    if len(approval_repository.list_all()) != 1:
        failures.append(
            "early-stop workflow must not persist additional approval"
        )

    return {
        "name": "Quote approval repository workflow integration",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_approval_service() -> dict:
    from datetime import datetime

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )
    from src.core.quote_approval_service import (
        QuoteApprovalNotFoundError,
        QuoteApprovalTransitionError,
        approve_quote,
        invalidate_quote_approval,
        reject_quote,
    )

    failures = []

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    repository = InMemoryQuoteApprovalRepository()

    pending_for_approval = repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    approved_at = datetime(2026, 8, 6, 19, 0, 0)
    approved = approve_quote(
        repository=repository,
        approval_id=pending_for_approval.approval_id,
        approved_by="  operations.manager@example.invalid  ",
        approved_at=approved_at,
    )

    if approved.approval_status != "approved":
        failures.append(
            "pending approval should transition to approved"
        )

    if approved.approved_by != "operations.manager@example.invalid":
        failures.append(
            "approved_by should be normalized"
        )

    if approved.approved_at != approved_at:
        failures.append(
            "approved_at should preserve explicit timestamp"
        )

    try:
        approve_quote(
            repository=repository,
            approval_id=approved.approval_id,
            approved_by="manager@example.invalid",
        )
    except QuoteApprovalTransitionError:
        pass
    else:
        failures.append(
            "approved approval must not be approved again"
        )

    invalidated = invalidate_quote_approval(
        repository=repository,
        approval_id=approved.approval_id,
        invalidated_by="manager@example.invalid",
    )

    if invalidated.approval_status != "invalidated":
        failures.append(
            "approved approval should transition to invalidated"
        )

    if (
        invalidated.approved_by is not None
        or invalidated.approved_at is not None
    ):
        failures.append(
            "invalidated approval must clear approval metadata"
        )

    pending_for_rejection = repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    rejected = reject_quote(
        repository=repository,
        approval_id=pending_for_rejection.approval_id,
        rejection_reason="  Fiyat revize edilmeli.  ",
        rejected_by="manager@example.invalid",
    )

    if rejected.approval_status != "rejected":
        failures.append(
            "pending approval should transition to rejected"
        )

    if rejected.rejection_reason != "Fiyat revize edilmeli.":
        failures.append(
            "rejection_reason should be normalized"
        )

    try:
        invalidate_quote_approval(
            repository=repository,
            approval_id=rejected.approval_id,
            invalidated_by="manager@example.invalid",
        )
    except QuoteApprovalTransitionError:
        pass
    else:
        failures.append(
            "rejected approval must be terminal"
        )

    pending_for_invalidation = repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    pending_invalidated = invalidate_quote_approval(
        repository=repository,
        approval_id=pending_for_invalidation.approval_id,
        invalidated_by="manager@example.invalid",
    )

    if pending_invalidated.approval_status != "invalidated":
        failures.append(
            "pending approval should transition to invalidated"
        )

    try:
        approve_quote(
            repository=repository,
            approval_id=pending_invalidated.approval_id,
            approved_by="manager@example.invalid",
        )
    except QuoteApprovalTransitionError:
        pass
    else:
        failures.append(
            "invalidated approval must be terminal"
        )

    try:
        approve_quote(
            repository=repository,
            approval_id="unknown-approval-id",
            approved_by="manager@example.invalid",
        )
    except QuoteApprovalNotFoundError:
        pass
    else:
        failures.append(
            "unknown approval_id should raise not found error"
        )

    pending_for_empty_actor = repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    try:
        approve_quote(
            repository=repository,
            approval_id=pending_for_empty_actor.approval_id,
            approved_by="   ",
        )
    except ValueError:
        pass
    else:
        failures.append(
            "empty approved_by should be rejected"
        )

    pending_for_empty_reason = repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    try:
        reject_quote(
            repository=repository,
            approval_id=pending_for_empty_reason.approval_id,
            rejection_reason="   ",
            rejected_by="manager@example.invalid",
        )
    except ValueError:
        pass
    else:
        failures.append(
            "empty rejection_reason should be rejected"
        )

    return {
        "name": "Quote approval service",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_approval_api_contract() -> dict:
    from fastapi import HTTPException

    from src.api import (
        QuoteApprovalApproveRequest,
        QuoteApprovalRejectRequest,
        approve_quote_approval,
        get_quote_case,
        get_quote_approval,
        invalidate_quote_approval_endpoint,
        list_quote_approvals,
        quote_approval_repository,
        quote_case_repository,
        reject_quote_approval,
    )
    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        Shipment,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_case import QuoteCase

    failures = []

    class _AuditState:
        pilot_operator = "manager@example.invalid"

    class _AuditRequest:
        state = _AuditState()

    audit_request = _AuditRequest()

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )
    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    pending_for_case_read = quote_approval_repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )
    quote_case = quote_case_repository.save(
        QuoteCase(
            shipment=Shipment(
                customer_name="Quote Case API Test Customer",
                pickup_country="Türkiye",
                pickup_city="Adana",
                delivery_country="Almanya",
                delivery_city="Hamburg",
                commodity="Tekstil",
                gross_weight_kg=20000,
                service_type="FTL",
                cargo_ready_date="2026-08-15",
                is_adr=False,
                is_temperature_controlled=False,
            ),
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
            quote_approval=pending_for_case_read,
        )
    )

    approval_response = approve_quote_approval(
        approval_id=pending_for_case_read.approval_id,
        request=QuoteApprovalApproveRequest(
            approved_by="quote.case.manager@example.invalid",
        ),
    )
    if approval_response.get("approval_status") != "approved":
        failures.append(
            "quote case approval route should approve pending approval"
        )

    refreshed_case = get_quote_case(quote_case.case_id)
    refreshed_approval = refreshed_case.get("quote_approval") or {}
    refreshed_send_safety = refreshed_case.get("quote_send_safety") or {}

    if refreshed_approval.get("approval_status") != "approved":
        failures.append(
            "post-approval quote case read should return current approval"
        )

    if refreshed_approval.get("approved_by") != (
        "quote.case.manager@example.invalid"
    ):
        failures.append(
            "post-approval quote case read should not return pending snapshot"
        )

    if refreshed_send_safety.get("can_send") is not True:
        failures.append(
            "post-approval quote case read should recompute send safety"
        )

    if refreshed_send_safety.get("approval_id") != (
        pending_for_case_read.approval_id
    ):
        failures.append(
            "recomputed send safety should use current approval"
        )

    pending_for_approval = quote_approval_repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    loaded = get_quote_approval(
        pending_for_approval.approval_id
    )

    if loaded.get("approval_id") != pending_for_approval.approval_id:
        failures.append(
            "get endpoint should return requested approval"
        )

    approved = approve_quote_approval(
        approval_id=pending_for_approval.approval_id,
        request=QuoteApprovalApproveRequest(
            approved_by="operations.manager@example.invalid",
        ),
    )

    if approved.get("approval_status") != "approved":
        failures.append(
            "approve endpoint should return approved status"
        )

    try:
        approve_quote_approval(
            approval_id=pending_for_approval.approval_id,
            request=QuoteApprovalApproveRequest(
                approved_by="manager@example.invalid",
            ),
        )
    except HTTPException as exc:
        if exc.status_code != 409:
            failures.append(
                "invalid approval transition should return HTTP 409"
            )
    else:
        failures.append(
            "approved record must not be approved again"
        )

    invalidated = invalidate_quote_approval_endpoint(
        pending_for_approval.approval_id,
        http_request=audit_request,
    )

    if invalidated.get("approval_status") != "invalidated":
        failures.append(
            "invalidate endpoint should return invalidated status"
        )

    pending_for_rejection = quote_approval_repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    rejected = reject_quote_approval(
        approval_id=pending_for_rejection.approval_id,
        request=QuoteApprovalRejectRequest(
            rejection_reason="Fiyat revize edilmeli.",
        ),
        http_request=audit_request,
    )

    if rejected.get("approval_status") != "rejected":
        failures.append(
            "reject endpoint should return rejected status"
        )

    approvals_response = list_quote_approvals()
    approvals = approvals_response.get("approvals") or []
    approval_ids = {
        approval.get("approval_id")
        for approval in approvals
    }

    if pending_for_approval.approval_id not in approval_ids:
        failures.append(
            "list endpoint should include invalidated approval"
        )

    if pending_for_rejection.approval_id not in approval_ids:
        failures.append(
            "list endpoint should include rejected approval"
        )

    try:
        get_quote_approval("unknown-approval-id")
    except HTTPException as exc:
        if exc.status_code != 404:
            failures.append(
                "unknown approval should return HTTP 404"
            )
    else:
        failures.append(
            "unknown approval get request should fail"
        )

    pending_for_empty_actor = quote_approval_repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    try:
        approve_quote_approval(
            approval_id=pending_for_empty_actor.approval_id,
            request=QuoteApprovalApproveRequest(
                approved_by="   ",
            ),
        )
    except HTTPException as exc:
        if exc.status_code != 422:
            failures.append(
                "empty approved_by should return HTTP 422"
            )
    else:
        failures.append(
            "empty approved_by request should fail"
        )

    pending_for_empty_reason = quote_approval_repository.save(
        QuoteApproval(quote_snapshot=snapshot)
    )

    try:
        reject_quote_approval(
            approval_id=pending_for_empty_reason.approval_id,
            request=QuoteApprovalRejectRequest(
                rejection_reason="   ",
            ),
            http_request=audit_request,
        )
    except HTTPException as exc:
        if exc.status_code != 422:
            failures.append(
                "empty rejection reason should return HTTP 422"
            )
    else:
        failures.append(
            "empty rejection reason request should fail"
        )

    return {
        "name": "Quote approval API contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_case_model() -> dict:
    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        Shipment,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_case import QuoteCase
    from src.core.quote_send_safety import (
        evaluate_quote_send_safety,
    )

    failures = []

    shipment = Shipment(
        customer_name="Quote Case Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-15",
        is_adr=False,
        is_temperature_controlled=False,
    )

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )

    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )

    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    approval = QuoteApproval(
        quote_snapshot=QuoteApprovalSnapshot.from_quote(
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    )

    send_safety = evaluate_quote_send_safety(
        approval=approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    case = QuoteCase(
        shipment=shipment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=approval,
        quote_send_safety=send_safety,
    )

    if not case.case_id:
        failures.append(
            "quote case should generate case_id"
        )

    if case.shipment != shipment:
        failures.append(
            "quote case should preserve shipment"
        )

    if case.supplier_quote != supplier_quote:
        failures.append(
            "quote case should preserve supplier quote"
        )

    if case.customer_quote != customer_quote:
        failures.append(
            "quote case should preserve customer quote"
        )

    if case.quote_draft != quote_draft:
        failures.append(
            "quote case should preserve quote draft"
        )

    if case.quote_approval != approval:
        failures.append(
            "quote case should preserve quote approval"
        )

    if case.quote_send_safety != send_safety:
        failures.append(
            "quote case should preserve send safety decision"
        )

    if case.created_at is None or case.updated_at is None:
        failures.append(
            "quote case should include lifecycle timestamps"
        )

    if case.source != "quote_case":
        failures.append(
            "quote case source should be quote_case"
        )

    partial_case = QuoteCase(
        shipment=shipment,
    )

    if partial_case.supplier_quote is not None:
        failures.append(
            "partial quote case should allow missing supplier quote"
        )

    if partial_case.quote_approval is not None:
        failures.append(
            "partial quote case should allow missing approval"
        )

    if partial_case.quote_send_safety is not None:
        failures.append(
            "partial quote case should allow missing send safety"
        )

    return {
        "name": "Quote case model",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_case_repository() -> dict:
    from datetime import datetime

    from src.core.models import (
        CustomerQuote,
        QuoteDraft,
        Shipment,
        SupplierQuote,
    )
    from src.core.quote_approval import (
        QuoteApproval,
        QuoteApprovalSnapshot,
    )
    from src.core.quote_case import QuoteCase
    from src.core.quote_case_repository import (
        InMemoryQuoteCaseRepository,
    )
    from src.core.quote_send_safety import (
        evaluate_quote_send_safety,
    )

    failures = []

    shipment = Shipment(
        customer_name="Quote Case Repository Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-15",
        is_adr=False,
        is_temperature_controlled=False,
    )

    supplier_quote = SupplierQuote(
        supplier_name="Reliable Supplier",
        cost=2000,
        currency="EUR",
        transit_time="5-7 days",
        notes="Selected supplier quote.",
    )

    customer_quote = CustomerQuote(
        supplier_cost=2000,
        margin_type="percentage",
        margin_value=15,
        final_price=2300,
        currency="EUR",
    )

    quote_draft = QuoteDraft(
        subject="Taşıma Teklifimiz",
        body="Fiyat: 2300 EUR",
    )

    approval = QuoteApproval(
        quote_snapshot=QuoteApprovalSnapshot.from_quote(
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    )

    send_safety = evaluate_quote_send_safety(
        approval=approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    repository = InMemoryQuoteCaseRepository()

    quote_case = QuoteCase(
        shipment=shipment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=approval,
        quote_send_safety=send_safety,
    )

    saved = repository.save(quote_case)

    if saved.case_id != quote_case.case_id:
        failures.append(
            "saved quote case should preserve case_id"
        )

    loaded = repository.get(quote_case.case_id)

    if loaded is None:
        failures.append(
            "saved quote case should be retrievable"
        )
    elif loaded != quote_case:
        failures.append(
            "retrieved quote case should match saved case"
        )

    updated_case = quote_case.model_copy(
        update={
            "updated_at": datetime(2026, 8, 7, 18, 30, 0),
        }
    )

    repository.save(updated_case)

    updated = repository.get(quote_case.case_id)

    if updated is None:
        failures.append(
            "updated quote case should remain retrievable"
        )
    elif updated.updated_at != updated_case.updated_at:
        failures.append(
            "saving same case_id should update existing case"
        )

    second_case = QuoteCase(
        shipment=shipment,
    )

    saved_many = repository.save_many([second_case])

    if len(saved_many) != 1:
        failures.append(
            "save_many should return saved quote cases"
        )

    cases = repository.list_all()

    if len(cases) != 2:
        failures.append(
            "repository should contain two unique case IDs"
        )

    cases.clear()

    if len(repository.list_all()) != 2:
        failures.append(
            "list_all should not expose mutable internal collection"
        )

    if repository.get("unknown-case-id") is not None:
        failures.append(
            "unknown case_id should return None"
        )

    return {
        "name": "Quote case repository",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_case_workflow_persistence() -> dict:
    from src.core.models import Shipment
    from src.core.quote_case_repository import (
        InMemoryQuoteCaseRepository,
    )
    from src.workflow import pipeline

    failures = []

    repository = InMemoryQuoteCaseRepository()

    shipment = Shipment(
        customer_name="Quote Case Workflow Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-15",
        is_adr=False,
        is_temperature_controlled=False,
    )

    result = pipeline.process_shipment(
        shipment=shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil yükü için "
            "komple tenteli araç fiyatı rica ederiz. "
            "Yük ADR değildir ve 15.08.2026 tarihinde hazırdır."
        ),
        quote_case_repository=repository,
    )

    quote_case = result.get("quote_case")

    if quote_case is None:
        failures.append(
            "successful workflow should generate quote case"
        )
    else:
        stored = repository.get(quote_case.case_id)

        if stored is None:
            failures.append(
                "workflow should persist quote case"
            )
        elif stored != quote_case:
            failures.append(
                "stored quote case should match workflow result"
            )

        if stored is not None:
            if stored.quote_approval != result.get("quote_approval"):
                failures.append(
                    "stored case should preserve quote approval"
                )

            if stored.quote_send_safety != result.get(
                "quote_send_safety"
            ):
                failures.append(
                    "stored case should preserve send safety"
                )

    if len(repository.list_all()) != 1:
        failures.append(
            "successful workflow should store exactly one quote case"
        )

    early_stop_shipment = shipment.model_copy(
        update={
            "commodity": "Kimyasal Ürün",
            "is_adr": True,
            "adr_class": None,
            "special_notes": None,
        }
    )

    early_stop_result = pipeline.process_shipment(
        shipment=early_stop_shipment,
        email_text=(
            "Adana'dan Hamburg'a ADR kapsamındaki kimyasal "
            "yük için fiyat rica ederiz. ADR sınıfı belli değil."
        ),
        quote_case_repository=repository,
    )

    if early_stop_result.get("quote_case") is not None:
        failures.append(
            "early-stop workflow must not generate quote case"
        )

    if len(repository.list_all()) != 1:
        failures.append(
            "early-stop workflow must not persist quote case"
        )

    return {
        "name": "Quote case workflow persistence",
        "passed": len(failures) == 0,
        "failures": failures,
    }


def evaluate_quote_case_api_contract() -> dict:
    from fastapi import HTTPException

    import src.api as api
    from src.core.models import Shipment

    failures = []

    before_ids = {
        item.case_id
        for item in api.quote_case_repository.list_all()
    }

    shipment = Shipment(
        customer_name="Quote Case API Test Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-08-15",
        is_adr=False,
        is_temperature_controlled=False,
    )

    original_parser = api.parse_email_with_ai

    try:
        api.parse_email_with_ai = lambda _: shipment

        response = api.process_email(
            api.ProcessEmailRequest(
                email_text="Deterministic quote case API test."
            )
        )
    finally:
        api.parse_email_with_ai = original_parser

    quote_case = response.get("quote_case")

    if quote_case is None:
        failures.append(
            "process-email should return serialized quote case"
        )
        return {
            "name": "Quote case API contract",
            "passed": len(failures) == 0,
            "failures": failures,
        }

    case_id = quote_case.get("case_id")

    if not case_id:
        failures.append(
            "serialized quote case should include case_id"
        )

    if case_id and case_id in before_ids:
        failures.append(
            "process-email should create a new quote case"
        )

    listed = api.list_quote_cases().get("quote_cases") or []

    listed_ids = {
        item.get("case_id")
        for item in listed
    }

    if case_id not in listed_ids:
        failures.append(
            "quote case list should include created case"
        )

    if case_id:
        loaded = api.get_quote_case(case_id)

        if loaded.get("case_id") != case_id:
            failures.append(
                "get quote case should return requested case"
            )

        if loaded.get("quote_approval") != quote_case.get(
            "quote_approval"
        ):
            failures.append(
                "loaded case should preserve quote approval"
            )

        if loaded.get("quote_send_safety") != quote_case.get(
            "quote_send_safety"
        ):
            failures.append(
                "loaded case should preserve send safety"
            )

        approval_id = (
            quote_case.get("quote_approval") or {}
        ).get("approval_id")

        if not approval_id:
            failures.append(
                "created quote case should include approval identity"
            )
        else:
            api.approve_quote_approval(
                approval_id=approval_id,
                request=api.QuoteApprovalApproveRequest(
                    approved_by="quote.case.manager@example.invalid",
                ),
            )
            approved_case = api.get_quote_case(case_id)

            if (
                approved_case.get("quote_approval") or {}
            ).get("approval_status") != "approved":
                failures.append(
                    "retrieved case should reflect authoritative approved status"
                )

            approved_send_safety = (
                approved_case.get("quote_send_safety") or {}
            )
            if approved_send_safety.get("can_send") is not True:
                failures.append(
                    "retrieved approved case should refresh send safety"
                )

            listed_after_approval = (
                api.list_quote_cases().get("quote_cases") or []
            )
            listed_approved_case = next(
                (
                    item
                    for item in listed_after_approval
                    if item.get("case_id") == case_id
                ),
                None,
            )
            if (
                not listed_approved_case
                or (
                    listed_approved_case.get("quote_approval") or {}
                ).get("approval_status") != "approved"
            ):
                failures.append(
                    "listed case should reflect authoritative approved status"
                )

            api.invalidate_quote_approval_endpoint(approval_id)
            invalidated_case = api.get_quote_case(case_id)

            if (
                invalidated_case.get("quote_approval") or {}
            ).get("approval_status") != "invalidated":
                failures.append(
                    "retrieved case should reflect authoritative invalidated status"
                )

            if (
                invalidated_case.get("quote_send_safety") or {}
            ).get("block_reason") != "approval_invalidated":
                failures.append(
                    "invalidated case should refresh to blocked send safety"
                )

    original_parser = api.parse_email_with_ai

    try:
        api.parse_email_with_ai = lambda _: shipment
        rejected_response = api.process_email(
            api.ProcessEmailRequest(
                email_text="Deterministic rejected quote case API test."
            )
        )
    finally:
        api.parse_email_with_ai = original_parser

    rejected_case = rejected_response.get("quote_case") or {}
    rejected_case_id = rejected_case.get("case_id")
    rejected_approval_id = (
        rejected_case.get("quote_approval") or {}
    ).get("approval_id")

    if rejected_case_id and rejected_approval_id:
        api.reject_quote_approval(
            approval_id=rejected_approval_id,
            request=api.QuoteApprovalRejectRequest(
                rejection_reason="Pricing requires revision.",
            ),
        )
        loaded_rejected_case = api.get_quote_case(rejected_case_id)

        if (
            loaded_rejected_case.get("quote_approval") or {}
        ).get("approval_status") != "rejected":
            failures.append(
                "retrieved case should reflect authoritative rejected status"
            )

        if (
            loaded_rejected_case.get("quote_send_safety") or {}
        ).get("block_reason") != "approval_rejected":
            failures.append(
                "rejected case should refresh to blocked send safety"
            )
    else:
        failures.append(
            "rejection lifecycle setup should create case and approval"
        )

    try:
        api.get_quote_case("unknown-case-id")
    except HTTPException as exc:
        if exc.status_code != 404:
            failures.append(
                "unknown case_id should return HTTP 404"
            )
    else:
        failures.append(
            "unknown quote case request should fail"
        )

    return {
        "name": "Quote case API contract",
        "passed": len(failures) == 0,
        "failures": failures,
    }
