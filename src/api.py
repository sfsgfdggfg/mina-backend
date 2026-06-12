from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from src.core.customer_memory import (
    CustomerMemoryProfile,
    load_customer_memory,
    save_customer_profile,
    set_customer_profile_active_status,
    update_customer_profile,
)
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

class CustomerMemoryCreateRequest(BaseModel):
    customer_name: str
    active: bool = True
    aliases: List[str] = []

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None

    default_pickup_city: Optional[str] = None
    default_pickup_area: Optional[str] = None
    default_pickup_country: Optional[str] = None

    default_delivery_city: Optional[str] = None
    default_delivery_country: Optional[str] = None

    last_updated_by: Optional[str] = "ui"
    change_note: Optional[str] = "Customer profile created from UI."

    operational_notes: List[str] = []

class CustomerMemoryUpdateRequest(BaseModel):
    original_customer_name: str
    customer_name: str
    active: bool = True
    aliases: List[str] = []

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None

    default_pickup_city: Optional[str] = None
    default_pickup_area: Optional[str] = None
    default_pickup_country: Optional[str] = None

    default_delivery_city: Optional[str] = None
    default_delivery_country: Optional[str] = None

    last_updated_by: Optional[str] = "ui"
    change_note: Optional[str] = "Customer profile updated from UI."

    operational_notes: List[str] = []

class CustomerMemoryStatusUpdateRequest(BaseModel):
    customer_name: str
    active: bool

@app.put("/customer-memory")
def update_customer_memory_profile(request: CustomerMemoryUpdateRequest):
    profile = CustomerMemoryProfile(
        customer_name=request.customer_name,
        active=request.active,
        aliases=request.aliases,
        default_commodity=request.default_commodity,
        default_equipment_type=request.default_equipment_type,
        price_sensitivity=request.price_sensitivity,
        time_sensitivity=request.time_sensitivity,
        default_pickup_city=request.default_pickup_city,
        default_pickup_area=request.default_pickup_area,
        default_pickup_country=request.default_pickup_country,
        default_delivery_city=request.default_delivery_city,
        default_delivery_country=request.default_delivery_country,
        operational_notes=request.operational_notes,
        last_updated_by=request.last_updated_by,
        change_note=request.change_note,
    )

    try:
        updated_profile = update_customer_profile(
            customer_name=request.original_customer_name,
            updated_profile=profile,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    return {
        "status": "updated",
        "profile": updated_profile.model_dump(),
    }

@app.patch("/customer-memory/status")
def update_customer_memory_status(request: CustomerMemoryStatusUpdateRequest):
    try:
        updated_profile = set_customer_profile_active_status(
            customer_name=request.customer_name,
            active=request.active,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=404,
            detail=str(error),
        )

    return {
        "status": "updated",
        "profile": updated_profile.model_dump(),
    }

@app.get("/customer-memory")
def get_customer_memory():
    profiles = load_customer_memory()

    return {
        "count": len(profiles),
        "profiles": [
            profile.model_dump()
            for profile in profiles
        ],
    }


@app.post("/customer-memory")
def create_customer_memory_profile(request: CustomerMemoryCreateRequest):
    profile = CustomerMemoryProfile(
        customer_name=request.customer_name,
        active=request.active,
        aliases=request.aliases,
        default_commodity=request.default_commodity,
        default_equipment_type=request.default_equipment_type,
        price_sensitivity=request.price_sensitivity,
        time_sensitivity=request.time_sensitivity,
        default_pickup_city=request.default_pickup_city,
        default_pickup_area=request.default_pickup_area,
        default_pickup_country=request.default_pickup_country,
        default_delivery_city=request.default_delivery_city,
        default_delivery_country=request.default_delivery_country,
        operational_notes=request.operational_notes,
        last_updated_by=request.last_updated_by,
        change_note=request.change_note,
    )

    try:
        saved_profile = save_customer_profile(profile)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    return {
        "status": "created",
        "profile": saved_profile.model_dump(),
    }

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

@app.get("/customer-memory/export")
def export_customer_memory():
    profiles = load_customer_memory()

    return {
        "export_type": "customer_memory",
        "profile_count": len(profiles),
        "profiles": [
            profile.model_dump()
            for profile in profiles
        ],
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