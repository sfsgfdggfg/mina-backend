from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from src.core.commodity_profile import get_commodity_record
from src.core.commodity_dictionary_validator import validate_commodity_dictionary_file
from src.core.supplier_capability_validator import validate_supplier_capabilities_file
from src.core.hs_commodity_map_validator import validate_hs_commodity_map_file
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.data_health import build_data_health_summary
from src.core.customer_memory import (
    CustomerMemoryProfile,
    load_customer_memory,
    save_customer_profile,
    set_customer_profile_active_status,
    update_customer_profile,
    apply_customer_memory_import,
    list_customer_memory_backups,
    read_customer_memory_backup,
    restore_customer_memory_from_backup,
    build_customer_memory_backup_cleanup_preview,
)
from src.ai.email_parser import parse_email_with_ai
from src.workflow.pipeline import process_shipment
from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval
from src.core.quote_send_service import prepare_quote_for_sending
from src.simulation.ai_email_test_cases import AI_EMAIL_TEST_CASES
from src.simulation.test_reporter import evaluate_test_result, evaluate_commodity_dictionary_validation, evaluate_supplier_capability_validation, evaluate_supplier_adr_capability_validation, evaluate_supplier_capability_registry_validation, evaluate_supplier_capability_registry_runtime_integrity, evaluate_customer_memory_validation, evaluate_hs_commodity_map_validation, evaluate_workflow_result_contract, evaluate_quote_readiness_blocked_state, evaluate_action_recommendation_result_contract, evaluate_supplier_rfq_draft_generation, evaluate_supplier_rfq_workflow_contract, evaluate_supplier_rfq_contact_propagation, evaluate_supplier_rfq_response_simulation, evaluate_supplier_quote_selection, evaluate_supplier_rfq_response_validation, evaluate_supplier_fallback_consistency, evaluate_final_quote_consistency_block, evaluate_supplier_response_required_state, evaluate_supplier_rfq_lifecycle_synchronization, evaluate_supplier_rfq_response_link_integrity, evaluate_supplier_rfq_response_validation_report, evaluate_supplier_rfq_response_status_rules, evaluate_supplier_rfq_api_contract, evaluate_supplier_quote_comparison_model, evaluate_multi_criteria_supplier_quote_selection, evaluate_supplier_quote_selection_traceability, evaluate_supplier_rfq_repository, evaluate_supplier_rfq_repository_workflow_integration, evaluate_quote_approval_model, evaluate_quote_approval_workflow_contract, evaluate_quote_send_safety_regression, evaluate_quote_send_service, evaluate_quote_send_api_contract, evaluate_supplier_rfq_response_validation_report, evaluate_supplier_rfq_response_validation_report


app = FastAPI(
    title="MINAI Freight OS API",
    description="AI-powered freight operations assistant API",
    version="0.1.0",
)


class ProcessEmailRequest(BaseModel):
    email_text: str


class PrepareQuoteSendRequest(BaseModel):
    recipient_email: str
    approval: QuoteApproval | None
    supplier_quote: SupplierQuote
    customer_quote: CustomerQuote
    quote_draft: QuoteDraft

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

class CustomerMemoryImportValidateRequest(BaseModel):
    import_data: dict

class CustomerMemoryRestoreRequest(BaseModel):
    file_name: str

RESERVED_CUSTOMER_MEMORY_TERMS = {
    "test",
    "demo",
    "deneme",
    "sample",
    "example",
    "dummy",
    "unknown",
    "unknown customer",
    "müşteri",
    "firma",
    "company",
    "customer",
    "client",
}


def normalize_import_value(value) -> str:
    if value is None:
        return ""

    return str(value).strip().lower()


def validate_customer_memory_import_data(import_data: dict) -> dict:
    profiles = import_data.get("profiles")

    errors = []
    warnings = []

    if profiles is None:
        return {
            "valid": False,
            "profile_count": 0,
            "customer_names": [],
            "errors": ["Geçersiz export formatı: 'profiles' alanı bulunamadı."],
            "warnings": [],
        }

    if not isinstance(profiles, list):
        return {
            "valid": False,
            "profile_count": 0,
            "customer_names": [],
            "errors": ["Geçersiz export formatı: 'profiles' alanı liste olmalı."],
            "warnings": [],
        }

    customer_names = []
    seen_names = set()
    seen_aliases = set()

    duplicate_names = []
    duplicate_aliases = []
    reserved_warnings = []

    for index, profile in enumerate(profiles, start=1):
        if not isinstance(profile, dict):
            errors.append(f"Profile #{index}: profil objesi geçerli değil.")
            continue

        customer_name = str(profile.get("customer_name", "")).strip()
        aliases = profile.get("aliases", [])

        customer_names.append(customer_name or f"Unnamed profile #{index}")

        normalized_name = normalize_import_value(customer_name)

        if normalized_name in RESERVED_CUSTOMER_MEMORY_TERMS:
            reserved_warnings.append(
                f"Profile #{index}: reserved customer name kullanıyor: {customer_name}"
            )

        if normalized_name:
            if normalized_name in seen_names:
                duplicate_names.append(customer_name)
            seen_names.add(normalized_name)

        if not isinstance(aliases, list):
            errors.append(f"Profile #{index}: aliases alanı liste değil.")
            aliases = []

        for alias in aliases:
            normalized_alias = normalize_import_value(alias)

            if normalized_alias in RESERVED_CUSTOMER_MEMORY_TERMS:
                reserved_warnings.append(
                    f"Profile #{index}: reserved alias kullanıyor: {alias}"
                )

            if normalized_alias:
                if normalized_alias in seen_aliases:
                    duplicate_aliases.append(str(alias))
                seen_aliases.add(normalized_alias)

    for name in duplicate_names:
        warnings.append(f"Duplicate customer name bulundu: {name}")

    for alias in duplicate_aliases:
        warnings.append(f"Duplicate alias bulundu: {alias}")

    warnings.extend(reserved_warnings)

    return {
        "valid": len(errors) == 0,
        "profile_count": len(profiles),
        "customer_names": customer_names,
        "errors": errors,
        "warnings": warnings,
        "duplicate_names": duplicate_names,
        "duplicate_aliases": duplicate_aliases,
        "reserved_warnings": reserved_warnings,
    }

def build_customer_memory_import_dry_run(import_data: dict) -> dict:
    validation_result = validate_customer_memory_import_data(import_data)

    if not validation_result.get("valid"):
        return {
            "valid": False,
            "profile_count": validation_result.get("profile_count", 0),
            "errors": validation_result.get("errors", []),
            "warnings": validation_result.get("warnings", []),
            "new_profiles": [],
            "existing_profiles": [],
            "name_conflicts": [],
            "alias_conflicts": [],
            "will_add": [],
            "will_update": [],
            "will_skip": [],
        }

    imported_profiles = import_data.get("profiles", [])
    current_profiles = load_customer_memory()

    current_names = {}
    current_aliases = {}

    for profile in current_profiles:
        normalized_name = normalize_import_value(profile.customer_name)

        if normalized_name:
            current_names[normalized_name] = profile.customer_name

        for alias in profile.aliases:
            normalized_alias = normalize_import_value(alias)

            if normalized_alias:
                current_aliases[normalized_alias] = {
                    "alias": alias,
                    "customer_name": profile.customer_name,
                }

    new_profiles = []
    existing_profiles = []
    name_conflicts = []
    alias_conflicts = []
    will_add = []
    will_update = []
    will_skip = []

    for index, profile in enumerate(imported_profiles, start=1):
        customer_name = str(profile.get("customer_name", "")).strip()
        normalized_name = normalize_import_value(customer_name)
        aliases = profile.get("aliases", [])

        if not customer_name:
            will_skip.append(
                {
                    "profile_index": index,
                    "reason": "Customer name is empty.",
                }
            )
            continue

        if normalized_name in current_names:
            existing_profiles.append(customer_name)
            will_update.append(customer_name)
        else:
            new_profiles.append(customer_name)
            will_add.append(customer_name)

        if not isinstance(aliases, list):
            will_skip.append(
                {
                    "profile_index": index,
                    "customer_name": customer_name,
                    "reason": "Aliases field is not a list.",
                }
            )
            continue

        for alias in aliases:
            normalized_alias = normalize_import_value(alias)

            if not normalized_alias:
                continue

            current_alias_match = current_aliases.get(normalized_alias)

            if current_alias_match:
                matched_customer_name = current_alias_match["customer_name"]

                if normalize_import_value(matched_customer_name) != normalized_name:
                    alias_conflicts.append(
                        {
                            "import_customer_name": customer_name,
                            "alias": alias,
                            "existing_customer_name": matched_customer_name,
                        }
                    )

    return {
        "valid": True,
        "profile_count": len(imported_profiles),
        "current_profile_count": len(current_profiles),
        "errors": validation_result.get("errors", []),
        "warnings": validation_result.get("warnings", []),
        "new_profiles": new_profiles,
        "existing_profiles": existing_profiles,
        "name_conflicts": name_conflicts,
        "alias_conflicts": alias_conflicts,
        "will_add": will_add,
        "will_update": will_update,
        "will_skip": will_skip,
    }

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


@app.post("/quotes/prepare-send")
def prepare_quote_send(request: PrepareQuoteSendRequest):
    try:
        result = prepare_quote_for_sending(
            recipient_email=request.recipient_email,
            approval=request.approval,
            supplier_quote=request.supplier_quote,
            customer_quote=request.customer_quote,
            quote_draft=request.quote_draft,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return result.model_dump()


@app.post("/process-email")
def process_email(request: ProcessEmailRequest):
    shipment = parse_email_with_ai(request.email_text)
    result = process_shipment(
    shipment=shipment,
    email_text=request.email_text,
)

    return serialize_result(result)

@app.post("/customer-memory/import/validate")
def validate_customer_memory_import(
    request: CustomerMemoryImportValidateRequest,
):
    return validate_customer_memory_import_data(request.import_data)

@app.get("/run-test-suite")
def run_test_suite():
    test_results = []
    test_results.append(evaluate_commodity_dictionary_validation())
    test_results.append(evaluate_supplier_capability_validation())
    test_results.append(evaluate_supplier_adr_capability_validation())
    test_results.append(evaluate_supplier_capability_registry_validation())
    test_results.append(evaluate_supplier_capability_registry_runtime_integrity())
    test_results.append(evaluate_customer_memory_validation())
    test_results.append(evaluate_hs_commodity_map_validation())
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
    test_results.append(evaluate_final_quote_consistency_block())
    test_results.append(evaluate_supplier_response_required_state())
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
    test_results.append(evaluate_quote_send_safety_regression())
    test_results.append(evaluate_quote_send_service())
    test_results.append(evaluate_quote_send_api_contract())
    test_results.append(evaluate_supplier_rfq_response_validation_report())
    test_results.append(evaluate_supplier_rfq_response_validation_report())

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

@app.post("/customer-memory/import/dry-run")
def dry_run_customer_memory_import(
    request: CustomerMemoryImportValidateRequest,
):
    return build_customer_memory_import_dry_run(request.import_data)

@app.post("/customer-memory/import/apply")
def apply_customer_memory_import_endpoint(
    request: CustomerMemoryImportValidateRequest,
):
    validation_result = validate_customer_memory_import_data(request.import_data)

    if not validation_result.get("valid"):
        return {
            "success": False,
            "message": "Import validation failed.",
            "validation_result": validation_result,
        }

    dry_run_result = build_customer_memory_import_dry_run(request.import_data)

    if dry_run_result.get("alias_conflicts"):
        return {
            "success": False,
            "message": "Import blocked because alias conflicts were found.",
            "dry_run_result": dry_run_result,
        }

    result = apply_customer_memory_import(
        request.import_data,
        updated_by="api_import",
    )

    return {
        "success": True,
        "message": "Customer memory import applied successfully.",
        "result": result,
    }

@app.get("/customer-memory/backups")
def get_customer_memory_backups():
    return {
        "backups": list_customer_memory_backups()
    }

@app.get("/customer-memory/backups/cleanup-preview")
def get_customer_memory_backup_cleanup_preview(
    keep_latest: int = 10,
):
    return build_customer_memory_backup_cleanup_preview(
        keep_latest=keep_latest,
    )

@app.get("/customer-memory/backups/{file_name}")
def get_customer_memory_backup(file_name: str):
    return read_customer_memory_backup(file_name)

@app.post("/customer-memory/backups/restore")
def restore_customer_memory_backup(
    request: CustomerMemoryRestoreRequest,
):
    backup_data = read_customer_memory_backup(request.file_name)

    backup_import_data = {
        "profiles": backup_data.get("profiles", [])
    }

    validation_result = validate_customer_memory_import_data(backup_import_data)

    if not validation_result.get("valid"):
        return {
            "success": False,
            "message": "Restore validation failed.",
            "validation_result": validation_result,
        }

    dry_run_result = build_customer_memory_import_dry_run(backup_import_data)

    if dry_run_result.get("alias_conflicts"):
        return {
            "success": False,
            "message": "Restore blocked because alias conflicts were found.",
            "dry_run_result": dry_run_result,
        }

    result = restore_customer_memory_from_backup(
        request.file_name,
        updated_by="api_restore",
    )

    return {
        "success": True,
        "message": "Customer memory restored successfully.",
        "result": result,
    }


@app.get("/commodity-dictionary/validation")
def get_commodity_dictionary_validation():
    return validate_commodity_dictionary_file()


@app.get("/supplier-capabilities/validation")
def get_supplier_capabilities_validation():
    return validate_supplier_capabilities_file()


@app.get("/customer-memory/validation")
def get_customer_memory_validation():
    return validate_customer_memory_file()


@app.get("/hs-commodity-map/validation")
def get_hs_commodity_map_validation():
    return validate_hs_commodity_map_file()



@app.get("/data-health/summary")
def get_data_health_summary():
    return build_data_health_summary()

def serialize_result(result: dict) -> dict:
    shipment = result["shipment"]
    missing_info = result.get("missing_info")
    equipment_decision = result.get("equipment_decision")
    risk_assessment = result.get("risk_assessment")
    supplier_selection = result.get("supplier_selection")
    operational_consistency = result.get("operational_consistency")
    quote_readiness = result.get("quote_readiness")
    supplier_rfq_drafts = result.get("supplier_rfq_drafts") or []
    supplier_rfq_responses = result.get("supplier_rfq_responses") or []
    valid_supplier_rfq_responses = result.get(
        "valid_supplier_rfq_responses"
    ) or []
    supplier_rfq_response_validation = result.get(
        "supplier_rfq_response_validation"
    )
    supplier_quote_comparisons = result.get(
        "supplier_quote_comparisons"
    ) or []
    supplier_quote_selection_decision = result.get(
        "supplier_quote_selection_decision"
    )
    supplier_quote = result.get("supplier_quote")
    customer_quote = result.get("customer_quote")
    quote_draft = result.get("quote_draft")
    quote_approval = result.get("quote_approval")
    quote_send_safety = result.get("quote_send_safety")
    clarification_draft = result.get("clarification_draft")
    management_review_draft = result.get("management_review_draft")
    customer_memory = result.get("customer_memory")
    action_recommendation = result.get("action_recommendation")
    commodity_profile = result.get("commodity_profile") or (get_commodity_record(shipment.commodity) if shipment else None)

    return {
        "shipment": shipment.model_dump() if shipment else None,
        "missing_info": missing_info.model_dump() if missing_info else None,
        "equipment_decision": equipment_decision.model_dump() if equipment_decision else None,
        "risk_assessment": risk_assessment.model_dump() if risk_assessment else None,
        "supplier_selection": supplier_selection,
        "operational_consistency": operational_consistency,
        "quote_readiness": quote_readiness.model_dump() if quote_readiness else None,
        "supplier_rfq_drafts": [
            draft.model_dump() if hasattr(draft, "model_dump") else draft
            for draft in supplier_rfq_drafts
        ],
        "supplier_rfq_responses": [
            response.model_dump() if hasattr(response, "model_dump") else response
            for response in supplier_rfq_responses
        ],
        "valid_supplier_rfq_responses": [
            response.model_dump() if hasattr(response, "model_dump") else response
            for response in valid_supplier_rfq_responses
        ],
        "supplier_rfq_response_validation": (
            supplier_rfq_response_validation.model_dump()
            if hasattr(supplier_rfq_response_validation, "model_dump")
            else supplier_rfq_response_validation
        ),
        "supplier_quote_comparisons": [
            comparison.model_dump()
            if hasattr(comparison, "model_dump")
            else comparison
            for comparison in supplier_quote_comparisons
        ],
        "supplier_quote_selection_decision": (
            supplier_quote_selection_decision.model_dump()
            if hasattr(
                supplier_quote_selection_decision,
                "model_dump",
            )
            else supplier_quote_selection_decision
        ),
        "supplier_quote": supplier_quote.model_dump() if supplier_quote else None,
        "customer_quote": customer_quote.model_dump() if customer_quote else None,
        "quote_draft": quote_draft.model_dump() if quote_draft else None,
        "quote_approval": (
            quote_approval.model_dump()
            if hasattr(quote_approval, "model_dump")
            else quote_approval
        ),
        "quote_send_safety": (
            quote_send_safety.model_dump()
            if hasattr(quote_send_safety, "model_dump")
            else quote_send_safety
        ),
        "clarification_draft": clarification_draft.model_dump() if clarification_draft else None,
        "management_review_draft": management_review_draft.model_dump() if management_review_draft else None,
        "customer_memory": customer_memory.model_dump() if customer_memory else None,
        "commodity_profile": commodity_profile,
        "result_type": determine_result_type(result),
        "action_recommendation": action_recommendation.model_dump() if action_recommendation else None,
    }


def determine_result_type(result: dict) -> str:
    quote_readiness = result.get("quote_readiness")

    if quote_readiness:
        return quote_readiness.result_type

    direct_result_type = result.get("result_type")

    if direct_result_type:
        return str(direct_result_type)

    return "unknown"
