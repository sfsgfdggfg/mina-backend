from src.simulation.email_generator import generate_fake_customer_email
from src.ai.email_parser import parse_email_to_shipment
from src.core.equipment import decide_equipment
from src.core.risk import assess_risk
from src.simulation.supplier_simulator import simulate_supplier_quote
from src.core.pricing import calculate_customer_quote
from src.ai.quote_generator import generate_quote_draft


def run_simulation_pipeline():
    print("\n==============================")
    print("MINAI FREIGHT OS - SIMULATION")
    print("==============================")

    email_text = generate_fake_customer_email()

    print("\n--- INBOUND EMAIL ---")
    print(email_text.strip())

    shipment = parse_email_to_shipment(email_text)

    print("\n--- PARSED SHIPMENT ---")
    print(shipment.model_dump_json(indent=2))

    equipment_decision = decide_equipment(shipment)

    print("\n--- EQUIPMENT DECISION ---")
    print(equipment_decision.model_dump_json(indent=2))

    risk_assessment = assess_risk(shipment)

    print("\n--- RISK ASSESSMENT ---")
    print(risk_assessment.model_dump_json(indent=2))

    supplier_quote = simulate_supplier_quote(shipment, equipment_decision)

    print("\n--- SUPPLIER QUOTE ---")
    print(supplier_quote.model_dump_json(indent=2))

    customer_quote = calculate_customer_quote(supplier_quote)

    print("\n--- CUSTOMER QUOTE ---")
    print(customer_quote.model_dump_json(indent=2))

    quote_draft = generate_quote_draft(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
    )

    print("\n--- QUOTE EMAIL DRAFT ---")
    print(f"Subject: {quote_draft.subject}\n")
    print(quote_draft.body)

    return quote_draft