"""Legacy developer simulation and AI test runner.

This module is intentionally outside the controlled operational runtime
import graph. The pilot API must never depend on it.
"""

import json
from src.simulation.email_generator import generate_fake_customer_email
from src.simulation.scenario_generator import get_simulation_scenarios
from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES
from src.simulation.clarification_resolution_regressions import (
    evaluate_clarification_resolution_regressions,
)
from src.simulation.regulatory_compliance_regressions import (
    evaluate_regulatory_compliance_regressions,
)
from src.simulation.extraction_confirmation_regressions import (
    evaluate_extraction_confirmation_regressions,
)
from src.simulation.test_reporter import evaluate_test_result, print_test_report, evaluate_commodity_dictionary_validation, evaluate_supplier_capability_validation, evaluate_supplier_adr_capability_validation, evaluate_supplier_capability_registry_validation, evaluate_supplier_capability_registry_runtime_integrity, evaluate_customer_memory_validation, evaluate_strict_supplier_eligibility, evaluate_inactive_customer_memory_matching, evaluate_heavy_cargo_weight_logic, evaluate_customer_pricing_regression, evaluate_hs_commodity_map_validation, evaluate_data_health_summary, evaluate_data_health_label_mapping, evaluate_data_health_registry_integrity, evaluate_data_health_summary_check_metadata, evaluate_workflow_result_contract, evaluate_quote_readiness_blocked_state, evaluate_action_recommendation_result_contract, evaluate_supplier_rfq_draft_generation, evaluate_supplier_rfq_workflow_contract, evaluate_supplier_rfq_contact_propagation, evaluate_supplier_rfq_response_simulation, evaluate_supplier_quote_selection, evaluate_supplier_rfq_response_validation, evaluate_supplier_fallback_consistency, evaluate_final_quote_consistency_block, evaluate_supplier_response_required_state, evaluate_supplier_rfq_lifecycle_synchronization, evaluate_supplier_rfq_response_link_integrity, evaluate_supplier_rfq_response_validation_report, evaluate_supplier_rfq_response_status_rules, evaluate_supplier_rfq_api_contract, evaluate_supplier_quote_comparison_model, evaluate_multi_criteria_supplier_quote_selection, evaluate_supplier_quote_selection_traceability, evaluate_supplier_rfq_repository, evaluate_supplier_rfq_repository_workflow_integration, evaluate_quote_approval_model, evaluate_quote_approval_workflow_contract, evaluate_quote_approval_repository, evaluate_quote_approval_repository_workflow_integration, evaluate_quote_approval_service, evaluate_quote_approval_api_contract, evaluate_quote_case_model, evaluate_quote_case_repository, evaluate_quote_case_workflow_persistence, evaluate_quote_case_api_contract, evaluate_quote_send_safety_regression, evaluate_quote_send_service, evaluate_quote_send_api_contract
from src.ai.email_parser import parse_email_to_shipment, parse_email_with_ai
from src.workflow.pipeline import process_shipment

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

    proposal = parse_email_with_ai(email_text)
    print("\n--- EXTRACTION PROPOSAL (NO OPERATIONAL AUTHORITY) ---")
    print(proposal.model_dump_json(indent=2))
    return {
        "result_type": "extraction_confirmation_required",
        "proposed_shipment": proposal,
    }


def run_ai_email_test_suite():
    from src.core.extraction_confirmation_repository import (
        InMemoryExtractionProposalRepository,
    )
    from src.core.mail import InboundMailEnvelope
    from src.core.quote_approval_repository import (
        InMemoryQuoteApprovalRepository,
    )
    from src.core.quote_case_repository import InMemoryQuoteCaseRepository
    from src.workflow.extraction_confirmation import (
        confirm_extraction_proposal,
        create_extraction_proposal,
        resume_confirmed_extraction,
    )
    from src.simulation.mail_adapter_regressions import (
        evaluate_mail_adapter_regressions,
    )

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
    test_results.append(evaluate_strict_supplier_eligibility())
    test_results.append(evaluate_inactive_customer_memory_matching())
    test_results.append(evaluate_heavy_cargo_weight_logic())
    test_results.append(evaluate_customer_pricing_regression())
    test_results.append(
        evaluate_clarification_resolution_regressions()
    )
    test_results.append(
        evaluate_regulatory_compliance_regressions()
    )
    test_results.append(
        evaluate_extraction_confirmation_regressions()
    )
    test_results.append(evaluate_mail_adapter_regressions())
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
    test_results.append(evaluate_supplier_fallback_consistency())
    test_results.append(evaluate_supplier_rfq_lifecycle_synchronization())
    test_results.append(evaluate_supplier_rfq_response_link_integrity())
    test_results.append(evaluate_supplier_rfq_response_validation_report())
    test_results.append(evaluate_supplier_rfq_response_status_rules())
    test_results.append(evaluate_supplier_rfq_api_contract())
    test_results.append(evaluate_supplier_quote_comparison_model())
    test_results.append(evaluate_multi_criteria_supplier_quote_selection())
    test_results.append(evaluate_supplier_quote_selection_traceability())
    test_results.append(evaluate_supplier_rfq_repository())
    test_results.append(evaluate_supplier_rfq_repository_workflow_integration())
    test_results.append(evaluate_quote_approval_model())
    test_results.append(evaluate_quote_approval_workflow_contract())
    test_results.append(evaluate_quote_approval_repository())
    test_results.append(evaluate_quote_approval_service())
    test_results.append(evaluate_quote_approval_api_contract())
    test_results.append(evaluate_quote_case_model())
    test_results.append(evaluate_quote_case_repository())
    test_results.append(evaluate_quote_send_safety_regression())
    test_results.append(evaluate_quote_send_service())
    test_results.append(evaluate_quote_send_api_contract())

    for index, test_case in enumerate(AI_EMAIL_TEST_CASES, start=1):
        print("\n\n########################################")
        print(f"AI TEST {index}: {test_case['name']}")
        print("########################################")

        email_text = test_case["email"]

        print("\n--- RAW EMAIL ---")
        print(email_text.strip())

        proposed_shipment = parse_email_with_ai(email_text)
        proposal_repository = InMemoryExtractionProposalRepository()
        proposal = create_extraction_proposal(
            mail=InboundMailEnvelope(body_text=email_text, source="manual"),
            proposed_shipment=proposed_shipment,
            repository=proposal_repository,
        )
        confirmed = confirm_extraction_proposal(
            repository=proposal_repository,
            proposal_id=proposal.proposal_id,
            operator_identity="AI regression confirmation fixture",
            corrections={
                field_name: False
                for field_name in proposal.unknown_safety_fields
            },
        )
        result = resume_confirmed_extraction(
            repository=proposal_repository,
            proposal_id=confirmed.proposal_id,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
        )

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
    regulatory_compliance = result.get("regulatory_compliance")
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

    if regulatory_compliance:
        print("\n--- REGULATORY COMPLIANCE ---")
        print(regulatory_compliance.model_dump_json(indent=2))

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

    if regulatory_compliance and not (
        regulatory_compliance.can_continue_to_quote
    ):
        print("\n--- WORKFLOW STOPPED ---")
        print(
            "Düzenleyici belge politikası nedeniyle teklif "
            "oluşturulmadı."
        )
        return

    print("\n--- SUPPLIER QUOTE ---")
    print(supplier_quote.model_dump_json(indent=2))

    print("\n--- CUSTOMER QUOTE ---")
    print(customer_quote.model_dump_json(indent=2))

    print("\n--- QUOTE EMAIL DRAFT ---")
    print(f"Subject: {quote_draft.subject}\n")
    print(quote_draft.body)
