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

    expected_risk_level = expected.get("risk_level")
    if expected_risk_level and risk_assessment.risk_level != expected_risk_level:
        failures.append(
            f"risk_level expected {expected_risk_level}, got {risk_assessment.risk_level}"
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