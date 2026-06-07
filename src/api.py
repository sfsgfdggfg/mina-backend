from fastapi import FastAPI
from pydantic import BaseModel

from src.ai.email_parser import parse_email_with_ai
from src.workflow.pipeline import process_shipment
from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES
from src.simulation.test_reporter import evaluate_test_result


app = FastAPI(
    title="MINAI Freight OS API",
    description="AI-powered freight operations assistant API",
    version="0.1.0",
)


class ProcessEmailRequest(BaseModel):
    email_text: str


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "MINAI Freight OS API",
    }


@app.post("/process-email")
def process_email(request: ProcessEmailRequest):
    shipment = parse_email_with_ai(request.email_text)
    result = process_shipment(
    shipment=shipment,
    email_text=request.email_text,
)

    return serialize_result(result)


@app.get("/run-test-suite")
def run_test_suite():
    test_results = []

    for test_case in AI_EMAIL_TEST_CASES:
        shipment = parse_email_with_ai(test_case["email"])
        result = process_shipment(
    shipment=shipment,
    email_text=test_case["email"],
)

        test_results.append(
            evaluate_test_result(
                test_case=test_case,
                result=result,
            )
        )

    passed_count = sum(1 for result in test_results if result["passed"])
    failed_count = len(test_results) - passed_count

    return {
        "summary": {
            "passed": passed_count,
            "failed": failed_count,
            "total": len(test_results),
        },
        "results": test_results,
    }


def serialize_result(result: dict) -> dict:
    shipment = result["shipment"]
    missing_info = result.get("missing_info")
    equipment_decision = result.get("equipment_decision")
    risk_assessment = result.get("risk_assessment")
    supplier_quote = result.get("supplier_quote")
    customer_quote = result.get("customer_quote")
    quote_draft = result.get("quote_draft")
    clarification_draft = result.get("clarification_draft")
    management_review_draft = result.get("management_review_draft")
    customer_memory = result.get("customer_memory")
    action_recommendation = result.get("action_recommendation")

    return {
        "shipment": shipment.model_dump() if shipment else None,
        "missing_info": missing_info.model_dump() if missing_info else None,
        "equipment_decision": equipment_decision.model_dump() if equipment_decision else None,
        "risk_assessment": risk_assessment.model_dump() if risk_assessment else None,
        "supplier_quote": supplier_quote.model_dump() if supplier_quote else None,
        "customer_quote": customer_quote.model_dump() if customer_quote else None,
        "quote_draft": quote_draft.model_dump() if quote_draft else None,
        "clarification_draft": clarification_draft.model_dump() if clarification_draft else None,
        "management_review_draft": management_review_draft.model_dump() if management_review_draft else None,
        "customer_memory": customer_memory.model_dump() if customer_memory else None,
        "result_type": determine_result_type(result),
        "action_recommendation": action_recommendation.model_dump() if action_recommendation else None,
    }


def determine_result_type(result: dict) -> str:
    if result.get("management_review_draft"):
        return "management_review"

    if result.get("clarification_draft"):
        return "clarification"

    if result.get("quote_draft"):
        return "quote"

    return "unknown"