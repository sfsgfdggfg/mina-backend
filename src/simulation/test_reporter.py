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