from datetime import date
import json
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
from src.workflow.automation_scheduler import AutomationScheduler
from src.workflow.mail_delivery import (
    send_supplier_rfq_follow_up_via_mail,
    send_supplier_rfq_via_mail,
)
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
    outlook_graph_sender_from_environment,
)
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    ExtractionCorrectionError,
    ExtractionProposalNotFoundError,
    confirm_extraction_proposal,
    resume_confirmed_extraction,
)
from src.core.pilot_store import SQLitePilotStore
from src.core.supplier_dispatch_policy import resolve_supplier_dispatch_policy
from src.core.business_calendar import supplier_calendar_metadata
from src.core.runtime_release import runtime_release_payload
from src.core.pilot_access import (
    authorize_pilot_request,
    pilot_mode_enabled,
)
from src.core.operational_data import operational_data_sources_from_environment
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteAutomationActionRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalShiftOpenAcceptanceReceiptRepository,
    SQLiteExtractionProposalRepository,
    SQLiteMinaJobRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.mail import (
    InboundMailEnvelope,
    OutboundMailSender,
    validate_inbound_mail_body,
)
from src.core.mina_job_actions import (
    MinaJobActionError,
    preview_supplier_reminder_now,
    send_supplier_reminder_now,
)
from src.core.mina_job_service import (
    MinaJobNotFoundError,
    MinaJobTransitionError,
    create_manual_mina_job,
    set_mina_job_automation_overrides,
    set_mina_job_owners,
    transition_mina_job_stage,
)
from src.core.mina_job_view import build_mina_job_detail, build_mina_job_list
from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    Shipment,
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
from src.core.quote_automated_sent import (
    CustomerQuoteAutomatedSentNotFoundError,
    CustomerQuoteAutomatedSentTransitionError,
    send_customer_quote_and_record,
)
from src.core.quote_manual_sent import (
    CustomerQuoteManualSentNotFoundError,
    CustomerQuoteManualSentTransitionError,
    record_customer_quote_manually_sent,
)
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.quote_send_service import prepare_quote_for_sending
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_dispatch_control import (
    SupplierAcknowledgementError,
    SupplierSecondaryDispatchBlockedError,
    authorize_secondary_after_price_negotiation,
    build_supplier_dispatch_status,
    record_supplier_acknowledgement,
)
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
from src.core.supplier_price_repository import (
    SQLiteSupplierPriceRepository,
    SupplierPriceIdempotencyConflictError,
)
from src.core.supplier_price_service import (
    build_job_supplier_price_view,
    create_direct_supplier_price_offer,
    create_supplier_fixed_rate,
    set_supplier_fixed_rate_active,
    use_fixed_rate_for_job,
)
from src.core.master_data import (
    MasterContact,
    SupplierGeographyCapability,
)
from src.core.master_data_repository import (
    MasterDataConflictError,
    SQLiteMasterDataRepository,
)
from src.core.master_data_service import (
    bootstrap_legacy_master_data,
    create_customer_master,
    create_supplier_master,
    supplier_geography_view,
    update_customer_master,
    update_supplier_master,
)
from src.core.automation_policy_repository import (
    SQLiteAgencyAutomationPolicyRepository,
)
from src.core.automation_policy_service import (
    resolve_effective_automation_policy,
    save_agency_automation_policy,
)
from src.core.attachment_review_queue import build_attachment_review_queue
from src.core.operational_work_queue import build_operational_work_queue
from src.core.operational_work_assignment_service import (
    OperationalWorkAssignmentConflictError,
    OperationalWorkAssignmentNotFoundError,
    OperationalWorkAssignmentTransitionError,
    acknowledge_operational_work,
    assign_operational_work_to_me,
    build_my_operational_work_view,
    decorate_operational_work_queue,
    handoff_operational_work,
    release_operational_work,
    renew_operational_work_assignment,
    takeover_operational_work_assignment,
)
from src.core.operational_shift_summary import build_operational_shift_summary
from src.core.operational_shift_close_readiness import build_operational_shift_close_readiness
from src.core.operational_shift_open_reconciliation import build_operational_shift_open_reconciliation
from src.core.operational_shift_continuity_ledger import build_operational_shift_continuity_ledger
from src.core.operational_shift_open_acceptance import (
    OperationalShiftOpenAcceptanceBlockedError,
    attest_operational_shift_open_acceptance,
    list_operational_shift_open_acceptances,
)
from src.core.operational_shift_close_attestation import (
    OperationalShiftCloseAttestationBlockedError,
    attest_operational_shift_close,
    list_operational_shift_close_receipts,
)
from src.core.operational_work_detail import (
    OperationalWorkItemNotFoundError,
    build_operational_work_item_detail,
)
from src.core.attachment_interpretation_review_service import (
    AttachmentReviewConflictError,
    AttachmentReviewNotFoundError,
    AttachmentReviewTransitionError,
    apply_attachment_interpretation_review,
    attachment_review_public_payload,
    build_attachment_review_preview,
    require_matching_attachment_review_preview,
    reject_attachment_interpretation_review,
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
mina_job_repository = SQLiteMinaJobRepository(pilot_store)
supplier_rfq_repository = SQLiteSupplierRFQRepository(pilot_store)
supplier_price_repository = SQLiteSupplierPriceRepository(pilot_store)
master_data_repository = SQLiteMasterDataRepository(pilot_store)
agency_automation_policy_repository = SQLiteAgencyAutomationPolicyRepository(pilot_store)
extraction_proposal_repository = SQLiteExtractionProposalRepository(pilot_store)
attachment_review_repository = SQLiteAttachmentInterpretationReviewRepository(pilot_store)
automation_action_repository = SQLiteAutomationActionRepository(pilot_store)
operational_work_assignment_repository = SQLiteOperationalWorkAssignmentRepository(pilot_store)
operational_shift_close_receipt_repository = SQLiteOperationalShiftCloseReceiptRepository(pilot_store)
operational_shift_open_acceptance_repository = SQLiteOperationalShiftOpenAcceptanceReceiptRepository(pilot_store)
try:
    outbound_mail_sender: OutboundMailSender | None = outlook_graph_sender_from_environment()
except MicrosoftAuthConfigurationError:
    outbound_mail_sender = None

automation_scheduler = AutomationScheduler(
    supplier_repository=supplier_rfq_repository,
    action_repository=automation_action_repository,
    sender=outbound_mail_sender,
    mina_job_repository=mina_job_repository,
    master_data_repository=master_data_repository,
    agency_policy_repository=agency_automation_policy_repository,
)


@app.on_event("startup")
def start_controlled_automation_scheduler():
    if pilot_mode_enabled():
        automation_scheduler.start()


@app.on_event("shutdown")
def stop_controlled_automation_scheduler():
    automation_scheduler.stop()


@app.get("/automation/status")
def get_automation_status():
    status = automation_scheduler.status()
    policy = resolve_supplier_dispatch_policy()
    durable_policy = agency_automation_policy_repository.get()
    return {
        **status,
        "legacy_workflows_not_auto_activated": True,
        "supplier_reminders_default_enabled": policy.automatic_supplier_reminders_enabled,
        "customer_deadline_updates_default_enabled": policy.automatic_customer_deadline_updates_enabled,
        "durable_agency_policy": None if durable_policy is None else durable_policy.model_dump(),
        "supplier_communication_calendar": supplier_calendar_metadata(),
    }


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
    interpret_attachments: bool = False


class ConfirmExtractionRequest(BaseModel):
    operator_identity: Optional[str] = None
    corrections: dict[str, Any] = Field(default_factory=dict)


class MinaJobManualCreateRequest(BaseModel):
    manual_intake_id: str = Field(min_length=1, max_length=300)
    job_kind: Literal["price_request", "approved_job"]
    intake_channel: Literal["phone", "whatsapp", "portal", "face_to_face", "other"]
    shipment: Shipment
    sales_owner: Optional[str] = Field(default=None, max_length=200)
    operations_owner: Optional[str] = Field(default=None, max_length=200)


class SupplierFixedRateCreateRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=200)
    origin_country: str = Field(min_length=1, max_length=100)
    destination_country: str = Field(min_length=1, max_length=100)
    origin_city: Optional[str] = Field(default=None, max_length=120)
    destination_city: Optional[str] = Field(default=None, max_length=120)
    origin_region: Optional[str] = Field(default=None, max_length=120)
    destination_region: Optional[str] = Field(default=None, max_length=120)
    transport_mode: Optional[Literal["road", "rail", "sea", "air", "multimodal"]] = None
    service_type: Optional[str] = Field(default=None, max_length=80)
    equipment_type: Optional[str] = Field(default=None, max_length=120)
    cost: float = Field(gt=0)
    currency: str = "EUR"
    transit_time: Optional[str] = Field(default=None, max_length=120)
    pricing_basis: Optional[Literal["all_in", "base_freight_plus_extras"]] = None
    included_costs: Optional[list[str]] = None
    excluded_costs: Optional[list[str]] = None
    valid_from: date
    valid_to: date
    evidence_source: Literal["agreement", "email", "phone", "whatsapp", "portal", "excel", "manual"]
    evidence_reference: Optional[str] = Field(default=None, max_length=300)
    notes: Optional[str] = Field(default=None, max_length=2000)
    active: bool = True


class SupplierDirectPriceCreateRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=200)
    source_type: Literal["email", "phone", "whatsapp", "portal", "api", "manual"]
    source_reference_id: Optional[str] = Field(default=None, max_length=300)
    cost: float = Field(gt=0)
    currency: str = "EUR"
    transit_time: Optional[str] = Field(default=None, max_length=120)
    validity_date: Optional[str] = Field(default=None, max_length=80)
    vehicle_available_date: Optional[str] = Field(default=None, max_length=80)
    equipment_type: Optional[str] = Field(default=None, max_length=120)
    pricing_basis: Optional[Literal["all_in", "base_freight_plus_extras"]] = None
    included_costs: Optional[list[str]] = None
    excluded_costs: Optional[list[str]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)


class SupplierFixedRateUseRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=300)


class SupplierFixedRateStatusRequest(BaseModel):
    active: bool


class MinaJobAutomationOverrideRequest(BaseModel):
    disable_supplier_reminders: bool = False
    disable_customer_deadline_updates: bool = False
    supplier_reminder_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    customer_deadline_update_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None


class AgencyAutomationPolicyRequest(BaseModel):
    supplier_reminder_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    customer_deadline_update_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None


class CustomerAutomationPolicyRequest(BaseModel):
    supplier_reminder_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    customer_deadline_update_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None


class MinaJobOwnersRequest(BaseModel):
    sales_owner: Optional[str] = Field(default=None, max_length=200)
    operations_owner: Optional[str] = Field(default=None, max_length=200)


class MinaJobStageTransitionRequest(BaseModel):
    target_stage: Literal[
        "pricing", "quote_ready", "quote_sent", "negotiation",
        "accepted", "operations", "operation_opened",
        "supplier_confirmation_pending", "vehicle_details_pending",
        "vehicle_assigned", "pre_loading_check", "ready_for_loading",
        "loaded", "in_transit", "delivery", "delivered",
        "pod_cmr_pending", "closing_review", "completed",
        "lost", "cancelled",
    ]
    reason: Optional[str] = None


class PreviewAttachmentReviewRequest(BaseModel):
    corrections: dict[str, Any] = Field(default_factory=dict)


class ApplyAttachmentReviewRequest(BaseModel):
    operator_identity: Optional[str] = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    preview_token: str = Field(pattern=r"^[0-9a-f]{64}$")


class RejectAttachmentReviewRequest(BaseModel):
    operator_identity: Optional[str] = None
    rejection_reason: str


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


class QuoteCaseAutomatedSendRequest(BaseModel):
    expected_approval_id: str
    recipient_email: str


class QuoteApprovalApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class QuoteApprovalRejectRequest(BaseModel):
    rejection_reason: str


class SupplierRFQApproveRequest(BaseModel):
    approved_by: Optional[str] = None


class SupplierRFQManualSentRequest(BaseModel):
    recorded_by: Optional[str] = None


class SupplierRFQAcknowledgementRequest(BaseModel):
    channel: Literal["phone", "whatsapp", "manual"]


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


class CustomerMasterCreateRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=300)
    customer_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    aliases: list[str] = Field(default_factory=list)
    trusted_sender_addresses: list[str] = Field(default_factory=list)
    trusted_sender_domains: list[str] = Field(default_factory=list)
    contacts: list[MasterContact] = Field(default_factory=list)
    sales_owner: Optional[str] = Field(default=None, max_length=200)
    default_commodity: Optional[str] = Field(default=None, max_length=300)
    default_equipment_type: Optional[str] = Field(default=None, max_length=300)
    default_pickup_city: Optional[str] = Field(default=None, max_length=200)
    default_pickup_area: Optional[str] = Field(default=None, max_length=300)
    default_pickup_country: Optional[str] = Field(default=None, max_length=120)
    default_delivery_city: Optional[str] = Field(default=None, max_length=200)
    default_delivery_country: Optional[str] = Field(default=None, max_length=120)
    price_sensitivity: Optional[str] = Field(default=None, max_length=80)
    time_sensitivity: Optional[str] = Field(default=None, max_length=80)
    pricing_policy: Optional[PricingFormula] = None
    supplier_reminder_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    customer_deadline_update_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    operational_notes: list[str] = Field(default_factory=list)


class CustomerMasterUpdateRequest(BaseModel):
    customer_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    aliases: list[str] = Field(default_factory=list)
    trusted_sender_addresses: list[str] = Field(default_factory=list)
    trusted_sender_domains: list[str] = Field(default_factory=list)
    contacts: list[MasterContact] = Field(default_factory=list)
    sales_owner: Optional[str] = Field(default=None, max_length=200)
    default_commodity: Optional[str] = Field(default=None, max_length=300)
    default_equipment_type: Optional[str] = Field(default=None, max_length=300)
    default_pickup_city: Optional[str] = Field(default=None, max_length=200)
    default_pickup_area: Optional[str] = Field(default=None, max_length=300)
    default_pickup_country: Optional[str] = Field(default=None, max_length=120)
    default_delivery_city: Optional[str] = Field(default=None, max_length=200)
    default_delivery_country: Optional[str] = Field(default=None, max_length=120)
    price_sensitivity: Optional[str] = Field(default=None, max_length=80)
    time_sensitivity: Optional[str] = Field(default=None, max_length=80)
    pricing_policy: Optional[PricingFormula] = None
    supplier_reminder_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    customer_deadline_update_mode: Optional[Literal["manual", "approval_required", "automatic"]] = None
    operational_notes: list[str] = Field(default_factory=list)


class SupplierMasterCreateRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    role: Literal["primary", "backup", "specialist"] = "backup"
    contacts: list[MasterContact] = Field(default_factory=list)
    geographies: list[SupplierGeographyCapability] = Field(default_factory=list)
    service_types: list[str] = Field(default_factory=list)
    equipment_types: list[str] = Field(default_factory=list)
    special_capabilities: list[str] = Field(default_factory=list)
    priority_routes: list[str] = Field(default_factory=list)
    legacy_region_tags: list[str] = Field(default_factory=list)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    price_score: float = Field(default=0.5, ge=0, le=1)
    speed_score: float = Field(default=0.5, ge=0, le=1)
    notes: str = Field(default="Master supplier profile.", min_length=1, max_length=2000)


class SupplierMasterUpdateRequest(BaseModel):
    supplier_name: str = Field(min_length=1, max_length=240)
    active: bool = True
    role: Literal["primary", "backup", "specialist"] = "backup"
    contacts: list[MasterContact] = Field(default_factory=list)
    geographies: list[SupplierGeographyCapability] = Field(default_factory=list)
    service_types: list[str] = Field(default_factory=list)
    equipment_types: list[str] = Field(default_factory=list)
    special_capabilities: list[str] = Field(default_factory=list)
    priority_routes: list[str] = Field(default_factory=list)
    legacy_region_tags: list[str] = Field(default_factory=list)
    reliability_score: float = Field(default=0.5, ge=0, le=1)
    price_score: float = Field(default=0.5, ge=0, le=1)
    speed_score: float = Field(default=0.5, ge=0, le=1)
    notes: str = Field(default="Master supplier profile.", min_length=1, max_length=2000)


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

@app.get("/master-data/customers")
def list_customer_master_profiles():
    return {
        "customers": [item.model_dump() for item in master_data_repository.list_customers()]
    }


@app.post("/master-data/customers")
def create_customer_master_profile(
    request: CustomerMasterCreateRequest, http_request: Request,
):
    try:
        profile = create_customer_master(
            repository=master_data_repository,
            updated_by=_authenticated_operator(http_request),
            source="manual",
            **request.model_dump(),
        )
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile.model_dump()


@app.get("/master-data/customers/{customer_id}")
def get_customer_master_profile(customer_id: str):
    profile = master_data_repository.get_customer(customer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Customer master not found: {customer_id}")
    return profile.model_dump()


@app.post("/master-data/customers/{customer_id}")
def update_customer_master_profile(
    customer_id: str, request: CustomerMasterUpdateRequest, http_request: Request,
):
    try:
        profile = update_customer_master(
            repository=master_data_repository, customer_id=customer_id,
            updated_by=_authenticated_operator(http_request), **request.model_dump(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Customer master not found: {customer_id}") from exc
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile.model_dump()


@app.get("/master-data/suppliers")
def list_supplier_master_profiles():
    return {
        "suppliers": [item.model_dump() for item in master_data_repository.list_suppliers()]
    }


@app.post("/master-data/suppliers")
def create_supplier_master_profile(
    request: SupplierMasterCreateRequest, http_request: Request,
):
    try:
        profile = create_supplier_master(
            repository=master_data_repository,
            updated_by=_authenticated_operator(http_request),
            source="manual",
            **request.model_dump(),
        )
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile.model_dump()


@app.get("/master-data/suppliers/{supplier_id}")
def get_supplier_master_profile(supplier_id: str):
    profile = master_data_repository.get_supplier(supplier_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Supplier master not found: {supplier_id}")
    return profile.model_dump()


@app.post("/master-data/suppliers/{supplier_id}")
def update_supplier_master_profile(
    supplier_id: str, request: SupplierMasterUpdateRequest, http_request: Request,
):
    try:
        profile = update_supplier_master(
            repository=master_data_repository, supplier_id=supplier_id,
            updated_by=_authenticated_operator(http_request), **request.model_dump(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Supplier master not found: {supplier_id}") from exc
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return profile.model_dump()


@app.get("/master-data/suppliers/{supplier_id}/geography")
def get_supplier_master_geography(supplier_id: str, destination_country: str):
    profile = master_data_repository.get_supplier(supplier_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Supplier master not found: {supplier_id}")
    return supplier_geography_view(profile, destination_country)


@app.post("/master-data/bootstrap/legacy")
def bootstrap_master_data_from_legacy(http_request: Request):
    customer_validation = validate_customer_memory_file(
        operational_data_sources.customer_memory_path
    )
    supplier_validation = validate_supplier_capabilities_file(
        operational_data_sources.supplier_capabilities_path
    )
    if not customer_validation.get("valid") or not supplier_validation.get("valid"):
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "legacy_master_data_validation_failed",
                "customer_errors": customer_validation.get("errors") or [],
                "supplier_errors": supplier_validation.get("errors") or [],
            },
        )
    customer_raw = json.loads(
        operational_data_sources.customer_memory_path.read_text(encoding="utf-8")
    )
    supplier_raw = json.loads(
        operational_data_sources.supplier_capabilities_path.read_text(encoding="utf-8")
    )
    try:
        return bootstrap_legacy_master_data(
            repository=master_data_repository,
            customer_profiles=[CustomerMemoryProfile.model_validate(item) for item in customer_raw],
            supplier_profiles=supplier_raw,
            updated_by=_authenticated_operator(http_request),
        )
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/automation-policy/agency")
def get_agency_automation_policy():
    policy = agency_automation_policy_repository.get()
    legacy = resolve_supplier_dispatch_policy()
    return {
        "policy": None if policy is None else policy.model_dump(),
        "legacy_fallback": {
            "supplier_reminder_mode": (
                "automatic" if legacy.automatic_supplier_reminders_enabled else "manual"
            ),
            "customer_deadline_update_mode": (
                "automatic" if legacy.automatic_customer_deadline_updates_enabled else "manual"
            ),
        },
    }


@app.post("/automation-policy/agency")
def update_agency_automation_policy(
    request: AgencyAutomationPolicyRequest, http_request: Request,
):
    current = agency_automation_policy_repository.get()
    supplier_mode = (
        request.supplier_reminder_mode
        if "supplier_reminder_mode" in request.model_fields_set
        else (None if current is None else current.supplier_reminder_mode)
    )
    customer_mode = (
        request.customer_deadline_update_mode
        if "customer_deadline_update_mode" in request.model_fields_set
        else (None if current is None else current.customer_deadline_update_mode)
    )
    try:
        policy = save_agency_automation_policy(
            repository=agency_automation_policy_repository,
            updated_by=_authenticated_operator(http_request),
            supplier_reminder_mode=supplier_mode,
            customer_deadline_update_mode=customer_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return policy.model_dump()


@app.post("/master-data/customers/{customer_id}/automation-policy")
def update_customer_automation_policy(
    customer_id: str, request: CustomerAutomationPolicyRequest, http_request: Request,
):
    current = master_data_repository.get_customer(customer_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"Customer master not found: {customer_id}")
    try:
        updated = update_customer_master(
            repository=master_data_repository,
            customer_id=customer_id,
            updated_by=_authenticated_operator(http_request),
            supplier_reminder_mode=(
                request.supplier_reminder_mode
                if "supplier_reminder_mode" in request.model_fields_set
                else current.supplier_reminder_mode
            ),
            customer_deadline_update_mode=(
                request.customer_deadline_update_mode
                if "customer_deadline_update_mode" in request.model_fields_set
                else current.customer_deadline_update_mode
            ),
        )
    except MasterDataConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "customer_id": updated.customer_id,
        "customer_name": updated.customer_name,
        "supplier_reminder_mode": updated.supplier_reminder_mode,
        "customer_deadline_update_mode": updated.customer_deadline_update_mode,
    }


@app.get("/mina-jobs/{job_id}/automation-policy")
def get_mina_job_automation_policy(job_id: str):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    workflow = (
        supplier_rfq_repository.get_workflow(job.supplier_rfq_workflow_id)
        if job.supplier_rfq_workflow_id else None
    )
    dispatch = workflow.dispatch_policy if workflow is not None else resolve_supplier_dispatch_policy()
    supplier_policy = resolve_effective_automation_policy(
        action="supplier_reminder",
        legacy_dispatch_enabled=dispatch.automatic_supplier_reminders_enabled,
        mina_job_repository=mina_job_repository, job_id=job_id,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_automation_policy_repository,
    )
    customer_policy = resolve_effective_automation_policy(
        action="customer_deadline_update",
        legacy_dispatch_enabled=dispatch.automatic_customer_deadline_updates_enabled,
        mina_job_repository=mina_job_repository, job_id=job_id,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_automation_policy_repository,
    )
    return {
        "job_id": job.job_id,
        "mina_code": job.mina_code,
        "supplier_reminder": supplier_policy.model_dump(),
        "customer_deadline_update": customer_policy.model_dump(),
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


@app.get("/mina-jobs")
def list_mina_jobs():
    return build_mina_job_list(mina_job_repository)


@app.post("/mina-jobs/manual")
def create_manual_job(request: MinaJobManualCreateRequest, http_request: Request):
    try:
        job = create_manual_mina_job(
            repository=mina_job_repository,
            manual_intake_id=request.manual_intake_id,
            intake_channel=request.intake_channel,
            job_kind=request.job_kind,
            shipment=request.shipment,
            opened_by=_authenticated_operator(http_request),
            sales_owner=request.sales_owner,
            operations_owner=request.operations_owner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job.model_dump()


@app.post("/supplier-fixed-rates")
def create_fixed_rate(request: SupplierFixedRateCreateRequest, http_request: Request):
    try:
        rate = create_supplier_fixed_rate(
            repository=supplier_price_repository,
            recorded_by=_authenticated_operator(http_request),
            **request.model_dump(),
        )
    except SupplierPriceIdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return rate.model_dump()


@app.get("/supplier-fixed-rates")
def list_fixed_rates():
    return {
        "fixed_rates": [item.model_dump() for item in supplier_price_repository.list_fixed_rates()]
    }


@app.post("/supplier-fixed-rates/{rate_id}/status")
def update_fixed_rate_status(
    rate_id: str, request: SupplierFixedRateStatusRequest, http_request: Request,
):
    try:
        rate = set_supplier_fixed_rate_active(
            repository=supplier_price_repository, rate_id=rate_id, active=request.active,
            updated_by=_authenticated_operator(http_request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return rate.model_dump()


@app.get("/mina-jobs/{job_id}/supplier-prices")
def get_mina_job_supplier_prices(job_id: str):
    try:
        return build_job_supplier_price_view(
            price_repository=supplier_price_repository,
            mina_repository=mina_job_repository,
            supplier_repository=supplier_rfq_repository,
            job_id=job_id,
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/mina-jobs/{job_id}/supplier-prices/manual")
def create_mina_job_supplier_price(
    job_id: str, request: SupplierDirectPriceCreateRequest, http_request: Request,
):
    try:
        offer = create_direct_supplier_price_offer(
            price_repository=supplier_price_repository,
            mina_repository=mina_job_repository,
            job_id=job_id, recorded_by=_authenticated_operator(http_request),
            **request.model_dump(),
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinaJobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupplierPriceIdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return offer.model_dump()


@app.post("/mina-jobs/{job_id}/supplier-prices/fixed-rate/{rate_id}")
def use_mina_job_fixed_rate(
    job_id: str, rate_id: str, request: SupplierFixedRateUseRequest, http_request: Request,
):
    try:
        offer = use_fixed_rate_for_job(
            price_repository=supplier_price_repository,
            mina_repository=mina_job_repository,
            job_id=job_id, rate_id=rate_id, entry_id=request.entry_id,
            recorded_by=_authenticated_operator(http_request),
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinaJobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupplierPriceIdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return offer.model_dump()


@app.get("/mina-jobs/{job_id}")
def get_mina_job(job_id: str):
    try:
        return build_mina_job_detail(
            repository=mina_job_repository,
            supplier_repository=supplier_rfq_repository,
            quote_case_repository=quote_case_repository,
            action_repository=automation_action_repository,
            price_repository=supplier_price_repository,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_automation_policy_repository,
            job_id=job_id,
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/mina-jobs/{job_id}/automation-overrides")
def update_mina_job_automation_overrides(
    job_id: str, request: MinaJobAutomationOverrideRequest,
    http_request: Request,
):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    try:
        updated = set_mina_job_automation_overrides(
            repository=mina_job_repository,
            mina_code=job.mina_code,
            actor=_authenticated_operator(http_request),
            disable_supplier_reminders=(
                request.disable_supplier_reminders
                if "disable_supplier_reminders" in request.model_fields_set
                else job.automation_overrides.disable_supplier_reminders
            ),
            disable_customer_deadline_updates=(
                request.disable_customer_deadline_updates
                if "disable_customer_deadline_updates" in request.model_fields_set
                else job.automation_overrides.disable_customer_deadline_updates
            ),
            supplier_reminder_mode=(
                request.supplier_reminder_mode
                if "supplier_reminder_mode" in request.model_fields_set
                else job.automation_overrides.supplier_reminder_mode
            ),
            customer_deadline_update_mode=(
                request.customer_deadline_update_mode
                if "customer_deadline_update_mode" in request.model_fields_set
                else job.automation_overrides.customer_deadline_update_mode
            ),
        )
    except MinaJobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return updated.model_dump()


@app.post("/mina-jobs/{job_id}/owners")
def update_mina_job_owners(
    job_id: str, request: MinaJobOwnersRequest, http_request: Request,
):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    try:
        updated = set_mina_job_owners(
            repository=mina_job_repository,
            mina_code=job.mina_code,
            actor=_authenticated_operator(http_request),
            sales_owner=request.sales_owner,
            operations_owner=request.operations_owner,
        )
    except MinaJobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return updated.model_dump()


@app.post("/mina-jobs/{job_id}/stage")
def update_mina_job_stage(
    job_id: str, request: MinaJobStageTransitionRequest,
    http_request: Request,
):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    try:
        updated = transition_mina_job_stage(
            repository=mina_job_repository,
            mina_code=job.mina_code,
            target_stage=request.target_stage,
            actor=_authenticated_operator(http_request),
            reason=request.reason,
        )
    except MinaJobTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return updated.model_dump()


@app.get("/mina-jobs/{job_id}/supplier-rfqs/{rfq_id}/reminder-preview")
def preview_mina_job_supplier_reminder(job_id: str, rfq_id: str):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    try:
        return preview_supplier_reminder_now(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_rfq_repository,
            action_repository=automation_action_repository,
            mina_code=job.mina_code,
            rfq_id=rfq_id,
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinaJobActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/mina-jobs/{job_id}/supplier-rfqs/{rfq_id}/reminder-now")
def send_mina_job_supplier_reminder_now(
    job_id: str, rfq_id: str, http_request: Request,
):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"MINA job not found: {job_id}")
    try:
        result = send_supplier_reminder_now(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_rfq_repository,
            action_repository=automation_action_repository,
            sender=outbound_mail_sender,
            mina_code=job.mina_code,
            rfq_id=rfq_id,
            actor=_authenticated_operator(http_request),
        )
    except MinaJobNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MinaJobActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return serialize_result(result)


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
            mina_job_repository=mina_job_repository,
        )
    except CustomerQuoteManualSentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerQuoteManualSentTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return result.model_dump()


@app.post("/quote-cases/{case_id}/send")
def send_quote_case_endpoint(
    case_id: str,
    request: QuoteCaseAutomatedSendRequest,
):
    try:
        result = send_customer_quote_and_record(
            quote_case_repository=quote_case_repository,
            approval_repository=quote_approval_repository,
            case_id=case_id,
            expected_approval_id=request.expected_approval_id,
            recipient_email=request.recipient_email,
            sender=outbound_mail_sender,
            mina_job_repository=mina_job_repository,
        )
    except CustomerQuoteAutomatedSentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CustomerQuoteAutomatedSentTransitionError as exc:
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
            mina_job_repository=mina_job_repository,
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
            quote_case_repository=quote_case_repository,
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
            quote_case_repository=quote_case_repository,
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
            quote_case_repository=quote_case_repository,
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
                attachment_review_repository=(
                    attachment_review_repository
                ),
                interpret_attachments=(
                    request.interpret_attachments
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


@app.get("/attachment-review-queue")
def list_attachment_review_queue():
    return build_attachment_review_queue(
        repository=attachment_review_repository,
        supplier_repository=supplier_rfq_repository,
    )


@app.get("/operational-work-queue")
def list_operational_work_queue():
    queue = build_operational_work_queue(
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )
    return decorate_operational_work_queue(
        queue, operational_work_assignment_repository
    )


@app.get("/operational-work-my")
def list_my_operational_work(http_request: Request):
    return build_my_operational_work_view(
        operator_name=_authenticated_operator(http_request),
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.get("/operational-work-shift-summary")
def get_operational_work_shift_summary(http_request: Request):
    return build_operational_shift_summary(
        operator_name=_authenticated_operator(http_request),
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.get("/operational-work-shift-close-readiness")
def get_operational_work_shift_close_readiness(http_request: Request):
    return build_operational_shift_close_readiness(
        operator_name=_authenticated_operator(http_request),
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.get("/operational-work-shift-open-reconciliation")
def get_operational_work_shift_open_reconciliation(http_request: Request):
    return build_operational_shift_open_reconciliation(
        operator_name=_authenticated_operator(http_request),
        receipt_repository=operational_shift_close_receipt_repository,
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.get("/operational-work-shift-continuity")
def get_operational_work_shift_continuity(http_request: Request):
    _authenticated_operator(http_request)
    return build_operational_shift_continuity_ledger(
        receipt_repository=operational_shift_close_receipt_repository,
        acceptance_repository=operational_shift_open_acceptance_repository,
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.post("/operational-work-shift-open-accept")
def accept_operational_work_shift_open(http_request: Request):
    try:
        return attest_operational_shift_open_acceptance(
            operator_name=_authenticated_operator(http_request),
            acceptance_repository=operational_shift_open_acceptance_repository,
            receipt_repository=operational_shift_close_receipt_repository,
            assignment_repository=operational_work_assignment_repository,
            attachment_repository=attachment_review_repository,
            proposal_repository=extraction_proposal_repository,
            supplier_repository=supplier_rfq_repository,
            approval_repository=quote_approval_repository,
            quote_case_repository=quote_case_repository,
        )
    except OperationalShiftOpenAcceptanceBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/operational-work-shift-open-acceptances")
def get_operational_work_shift_open_acceptances(http_request: Request):
    return list_operational_shift_open_acceptances(
        operator_name=_authenticated_operator(http_request),
        acceptance_repository=operational_shift_open_acceptance_repository,
        receipt_repository=operational_shift_close_receipt_repository,
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.post("/operational-work-shift-close-attest")
def attest_operational_work_shift_close(http_request: Request):
    try:
        return attest_operational_shift_close(
            operator_name=_authenticated_operator(http_request),
            receipt_repository=operational_shift_close_receipt_repository,
            assignment_repository=operational_work_assignment_repository,
            attachment_repository=attachment_review_repository,
            proposal_repository=extraction_proposal_repository,
            supplier_repository=supplier_rfq_repository,
            approval_repository=quote_approval_repository,
            quote_case_repository=quote_case_repository,
        )
    except OperationalShiftCloseAttestationBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/operational-work-shift-close-receipts")
def get_operational_work_shift_close_receipts(http_request: Request):
    return list_operational_shift_close_receipts(
        operator_name=_authenticated_operator(http_request),
        receipt_repository=operational_shift_close_receipt_repository,
        assignment_repository=operational_work_assignment_repository,
        attachment_repository=attachment_review_repository,
        proposal_repository=extraction_proposal_repository,
        supplier_repository=supplier_rfq_repository,
        approval_repository=quote_approval_repository,
        quote_case_repository=quote_case_repository,
    )


@app.get("/operational-work-items/{work_id}")
def get_operational_work_item(work_id: str):
    try:
        return build_operational_work_item_detail(
            work_id=work_id,
            attachment_repository=attachment_review_repository,
            proposal_repository=extraction_proposal_repository,
            supplier_repository=supplier_rfq_repository,
            approval_repository=quote_approval_repository,
            quote_case_repository=quote_case_repository,
            assignment_repository=operational_work_assignment_repository,
        )
    except OperationalWorkItemNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _work_assignment_args(work_id: str) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "assignment_repository": operational_work_assignment_repository,
        "attachment_repository": attachment_review_repository,
        "proposal_repository": extraction_proposal_repository,
        "supplier_repository": supplier_rfq_repository,
        "approval_repository": quote_approval_repository,
        "quote_case_repository": quote_case_repository,
    }


def _assignment_error(exc: Exception):
    if isinstance(exc, OperationalWorkAssignmentNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, (OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@app.post("/operational-work-items/{work_id}/assign-to-me")
def assign_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = assign_operational_work_to_me(
            operator_name=_authenticated_operator(http_request),
            **_work_assignment_args(work_id),
        )
    except (OperationalWorkAssignmentNotFoundError, OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.post("/operational-work-items/{work_id}/acknowledge")
def acknowledge_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = acknowledge_operational_work(
            operator_name=_authenticated_operator(http_request),
            **_work_assignment_args(work_id),
        )
    except (OperationalWorkAssignmentNotFoundError, OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.post("/operational-work-items/{work_id}/renew")
def renew_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = renew_operational_work_assignment(
            operator_name=_authenticated_operator(http_request),
            **_work_assignment_args(work_id),
        )
    except (OperationalWorkAssignmentNotFoundError, OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.post("/operational-work-items/{work_id}/takeover")
def takeover_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = takeover_operational_work_assignment(
            operator_name=_authenticated_operator(http_request),
            **_work_assignment_args(work_id),
        )
    except (OperationalWorkAssignmentNotFoundError, OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.post("/operational-work-items/{work_id}/handoff")
def handoff_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = handoff_operational_work(
            operator_name=_authenticated_operator(http_request),
            **_work_assignment_args(work_id),
        )
    except (
        OperationalWorkAssignmentNotFoundError,
        OperationalWorkAssignmentConflictError,
        OperationalWorkAssignmentTransitionError,
    ) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.post("/operational-work-items/{work_id}/release")
def release_operational_work_endpoint(work_id: str, http_request: Request):
    try:
        result = release_operational_work(
            work_id=work_id,
            operator_name=_authenticated_operator(http_request),
            assignment_repository=operational_work_assignment_repository,
        )
    except (OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError) as exc:
        _assignment_error(exc)
    return result.model_dump(exclude={"work_state_sha256"})


@app.get("/attachment-reviews")
def list_attachment_reviews():
    return {
        "reviews": [
            attachment_review_public_payload(review, include_candidate=False)
            for review in attachment_review_repository.list_all()
        ]
    }


@app.get("/attachment-reviews/{review_id}")
def get_attachment_review(review_id: str):
    review = attachment_review_repository.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Attachment review not found: {review_id}")
    payload = attachment_review_public_payload(review, include_candidate=True)
    payload["field_review"] = build_attachment_review_preview(review, {})
    return payload


@app.post("/attachment-reviews/{review_id}/preview")
def preview_attachment_review_endpoint(
    review_id: str, request: PreviewAttachmentReviewRequest
):
    review = attachment_review_repository.get(review_id)
    if review is None:
        raise HTTPException(status_code=404, detail=f"Attachment review not found: {review_id}")
    return build_attachment_review_preview(review, request.corrections)


@app.post("/attachment-reviews/{review_id}/apply")
def apply_attachment_review_endpoint(
    review_id: str,
    request: ApplyAttachmentReviewRequest,
    http_request: Request = None,
):
    try:
        current_review = attachment_review_repository.get(review_id)
        if current_review is None:
            raise AttachmentReviewNotFoundError(
                f"Attachment interpretation review not found: {review_id}"
            )
        require_matching_attachment_review_preview(
            current_review,
            corrections=request.corrections,
            preview_token=request.preview_token,
        )
        review = apply_attachment_interpretation_review(
            repository=attachment_review_repository,
            review_id=review_id,
            operator_identity=_authenticated_operator(http_request, request.operator_identity),
            corrections=request.corrections,
            proposal_repository=extraction_proposal_repository,
            supplier_repository=supplier_rfq_repository,
        )
    except AttachmentReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (AttachmentReviewTransitionError, AttachmentReviewConflictError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return attachment_review_public_payload(review, include_candidate=True)


@app.post("/attachment-reviews/{review_id}/reject")
def reject_attachment_review_endpoint(
    review_id: str,
    request: RejectAttachmentReviewRequest,
    http_request: Request = None,
):
    try:
        review = reject_attachment_interpretation_review(
            repository=attachment_review_repository,
            review_id=review_id,
            operator_identity=_authenticated_operator(http_request, request.operator_identity),
            rejection_reason=request.rejection_reason,
        )
    except AttachmentReviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AttachmentReviewTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return attachment_review_public_payload(review, include_candidate=True)


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
            mina_job_repository=mina_job_repository,
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
            mina_job_repository=mina_job_repository,
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
        "automated_sent_evidence": [
            evidence.model_dump()
            for evidence in supplier_rfq_repository.list_automated_sent_evidence(rfq_id)
        ],
        "manual_sent_evidence": [
            evidence.model_dump()
            for evidence in supplier_rfq_repository.list_manual_sent_evidence(rfq_id)
        ],
        "acknowledgements": [
            {
                "acknowledged_at": evidence.acknowledged_at,
                "channel": evidence.channel,
            }
            for evidence in supplier_rfq_repository.list_acknowledgements(rfq_id)
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
                "automated_sent_evidence": [
                    evidence.model_dump()
                    for evidence in (
                        supplier_rfq_repository
                        .list_follow_up_automated_sent_evidence(item.follow_up_id)
                    )
                ],
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
        "automated_sent_evidence": [
            evidence.model_dump()
            for evidence in (
                supplier_rfq_repository
                .list_follow_up_automated_sent_evidence(follow_up_id)
            )
        ],
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


@app.post("/supplier-rfq-follow-ups/{follow_up_id}/send")
def send_supplier_rfq_follow_up_endpoint(follow_up_id: str):
    try:
        result = send_supplier_rfq_follow_up_via_mail(
            repository=supplier_rfq_repository,
            follow_up_id=follow_up_id,
            sender=outbound_mail_sender,
            enforce_business_hours=True,
        )
    except SupplierRFQFollowUpNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result.delivery.status == "rejected_before_provider":
        raise HTTPException(status_code=409, detail=result.delivery.reason)
    if result.delivery.status != "sent":
        raise HTTPException(status_code=503, detail=result.delivery.reason)
    return result.model_dump()


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


@app.post("/supplier-rfqs/{rfq_id}/acknowledge-seen")
def record_supplier_rfq_seen(
    rfq_id: str,
    request: SupplierRFQAcknowledgementRequest,
    http_request: Request = None,
):
    try:
        return record_supplier_acknowledgement(
            repository=supplier_rfq_repository,
            rfq_id=rfq_id,
            channel=request.channel,
            recorded_by=_authenticated_operator(http_request),
        )
    except SupplierAcknowledgementError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/supplier-rfq-workflows/{workflow_id}/dispatch-status")
def get_supplier_rfq_dispatch_status(workflow_id: str):
    try:
        return build_supplier_dispatch_status(
            repository=supplier_rfq_repository,
            workflow_id=workflow_id,
            action_repository=automation_action_repository,
        )
    except SupplierSecondaryDispatchBlockedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/supplier-rfq-workflows/{workflow_id}/authorize-secondary-after-negotiation")
def authorize_supplier_secondary_dispatch(
    workflow_id: str,
    http_request: Request = None,
):
    try:
        return authorize_secondary_after_price_negotiation(
            repository=supplier_rfq_repository,
            workflow_id=workflow_id,
            authorized_by=_authenticated_operator(http_request),
        )
    except SupplierSecondaryDispatchBlockedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
        result = send_supplier_rfq_via_mail(
            repository=supplier_rfq_repository,
            rfq_id=rfq_id,
            sender=outbound_mail_sender,
            enforce_business_hours=True,
        )
        if result.delivery.status == "rejected_before_provider":
            raise HTTPException(
                status_code=409,
                detail=result.delivery.reason,
            )
        if result.delivery.status != "sent":
            raise HTTPException(
                status_code=503,
                detail=result.delivery.reason,
            )
        return result.model_dump()
    except SupplierRFQNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupplierRFQTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
            mina_job_repository=mina_job_repository,
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
