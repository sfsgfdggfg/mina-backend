import json
from src.simulation.email_generator import generate_fake_customer_email
from src.simulation.scenario_generator import get_simulation_scenarios
from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES
from src.simulation.test_reporter import evaluate_test_result, print_test_report, evaluate_commodity_dictionary_validation, evaluate_supplier_capability_validation, evaluate_supplier_adr_capability_validation, evaluate_supplier_capability_registry_validation, evaluate_supplier_capability_registry_runtime_integrity, evaluate_customer_memory_validation, evaluate_hs_commodity_map_validation, evaluate_data_health_summary, evaluate_data_health_label_mapping, evaluate_data_health_registry_integrity, evaluate_data_health_summary_check_metadata, evaluate_workflow_result_contract, evaluate_quote_readiness_blocked_state, evaluate_action_recommendation_result_contract, evaluate_supplier_rfq_draft_generation, evaluate_supplier_rfq_workflow_contract, evaluate_supplier_rfq_contact_propagation, evaluate_supplier_rfq_response_simulation, evaluate_supplier_quote_selection, evaluate_supplier_rfq_response_validation
from src.core.action_recommendation import generate_action_recommendation
from src.ai.email_parser import parse_email_to_shipment, parse_email_with_ai
from src.ai.quote_generator import generate_quote_draft
from src.ai.clarification_generator import generate_clarification_draft
from src.ai.approval_generator import generate_management_review_draft
from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts

from src.core.customer_memory import enrich_shipment_with_customer_memory
from src.core.equipment import decide_equipment
from src.core.risk import assess_risk
from src.core.missing_info import check_missing_information
from src.simulation.supplier_simulator import simulate_supplier_rfq_responses
from src.core.supplier_selection import select_suppliers_for_shipment
from src.core.operational_consistency import check_operational_consistency
from src.core.pricing import calculate_customer_quote
from src.core.commodity_profile import get_commodity_record
from src.core.quote_readiness import decide_quote_readiness
from src.core.supplier_quote_selection import select_supplier_quote_from_responses


def process_shipment(shipment, email_text: str | None = None):
    customer_memory = enrich_shipment_with_customer_memory(
        shipment=shipment,
        email_text=email_text,
    )

    commodity_profile = get_commodity_record(shipment.commodity)
    missing_info = check_missing_information(shipment)
    equipment_decision = decide_equipment(shipment)
    risk_assessment = assess_risk(
    shipment=shipment,
    customer_memory=customer_memory,
)

    # 1. RED risk varsa önce yönetici onayına gider
    supplier_selection = select_suppliers_for_shipment(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
    )

    operational_consistency = check_operational_consistency(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_selection=supplier_selection,
        supplier_quote=None,
    )

    quote_readiness = decide_quote_readiness(
        missing_info=missing_info,
        risk_assessment=risk_assessment,
        operational_consistency=operational_consistency,
    )

    if quote_readiness.result_type == "blocked":
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="blocked",
        )

        return {
            "shipment": shipment,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "clarification_draft": None,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
        }

    if quote_readiness.result_type == "management_review":
        management_review_draft = generate_management_review_draft(
            shipment=shipment,
            risk_assessment=risk_assessment,
        )
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="management_review",
        )
        

        return {
            "shipment": shipment,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "clarification_draft": None,
            "management_review_draft": management_review_draft,
            "action_recommendation": action_recommendation,
        }

    # 2. RED değilse kritik eksik bilgi kontrol edilir
    if quote_readiness.result_type == "clarification":
        clarification_draft = generate_clarification_draft(
            shipment=shipment,
            missing_info=missing_info,
        )
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="clarification",
        )

        return {
            "shipment": shipment,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "clarification_draft": clarification_draft,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
        }

    # 3. Her şey uygunsa supplier RFQ ve quote akışı çalışır
    supplier_rfq_drafts = generate_supplier_rfq_drafts(
        shipment=shipment,
        equipment_decision=equipment_decision,
        supplier_selection=supplier_selection,
    )

    supplier_rfq_responses = simulate_supplier_rfq_responses(
        shipment=shipment,
        equipment_decision=equipment_decision,
        supplier_selection=supplier_selection,
        rfq_drafts=supplier_rfq_drafts,
    )

    supplier_quote = select_supplier_quote_from_responses(
        supplier_rfq_responses
    )

    if supplier_quote is None:
        raise RuntimeError(
            "Kullanılabilir supplier RFQ cevabı bulunamadı."
        )

    customer_quote = calculate_customer_quote(supplier_quote)

    quote_draft = generate_quote_draft(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
    )
    action_recommendation = generate_action_recommendation(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        missing_info=missing_info,
        result_type=quote_readiness.result_type,
    )

    return {
        "shipment": shipment,
        "customer_memory": customer_memory,
        "commodity_profile": commodity_profile,
        "missing_info": missing_info,
        "equipment_decision": equipment_decision,
        "risk_assessment": risk_assessment,
        "supplier_selection": supplier_selection,
        "operational_consistency": operational_consistency,
        "quote_readiness": quote_readiness,
        "supplier_rfq_drafts": supplier_rfq_drafts,
        "supplier_rfq_responses": supplier_rfq_responses,
        "supplier_quote": supplier_quote,
        "customer_quote": customer_quote,
        "quote_draft": quote_draft,
        "clarification_draft": None,
        "management_review_draft": None,
        "action_recommendation": action_recommendation,
    }


def run_simulation_pipeline():
    print("\n==============================")
    print("MINAI FREIGHT OS - SINGLE EMAIL SIMULATION")
    print("==============================")

    email_text = generate_fake_customer_email()

    print("\n--- INBOUND EMAIL ---")
    print(email_text.strip())

    shipment = parse_email_to_shipment(email_text)
    result = process_shipment(shipment, email_text=email_text)

    print_result(result)

    return result.get("quote_draft")


def run_scenario_pipeline():
    print("\n==============================")
    print("MINAI FREIGHT OS - SCENARIO SIMULATION")
    print("==============================")

    scenarios = get_simulation_scenarios()

    for index, shipment in enumerate(scenarios, start=1):
        print("\n\n########################################")
        print(f"SCENARIO {index}: {shipment.customer_name}")
        print("########################################")

        result = process_shipment(shipment)
        print_result(result)


def run_ai_email_pipeline():
    print("\n==============================")
    print("MINAI FREIGHT OS - AI EMAIL PARSER MODE")
    print("==============================")

    email_text = """
Merhaba,

Adana OSB'den Stuttgart Almanya'ya 1 adet makine için komple araç fiyat rica ederiz.
Yaklaşık 3000 kg. Ölçüleri henüz net değil.
Yük 23.06.2026 tarihinde hazır olacaktır.

Teşekkürler.
"""

    print("\n--- RAW EMAIL ---")
    print(email_text.strip())

    shipment = parse_email_with_ai(email_text)
    result = process_shipment(shipment, email_text=email_text)

    print_result(result)

    return result


def run_ai_email_test_suite():
    print("\n==============================")
    print("MINAI FREIGHT OS - AI EMAIL TEST SUITE")
    print("==============================")

    test_results = []
    test_results.append(evaluate_commodity_dictionary_validation())
    test_results.append(evaluate_supplier_capability_validation())
    test_results.append(evaluate_supplier_adr_capability_validation())
    test_results.append(evaluate_supplier_capability_registry_validation())
    test_results.append(evaluate_supplier_capability_registry_runtime_integrity())
    test_results.append(evaluate_customer_memory_validation())
    test_results.append(evaluate_hs_commodity_map_validation())
    test_results.append(evaluate_data_health_summary())
    test_results.append(evaluate_data_health_label_mapping())
    test_results.append(evaluate_data_health_registry_integrity())
    test_results.append(evaluate_data_health_summary_check_metadata())
    test_results.append(evaluate_workflow_result_contract())
    test_results.append(evaluate_quote_readiness_blocked_state())
    test_results.append(evaluate_action_recommendation_result_contract())
    test_results.append(evaluate_supplier_rfq_draft_generation())
    test_results.append(evaluate_supplier_rfq_workflow_contract())
    test_results.append(evaluate_supplier_rfq_contact_propagation())
    test_results.append(evaluate_supplier_rfq_response_simulation())
    test_results.append(evaluate_supplier_quote_selection())
    test_results.append(evaluate_supplier_rfq_response_validation())

    for index, test_case in enumerate(AI_EMAIL_TEST_CASES, start=1):
        print("\n\n########################################")
        print(f"AI TEST {index}: {test_case['name']}")
        print("########################################")

        email_text = test_case["email"]

        print("\n--- RAW EMAIL ---")
        print(email_text.strip())

        shipment = parse_email_with_ai(email_text)
        result = process_shipment(shipment, email_text=email_text)

        print_result(result)

        test_results.append(
            evaluate_test_result(
                test_case=test_case,
                result=result,
            )
        )

    print_test_report(test_results)


def print_result(result):
    if result is None:
        print("\nERROR: process_shipment None döndürdü.")
        return

    shipment = result["shipment"]
    customer_memory = result.get("customer_memory")
    missing_info = result.get("missing_info")
    equipment_decision = result["equipment_decision"]
    risk_assessment = result["risk_assessment"]
    supplier_quote = result.get("supplier_quote")
    supplier_selection = result.get("supplier_selection")
    operational_consistency = result.get("operational_consistency")
    quote_readiness = result.get("quote_readiness")
    customer_quote = result.get("customer_quote")
    quote_draft = result.get("quote_draft")
    clarification_draft = result.get("clarification_draft")
    management_review_draft = result.get("management_review_draft")
    action_recommendation = result.get("action_recommendation")

    print("\n--- SHIPMENT ---")
    print(shipment.model_dump_json(indent=2))

    print("\n--- EQUIPMENT DECISION ---")
    print(equipment_decision.model_dump_json(indent=2))

    print("\n--- RISK ASSESSMENT ---")
    print(risk_assessment.model_dump_json(indent=2))

    print("\n--- SUPPLIER SELECTION ---")
    print(json.dumps(supplier_selection, indent=2, ensure_ascii=False))

    if operational_consistency:
        print("\n--- OPERATIONAL CONSISTENCY ---")
        print(json.dumps(operational_consistency, indent=2, ensure_ascii=False))

    if quote_readiness:
        print("\n--- QUOTE READINESS ---")
        print(quote_readiness.model_dump_json(indent=2))

    if customer_memory:
        print("\n--- CUSTOMER MEMORY ---")
        print(customer_memory.model_dump_json(indent=2))
    
    if action_recommendation:
        print("\n--- ACTION RECOMMENDATION ---")
        print(action_recommendation.model_dump_json(indent=2))

    if risk_assessment.risk_level == "red":
        print("\n--- WORKFLOW STOPPED ---")
        print("RED risk nedeniyle müşteriye teklif oluşturulmadı.")
        print("Bir sonraki adım: yönetici / senior operasyon onayı.")

        if management_review_draft:
            print("\n--- MANAGEMENT REVIEW DRAFT ---")
            print(f"Subject: {management_review_draft.subject}\n")
            print(management_review_draft.body)
        else:
            print("\nUYARI: Management review draft üretilemedi.")

        return

    if missing_info:
        print("\n--- MISSING INFORMATION CHECK ---")
        print(missing_info.model_dump_json(indent=2))

        if not missing_info.can_continue_to_quote:
            print("\n--- WORKFLOW STOPPED ---")
            print("Kritik eksik bilgi nedeniyle fiyat/teklif oluşturulmadı.")
            print("Bir sonraki adım: müşteriden eksik bilgi istenecek.")

            if clarification_draft:
                print("\n--- CLARIFICATION EMAIL DRAFT ---")
                print(f"Subject: {clarification_draft.subject}\n")
                print(clarification_draft.body)

            return

    print("\n--- SUPPLIER QUOTE ---")
    print(supplier_quote.model_dump_json(indent=2))

    print("\n--- CUSTOMER QUOTE ---")
    print(customer_quote.model_dump_json(indent=2))

    print("\n--- QUOTE EMAIL DRAFT ---")
    print(f"Subject: {quote_draft.subject}\n")
    print(quote_draft.body)