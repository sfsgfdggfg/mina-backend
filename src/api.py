from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from typing import Any, List, Literal, Optional
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
from src.ai.email_parser import (
    EmailParserUnavailableError,
    parse_email_with_ai,
)
from src.ai.supplier_response_parser import (
    OpenAISupplierResponseParser,
)
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import (
    SupplierRFQWorkflowProgressionError,
    SupplierRFQWorkflowNotFoundError,
    resume_supplier_rfq_workflow,
)
from src.workflow.supplier_response_ingestion import (
    SupplierReplyIngestionRequest,
    ingest_supplier_reply,
)
from src.workflow.mail_delivery import send_supplier_rfq_via_mail
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
    process_customer_inquiry_mail,
)
from src.workflow.outlook_pull import (
    pull_controlled_outlook_inbox,
)
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationError,
)
from src.integrations.outlook_graph import (
    MAX_PULL_MESSAGES,
    OutlookGraphMessageError,
    OutlookGraphReadError,
)
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    ExtractionCorrectionError,
    ExtractionProposalNotFoundError,
    confirm_extraction_proposal,
    resume_confirmed_extraction,
)
from src.core.pilot_store import SQLitePilotStore
from src.core.runtime_release import runtime_release_payload
from src.core.pilot_access import (
    authorize_pilot_request,
    pilot_mode_enabled,
)
from src.core.operational_data import operational_data_sources_from_environment
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.mail import (
    InboundMailEnvelope,
    OutboundMailSender,
    validate_inbound_mail_body,
)
from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    SupplierQuote,
)
from src.core.pricing_policy import PricingFormula
from src.core.quote_approval import QuoteApproval
from src.core.quote_approval_service import (
    QuoteApprovalNotFoundError,
    QuoteApprovalTransitionError,
    approve_quote,
    invalidate_quote_approval,
    reject_quote,
)
from src.core.quote_revision_service import (
    QuoteRevisionNotFoundError,
    QuoteRevisionTransitionError,
    revise_quote_case as revise_quote_case_service,
)
from src.core.quote_final_output import (
    QuoteFinalOutputNotFoundError,
    QuoteFinalOutputTransitionError,
    build_quote_final_output,
)
from src.core.quote_manual_sent import (
    CustomerQuoteManualSentNotFoundError,
    CustomerQuoteManualSentTransitionError,
    record_customer_quote_manually_sent,
)
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.quote_send_service import prepare_quote_for_sending
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQFollowUpNotFoundError,
    SupplierRFQNotFoundError,
    SupplierRFQResponseError,
    SupplierRFQTransitionError,
    approve_supplier_rfq,
    approve_supplier_rfq_follow_up,
    attach_supplier_rfq_response,
    record_supplier_rfq_follow_up_manually_sent,
    record_supplier_rfq_manually_sent,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQResponseError,
)



app = FastAPI(
    title="MINAI Freight OS API",
    description="AI-powered freight operations assistant API",
    version="0.1.0",
)


@app.middleware("http")
async def enforce_pilot_access(request: Request, call_next):
    decision = authorize_pilot_request(
        method=request.method,
        path=request.url.path,
        client_host=(
            request.client.host
            if request.client is not None
            else None
        ),
        authorization=request.headers.get("Authorization"),
        request_scheme=request.url.scheme,
    )
    if not decision.allowed:
        return JSONResponse(
            status_code=decision.status_code,
            content={"detail": decision.reason},
        )
    request.state.pilot_operator = decision.operator_name
    return await call_next(request)


def _authenticated_operator(
    request: Request | None,
    claimed_identity: str | None = None,
) -> str:
    authenticated = (
        getattr(request.state, "pilot_operator", None)
        if request is not None
        else None
    )
    if authenticated:
        return authenticated
    if pilot_mode_enabled():
        raise HTTPException(
            status_code=401,
            detail="pilot_authentication_required",
        )
    normalized = (claimed_identity or "").strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="Operator identity is required.",
        )
    return normalized


pilot_store = SQLitePilotStore()
operational_data_sources = operational_data_sources_from_environment()
quote_approval_repository = SQLiteQuoteApprovalRepository(pilot_store)
quote_case_repository = SQLiteQuoteCaseRepository(pilot_store)
supplier_rfq_repository = SQLiteSupplierRFQRepository(pilot_store)
extraction_proposal_repository = SQLiteExtractionProposalRepository(pilot_store)
outbound_mail_sender: OutboundMailSender | None = None


class ProcessEmailRequest(BaseModel):
    email_text: str
    sender_address: Optional[str] = None
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    external_message_id: Optional[str] = None

    @field_validator("email_text")
    @classmethod
    def validate_email_text(cls, value: str) -> str:
        return validate_inbound_mail_body(value)



class OutlookPullRequest(BaseModel):
    limit: int = Field(
        default=10,
        ge=1,
        le=MAX_PULL_MESSAGES,
    )


class ConfirmExtractionRequest(BaseModel):
    operator_identity: Optional[str] = None
    corrections: dict[str, Any] = Field(default_factory=dict)


class PrepareQuoteSendRequest(BaseModel):
    recipient_email: str
    approval_id: str
    supplier_quote: SupplierQuote
    customer_quote: CustomerQuote
    quote_draft: QuoteDraft


class QuoteCaseRevisionRequest(BaseModel):
    expected_approval_id: str
    subject: str
    body: str
    final_price: Optional[float] = Field(
        default=None,
        gt=0,
    )
    operator_note: Optional[str] = None


class QuoteCaseManualSentRequest(BaseModel):
    expected_approval_id: str
    recipient_email: str
    sent_by: Optional[str] = None


class QuoteApprovalApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class QuoteApprovalRejectRequest(BaseModel):
    rejection_reason: str


class SupplierRFQApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class SupplierRFQManualSentRequest(BaseModel):
    recorded_by: Optional[str] = None


class SupplierRFQResponseRequest(BaseModel):
    supplier_name: str
    rfq_priority: int
    status: Literal[
        "quoted",
        "no_capacity",
        "declined",
        "needs_clarification",
    ]
    cost: Optional[float] = None
    currency: Optional[str] = None
    transit_time: Optional[str] = None
    validity_date: Optional[str] = None
    vehicle_available_date: Optional[str] = None
    equipment_type: Optional[str] = None
    pricing_basis: Optional[
        Literal["all_in", "base_freight_plus_extras"]
    ] = None
    included_costs: Optional[List[str]] = None
    excluded_costs: Optional[List[str]] = None
    notes: Optional[str] = None
    recorded_by: Optional[str] = None


class ResumeSupplierQuoteRequest(BaseModel):
    quote_pricing_override: Optional[PricingFormula] = None


class CustomerMemoryCreateRequest(BaseModel):
    customer_name: str
    active: bool = True
    aliases: List[str] = []
    trusted_sender_addresses: List[str] = []
    trusted_sender_domains: List[str] = []

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None
    pricing_policy: Optional[PricingFormula] = None

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
    trusted_sender_addresses: List[str] = []
    trusted_sender_domains: List[str] = []

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None
    pricing_policy: Optional[PricingFormula] = None

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
        trusted_sender_addresses=request.trusted_sender_addresses,
        trusted_sender_domains=request.trusted_sender_domains,
        default_commodity=request.default_commodity,
        default_equipment_type=request.default_equipment_type,
        price_sensitivity=request.price_sensitivity,
        time_sensitivity=request.time_sensitivity,
        pricing_policy=request.pricing_policy,
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
        trusted_sender_addresses=request.trusted_sender_addresses,
        trusted_sender_domains=request.trusted_sender_domains,
        default_commodity=request.default_commodity,
        default_equipment_type=request.default_equipment_type,
        price_sensitivity=request.price_sensitivity,
        time_sensitivity=request.time_sensitivity,
        pricing_policy=request.pricing_policy,
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


@app.get("/runtime/release")
def runtime_release():
    return runtime_release_payload()


def _enrich_quote_case_with_current_approval(quote_case):
    snapshot_approval = quote_case.quote_approval

    if snapshot_approval is None:
        return quote_case

    current_approval = quote_approval_repository.get(
        snapshot_approval.approval_id
    )

    if not all(
        [
            quote_case.supplier_quote,
            quote_case.customer_quote,
            quote_case.quote_draft,
        ]
    ):
        return quote_case.model_copy(
            update={"quote_approval": current_approval}
        )

    current_send_safety = evaluate_quote_send_safety(
        approval=current_approval,
        supplier_quote=quote_case.supplier_quote,
        customer_quote=quote_case.customer_quote,
        quote_draft=quote_case.quote_draft,
        regulatory_compliance=quote_case.regulatory_compliance,
    )

    return quote_case.model_copy(
        update={
            "quote_approval": current_approval,
            "quote_send_safety": current_send_safety,
        }
    )


@app.get("/quote-cases")
def list_quote_cases():
    return {
        "quote_cases": [
            _enrich_quote_case_with_current_approval(
                quote_case
            ).model_dump()
            for quote_case in quote_case_repository.list_all()
        ]
    }


@app.get("/quote-cases/{case_id}")
def get_quote_case(case_id: str):
    quote_case = quote_case_repository.get(case_id)

    if quote_case is None:
        raise HTTPException(
            status_code=404,
            detail=f"Quote case not found: {case_id}",
        )

    return _enrich_quote_case_with_current_approval(
        quote_case
    ).model_dump()


@app.post("/quote-cases/{case_id}/record-manually-sent")
def record_quote_case_manually_sent(
    case_id: str,
    request: QuoteCaseManualSentRequest,
    http_request: Request = None,
):
    try:
        result = record_customer_quote_manually_sent(
            quote_case_repository=quote_case_repository,
            approval_repository=quote_approval_repository,
            case_id=case_id,
            expected_approval_id=request.expected_approval_id,
            recipient_email=request.recipient_email,
            sent_by=_authenticated_operator(
                http_request,
                request.sent_by,
            ),
        )
    except CustomerQuoteManualSentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerQuoteManualSentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result.model_dump()


@app.get("/quote-cases/{case_id}/final-output")
def get_quote_case_final_output(case_id: str):
    try:
        result = build_quote_final_output(
            quote_case_repository=quote_case_repository,
            approval_repository=quote_approval_repository,
            case_id=case_id,
        )
    except QuoteFinalOutputNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except QuoteFinalOutputTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return result.model_dump()


@app.post("/quote-cases/{case_id}/revise")
def revise_quote_case_endpoint(
    case_id: str,
    request: QuoteCaseRevisionRequest,
    http_request: Request = None,
):
    try:
        result = revise_quote_case_service(
            quote_case_repository=(
                quote_case_repository
            ),
            approval_repository=(
                quote_approval_repository
            ),
            case_id=case_id,
            expected_approval_id=(
                request.expected_approval_id
            ),
            subject=request.subject,
            body=request.body,
            final_price=request.final_price,
            operator_note=request.operator_note,
            edited_by=_authenticated_operator(
                http_request
            ),
        )
    except QuoteRevisionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except QuoteRevisionTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return result.model_dump()


@app.get("/quote-approvals")
def list_quote_approvals():
    return {
        "approvals": [
            approval.model_dump()
            for approval in quote_approval_repository.list_all()
        ]
    }


@app.get("/quote-approvals/{approval_id}")
def get_quote_approval(approval_id: str):
    approval = quote_approval_repository.get(approval_id)

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=f"Quote approval not found: {approval_id}",
        )

    return approval.model_dump()


@app.post("/quote-approvals/{approval_id}/approve")
def approve_quote_approval(
    approval_id: str,
    request: QuoteApprovalApproveRequest,
    http_request: Request = None,
):
    try:
        approval = approve_quote(
            repository=quote_approval_repository,
            approval_id=approval_id,
            approved_by=_authenticated_operator(
                http_request,
                request.approved_by,
            ),
        )
    except QuoteApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except QuoteApprovalTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return approval.model_dump()


@app.post("/quote-approvals/{approval_id}/reject")
def reject_quote_approval(
    approval_id: str,
    request: QuoteApprovalRejectRequest,
    http_request: Request = None,
):
    try:
        approval = reject_quote(
            repository=quote_approval_repository,
            approval_id=approval_id,
            rejection_reason=request.rejection_reason,
            rejected_by=_authenticated_operator(http_request),
        )
    except QuoteApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except QuoteApprovalTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return approval.model_dump()


@app.post("/quote-approvals/{approval_id}/invalidate")
def invalidate_quote_approval_endpoint(
    approval_id: str,
    http_request: Request = None,
):
    try:
        approval = invalidate_quote_approval(
            repository=quote_approval_repository,
            approval_id=approval_id,
            invalidated_by=_authenticated_operator(http_request),
        )
    except QuoteApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc
    except QuoteApprovalTransitionError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    return approval.model_dump()


@app.post("/quotes/prepare-send")
def prepare_quote_send(request: PrepareQuoteSendRequest):
    approval = quote_approval_repository.get(
        request.approval_id
    )

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Quote approval not found: "
                f"{request.approval_id}"
            ),
        )

    regulatory_compliance = next(
        (
            quote_case.regulatory_compliance
            for quote_case in quote_case_repository.list_all()
            if quote_case.quote_approval is not None
            and quote_case.quote_approval.approval_id
            == request.approval_id
        ),
        None,
    )

    try:
        result = prepare_quote_for_sending(
            recipient_email=request.recipient_email,
            approval=approval,
            supplier_quote=request.supplier_quote,
            customer_quote=request.customer_quote,
            quote_draft=request.quote_draft,
            regulatory_compliance=regulatory_compliance,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc

    return result.model_dump()


@app.post("/inbound/outlook/pull")
def pull_outlook_inbound(
    request: OutlookPullRequest,
):
    try:
        config = (
            MicrosoftAuthConfig.from_environment()
        )

        result = (
            pull_controlled_outlook_inbox(
                config=config,
                limit=request.limit,
                shipment_parser=(
                    parse_email_with_ai
                ),
                proposal_repository=(
                    extraction_proposal_repository
                ),
                operational_data_sources=(
                    operational_data_sources
                ),
                supplier_parser=(
                    OpenAISupplierResponseParser()
                ),
                supplier_repository=(
                    supplier_rfq_repository
                ),
            )
        )

    except MicrosoftAuthConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "outlook_auth_configuration_invalid"
            ),
        ) from exc

    except MicrosoftAuthenticationError as exc:
        raise HTTPException(
            status_code=428,
            detail=exc.code,
        ) from exc

    except (
        OutlookGraphReadError,
        OutlookGraphMessageError,
    ) as exc:
        raise HTTPException(
            status_code=503,
            detail=getattr(
                exc,
                "code",
                "outlook_graph_read_failed",
            ),
        ) from exc

    return result


@app.post("/process-email")
def process_email(request: ProcessEmailRequest):
    try:
        result = process_customer_inquiry_mail(
            mail=InboundMailEnvelope(
                body_text=request.email_text,
                sender_address=request.sender_address,
                sender_name=request.sender_name,
                subject=request.subject,
                external_message_id=(
                    request.external_message_id
                ),
                source="manual",
            ),
            shipment_parser=parse_email_with_ai,
            proposal_repository=(
                extraction_proposal_repository
            ),
        )
    except InboundMailIdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail="inbound_message_id_conflict",
        ) from exc
    except EmailParserUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail="email_parser_unavailable",
        ) from exc

    return serialize_result(result)


@app.get("/extraction-proposals/{proposal_id}")
def get_extraction_proposal(proposal_id: str):
    proposal = extraction_proposal_repository.get(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail=f"Extraction proposal not found: {proposal_id}",
        )
    return proposal.model_dump()


@app.post("/extraction-proposals/{proposal_id}/confirm")
def confirm_extraction_proposal_endpoint(
    proposal_id: str,
    request: ConfirmExtractionRequest,
    http_request: Request = None,
):
    try:
        proposal = confirm_extraction_proposal(
            repository=extraction_proposal_repository,
            proposal_id=proposal_id,
            operator_identity=_authenticated_operator(
                http_request,
                request.operator_identity,
            ),
            corrections=request.corrections,
        )
    except ExtractionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExtractionConfirmationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ExtractionCorrectionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return proposal.model_dump()


@app.post("/extraction-proposals/{proposal_id}/resume")
def resume_extraction_proposal_endpoint(proposal_id: str):
    try:
        result = resume_confirmed_extraction(
            repository=extraction_proposal_repository,
            proposal_id=proposal_id,
            rfq_repository=supplier_rfq_repository,
            approval_repository=quote_approval_repository,
            quote_case_repository=quote_case_repository,
            evidence_recorder=pilot_store,
            operational_data_sources=operational_data_sources,
        )
    except ExtractionProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ExtractionConfirmationTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_result(result)


@app.get("/supplier-rfqs")
def list_supplier_rfqs():
    return {
        "supplier_rfqs": [
            draft.model_dump()
            for draft in supplier_rfq_repository.list_drafts()
        ]
    }


@app.get("/supplier-rfqs/{rfq_id}")
def get_supplier_rfq(rfq_id: str):
    draft = supplier_rfq_repository.get_draft(rfq_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=f"Supplier RFQ not found: {rfq_id}",
        )
    return {
        **draft.model_dump(),
        "responses": [
            response.model_dump()
            for response in supplier_rfq_repository.list_responses(rfq_id)
        ],
        "follow_ups": [
            item.model_dump()
            for item in supplier_rfq_repository.list_follow_up_drafts(rfq_id)
        ],
    }


@app.get("/supplier-rfqs/{rfq_id}/follow-ups")
def list_supplier_rfq_follow_ups(rfq_id: str):
    draft = supplier_rfq_repository.get_draft(rfq_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail=f"Supplier RFQ not found: {rfq_id}",
        )
    return {
        "rfq_id": rfq_id,
        "follow_ups": [
            {
                **item.model_dump(),
                "manual_sent_evidence": [
                    evidence.model_dump()
                    for evidence in (
                        supplier_rfq_repository
                        .list_follow_up_manual_sent_evidence(item.follow_up_id)
                    )
                ],
            }
            for item in supplier_rfq_repository.list_follow_up_drafts(rfq_id)
        ],
    }


@app.get("/supplier-rfq-follow-ups/{follow_up_id}")
def get_supplier_rfq_follow_up(follow_up_id: str):
    follow_up = supplier_rfq_repository.get_follow_up_draft(follow_up_id)
    if follow_up is None:
        raise HTTPException(
            status_code=404,
            detail=f"Supplier RFQ follow-up not found: {follow_up_id}",
        )
    return {
        **follow_up.model_dump(),
        "manual_sent_evidence": [
            evidence.model_dump()
            for evidence in (
                supplier_rfq_repository
                .list_follow_up_manual_sent_evidence(follow_up_id)
            )
        ],
    }


@app.post("/supplier-rfq-follow-ups/{follow_up_id}/approve")
def approve_supplier_rfq_follow_up_endpoint(
    follow_up_id: str,
    request: SupplierRFQApproveRequest,
    http_request: Request = None,
):
    try:
        return approve_supplier_rfq_follow_up(
            repository=supplier_rfq_repository,
            follow_up_id=follow_up_id,
            approved_by=_authenticated_operator(
                http_request,
                request.approved_by,
            ),
        ).model_dump()
    except SupplierRFQFollowUpNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/supplier-rfq-follow-ups/{follow_up_id}/record-manually-sent")
def record_supplier_rfq_follow_up_manually_sent_endpoint(
    follow_up_id: str,
    request: SupplierRFQManualSentRequest,
    http_request: Request = None,
):
    try:
        follow_up, evidence = record_supplier_rfq_follow_up_manually_sent(
            repository=supplier_rfq_repository,
            follow_up_id=follow_up_id,
            recorded_by=_authenticated_operator(
                http_request,
                request.recorded_by,
            ),
        )
    except SupplierRFQFollowUpNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "supplier_rfq_follow_up": follow_up.model_dump(),
        "manual_sent_evidence": evidence.model_dump(),
    }


@app.post("/supplier-rfqs/{rfq_id}/approve")
def approve_supplier_rfq_endpoint(
    rfq_id: str,
    request: SupplierRFQApproveRequest,
    http_request: Request = None,
):
    try:
        return approve_supplier_rfq(
            repository=supplier_rfq_repository,
            rfq_id=rfq_id,
            approved_by=_authenticated_operator(
                http_request,
                request.approved_by,
            ),
        ).model_dump()
    except SupplierRFQNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/supplier-rfqs/{rfq_id}/send")
def send_supplier_rfq_endpoint(rfq_id: str):
    try:
        return send_supplier_rfq_via_mail(
            repository=supplier_rfq_repository,
            rfq_id=rfq_id,
            sender=outbound_mail_sender,
        ).model_dump()
    except SupplierRFQNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/supplier-rfqs/{rfq_id}/record-manually-sent")
def record_supplier_rfq_manually_sent_endpoint(
    rfq_id: str,
    request: SupplierRFQManualSentRequest,
    http_request: Request = None,
):
    try:
        draft, evidence = record_supplier_rfq_manually_sent(
            repository=supplier_rfq_repository,
            rfq_id=rfq_id,
            recorded_by=_authenticated_operator(
                http_request,
                request.recorded_by,
            ),
        )
    except SupplierRFQNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "supplier_rfq": draft.model_dump(),
        "manual_sent_evidence": evidence.model_dump(),
    }


@app.post("/supplier-rfqs/{rfq_id}/responses")
def attach_supplier_rfq_response_endpoint(
    rfq_id: str,
    request: SupplierRFQResponseRequest,
    http_request: Request = None,
):
    try:
        response_payload = request.model_dump(
            exclude={"recorded_by"}
        )
        response = SupplierRFQResponse(
            rfq_id=rfq_id,
            **response_payload,
            source="manual",
            recorded_by=_authenticated_operator(
                http_request,
                request.recorded_by,
            ),
        )
        draft = attach_supplier_rfq_response(
            repository=supplier_rfq_repository,
            response=response,
        )
        return {
            "supplier_rfq": draft.model_dump(),
            "response": response.model_dump(),
        }
    except SupplierRFQNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        SupplierRFQTransitionError,
        SupplierRFQResponseError,
        DuplicateSupplierRFQResponseError,
    ) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@app.post("/supplier-rfq-workflows/{workflow_id}/resume-quote")
def resume_supplier_rfq_quote(
    workflow_id: str,
    request: ResumeSupplierQuoteRequest | None = None,
):
    try:
        result = resume_supplier_rfq_workflow(
            workflow_id=workflow_id,
            rfq_repository=supplier_rfq_repository,
            approval_repository=quote_approval_repository,
            quote_case_repository=quote_case_repository,
            operational_data_sources=operational_data_sources,
            quote_pricing_override=(
                request.quote_pricing_override if request is not None else None
            ),
        )
    except SupplierRFQWorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQWorkflowProgressionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_result(result)


@app.post("/supplier-responses/ingest")
def ingest_supplier_response(request: SupplierReplyIngestionRequest):
    return ingest_supplier_reply(
        reply=request.reply,
        extracted_response=request.extracted_response,
        repository=supplier_rfq_repository,
    ).model_dump()

@app.post("/customer-memory/import/validate")
def validate_customer_memory_import(
    request: CustomerMemoryImportValidateRequest,
):
    return validate_customer_memory_import_data(request.import_data)

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
    shipment = result.get("shipment")
    pilot_scope = result.get("pilot_scope")
    extraction_proposal = result.get("extraction_proposal")
    missing_info = result.get("missing_info")
    regulatory_compliance = result.get("regulatory_compliance")
    equipment_decision = result.get("equipment_decision")
    risk_assessment = result.get("risk_assessment")
    supplier_selection = result.get("supplier_selection")
    operational_consistency = result.get("operational_consistency")
    quote_readiness = result.get("quote_readiness")
    supplier_rfq_workflow = result.get("supplier_rfq_workflow")
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
    quote_case = result.get("quote_case")
    clarification_draft = result.get("clarification_draft")
    management_review_draft = result.get("management_review_draft")
    customer_memory = result.get("customer_memory")
    action_recommendation = result.get("action_recommendation")
    commodity_profile = result.get("commodity_profile") or (get_commodity_record(shipment.commodity) if shipment else None)

    return {
        "ingestion_status": result.get(
            "ingestion_status"
        ),
        "extraction_proposal": (
            extraction_proposal.model_dump()
            if hasattr(extraction_proposal, "model_dump")
            else extraction_proposal
        ),
        "shipment": shipment.model_dump() if shipment else None,
        "pilot_scope": (
            pilot_scope.model_dump()
            if hasattr(pilot_scope, "model_dump")
            else pilot_scope
        ),
        "missing_info": missing_info.model_dump() if missing_info else None,
        "regulatory_compliance": (
            regulatory_compliance.model_dump()
            if hasattr(regulatory_compliance, "model_dump")
            else regulatory_compliance
        ),
        "equipment_decision": equipment_decision.model_dump() if equipment_decision else None,
        "risk_assessment": risk_assessment.model_dump() if risk_assessment else None,
        "supplier_selection": supplier_selection,
        "operational_consistency": operational_consistency,
        "quote_readiness": quote_readiness.model_dump() if quote_readiness else None,
        "supplier_rfq_workflow": (
            supplier_rfq_workflow.model_dump()
            if hasattr(supplier_rfq_workflow, "model_dump")
            else supplier_rfq_workflow
        ),
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
        "quote_case": (
            quote_case.model_dump()
            if hasattr(quote_case, "model_dump")
            else quote_case
        ),
        "clarification_draft": clarification_draft.model_dump() if clarification_draft else None,
        "management_review_draft": management_review_draft.model_dump() if management_review_draft else None,
        "customer_memory": customer_memory.model_dump() if customer_memory else None,
        "commodity_profile": commodity_profile,
        "result_type": determine_result_type(result),
        "action_recommendation": action_recommendation.model_dump() if action_recommendation else None,
    }


def determine_result_type(result: dict) -> str:
    direct_result_type = result.get("result_type")

    if direct_result_type:
        return str(direct_result_type)

    quote_readiness = result.get("quote_readiness")

    if quote_readiness:
        return quote_readiness.result_type

    return "unknown"
