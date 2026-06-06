from src.simulation.email_generator import generate_fake_customer_email
from src.simulation.scenario_generator import get_simulation_scenarios
from src.ai.email_parser import parse_email_to_shipment, parse_email_with_ai
from src.core.equipment import decide_equipment
from src.core.risk import assess_risk
from src.core.missing_info import check_missing_information
from src.simulation.supplier_simulator import simulate_supplier_quote
from src.core.pricing import calculate_customer_quote
from src.ai.quote_generator import generate_quote_draft
from src.ai.clarification_generator import generate_clarification_draft
from src.ai.approval_generator import generate_management_review_draft


def process_shipment(shipment):
    missing_info = check_missing_information(shipment)
    equipment_decision = decide_equipment(shipment)
    risk_assessment = assess_risk(shipment)

    if not missing_info.can_continue_to_quote:
        clarification_draft = generate_clarification_draft(
            shipment=shipment,
            missing_info=missing_info,
        )

        return {
            "shipment": shipment,
            "missing_info": missing_info,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "clarification_draft": clarification_draft,
            "management_review_draft": None,
        }

    if risk_assessment.risk_level == "red":
        management_review_draft = generate_management_review_draft(
            shipment=shipment,
            risk_assessment=risk_assessment,
        )

        return {
            "shipment": shipment,
            "missing_info": missing_info,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "clarification_draft": None,
            "management_review_draft": management_review_draft,
        }

    supplier_quote = simulate_supplier_quote(shipment, equipment_decision)
    customer_quote = calculate_customer_quote(supplier_quote)

    quote_draft = generate_quote_draft(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
    )

    return {
        "shipment": shipment,
        "missing_info": missing_info,
        "equipment_decision": equipment_decision,
        "risk_assessment": risk_assessment,
        "supplier_quote": supplier_quote,
        "customer_quote": customer_quote,
        "quote_draft": quote_draft,
        "clarification_draft": None,
        "management_review_draft": None,
    }

def run_simulation_pipeline():
    print("\n==============================")
    print("MINAI FREIGHT OS - SINGLE EMAIL SIMULATION")
    print("==============================")

    email_text = generate_fake_customer_email()

    print("\n--- INBOUND EMAIL ---")
    print(email_text.strip())

    shipment = parse_email_to_shipment(email_text)
    result = process_shipment(shipment)

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
    result = process_shipment(shipment)

    print_result(result)

    return result


def print_result(result):
    shipment = result["shipment"]
    missing_info = result.get("missing_info")
    equipment_decision = result["equipment_decision"]
    risk_assessment = result["risk_assessment"]
    supplier_quote = result.get("supplier_quote")
    customer_quote = result.get("customer_quote")
    quote_draft = result.get("quote_draft")
    clarification_draft = result.get("clarification_draft")
    management_review_draft = result.get("management_review_draft")

    print("\n--- SHIPMENT ---")
    print(shipment.model_dump_json(indent=2))

    print("\n--- EQUIPMENT DECISION ---")
    print(equipment_decision.model_dump_json(indent=2))

    print("\n--- RISK ASSESSMENT ---")
    print(risk_assessment.model_dump_json(indent=2))

    if risk_assessment.risk_level == "red":
        print("\n--- WORKFLOW STOPPED ---")
        print("RED risk nedeniyle müşteriye teklif oluşturulmadı.")
        print("Bir sonraki adım: yönetici / senior operasyon onayı.")

        if management_review_draft:
            print("\n--- MANAGEMENT REVIEW DRAFT ---")
            print(f"Subject: {management_review_draft.subject}\n")
            print(management_review_draft.body)

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