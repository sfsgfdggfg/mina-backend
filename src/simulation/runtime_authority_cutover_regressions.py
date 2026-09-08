from __future__ import annotations

from datetime import datetime, timezone

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope, MailSendResult
from src.core.master_data import MasterContact, SupplierGeographyCapability
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_mina_job_for_confirmed_proposal, link_mina_job_workflow
from src.core.models import Package, Shipment
from src.core.pricing_policy import PricingFormula
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_price_repository import InMemorySupplierPriceRepository
from src.core.supplier_price_service import create_direct_supplier_price_offer
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import approve_supplier_rfq, attach_supplier_rfq_response, send_supplier_rfq
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.outlook_inbound_ingestion import process_controlled_outlook_customer_mail
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Pilot Customer Master",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-09-10",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[Package(
            package_type="pallet", quantity=20,
            length_cm=120, width_cm=80, height_cm=150, weight_kg=1000,
        )],
    )


def _master_data() -> InMemoryMasterDataRepository:
    repository = InMemoryMasterDataRepository()
    create_customer_master(
        repository=repository,
        entry_id="pilot-customer-master",
        customer_name="Pilot Customer Master",
        trusted_sender_addresses=["ops@pilot-customer.example"],
        pricing_policy=PricingFormula(method="cost_markup_percentage", value=10),
        updated_by="Pilot Operator",
        created_at=NOW,
    )
    create_supplier_master(
        repository=repository,
        entry_id="pilot-supplier-master",
        supplier_name="Pilot Road Supplier",
        role="primary",
        contacts=[MasterContact(
            contact_name="Pricing Desk", email="pricing@pilot-supplier.example",
            roles=["pricing"], is_primary=True, active=True,
        )],
        geographies=[SupplierGeographyCapability(
            scope_type="country", scope_name="Almanya", strength="main_market", source="manual",
        )],
        service_types=["FTL"],
        equipment_types=["Tenteli / Curtainsider"],
        priority_routes=["Türkiye-Almanya"],
        reliability_score=0.90,
        price_score=0.80,
        speed_score=0.85,
        notes="Pilot road supplier.",
        updated_by="Pilot Operator",
        created_at=NOW,
    )
    return repository


def _mail() -> InboundMailEnvelope:
    return InboundMailEnvelope(
        external_message_id="master-cutover-mail-1",
        provider_name="microsoft_graph",
        mailbox_id="operations@example.invalid",
        sender_address="ops@pilot-customer.example",
        sender_name="Pilot Customer",
        recipient_addresses=["operations@example.invalid"],
        subject="Adana Hamburg FTL",
        body_text="Adana'dan Hamburg'a 20 ton tekstil için fiyat rica ederiz.",
        received_at=NOW,
        source="email",
    )


def evaluate_runtime_authority_cutover_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    masters = _master_data()
    proposals = InMemoryExtractionProposalRepository()
    outlook = process_controlled_outlook_customer_mail(
        mail=_mail(),
        shipment_parser=lambda _safe: ShipmentProposalSnapshot.model_validate(_shipment().model_dump()),
        proposal_repository=proposals,
        operational_data_sources=None,
        master_data_repository=masters,
    )
    proposal = outlook.get("extraction_proposal")
    check(
        outlook.get("inbound_gate_status") == "pass"
        and proposal is not None
        and proposal.proposed_shipment.customer_name == "Pilot Customer Master",
        "controlled Outlook intake trusts durable Customer Master without legacy JSON",
    )

    jobs = InMemoryMinaJobRepository()
    rfqs = InMemorySupplierRFQRepository()
    approvals = InMemoryQuoteApprovalRepository()
    cases = InMemoryQuoteCaseRepository()
    prices = InMemorySupplierPriceRepository()
    shipment = _shipment()
    job = create_mina_job_for_confirmed_proposal(
        repository=jobs,
        proposal_id="master-cutover-proposal-1",
        shipment=shipment,
        opened_by="Pilot Operator",
        opened_at=NOW,
    )
    initial = process_shipment(
        shipment=shipment.model_copy(deep=True),
        email_text=_mail().body_text,
        sender_address=_mail().sender_address,
        customer_subject=_mail().subject,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        rfq_repository=rfqs,
        approval_repository=approvals,
        quote_case_repository=cases,
        master_data_repository=masters,
    )
    workflow = initial.get("supplier_rfq_workflow")
    drafts = initial.get("supplier_rfq_drafts") or []
    check(
        initial.get("customer_memory") is not None
        and initial["customer_memory"].source == "customer_master_projection"
        and initial.get("supplier_selection", {}).get("data_source") == "supplier_master_projection"
        and workflow is not None
        and len(drafts) == 1
        and drafts[0].supplier_name == "Pilot Road Supplier",
        "confirmed shipment uses Customer and Supplier Master as one runtime authority",
    )
    if workflow is None or not drafts:
        return {"name": "Runtime authority cutover", "passed": False, "failures": failures, "passes": passes}

    job = link_mina_job_workflow(
        repository=jobs,
        job_id=job.job_id,
        workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_approval_required",
        occurred_at=NOW,
    )
    draft = approve_supplier_rfq(
        rfqs, drafts[0].rfq_id, approved_by="Pilot Operator"
    )
    sent = send_supplier_rfq(
        rfqs,
        draft.rfq_id,
        MailSendResult(
            operation_id=f"supplier-rfq:{draft.rfq_id}",
            status="sent",
            reason="Regression provider confirmed delivery.",
            provider_name="regression-provider",
            provider_message_id=f"message-{draft.rfq_id}",
            sent_at=NOW,
        ),
    )
    attach_supplier_rfq_response(
        rfqs,
        SupplierRFQResponse(
            rfq_id=sent.rfq_id,
            supplier_name=sent.supplier_name,
            rfq_priority=sent.priority,
            status="quoted",
            cost=2400,
            currency="EUR",
            transit_time="4 days",
            equipment_type="Tenteli / Curtainsider",
            pricing_basis="all_in",
            source="email",
            received_at=NOW,
        ),
    )

    phone_offer = create_direct_supplier_price_offer(
        price_repository=prices,
        mina_repository=jobs,
        job_id=job.job_id,
        entry_id="phone-price-1",
        supplier_name="Pilot Road Supplier",
        source_type="phone",
        source_reference_id="operator-phone-call-1",
        cost=2200,
        currency="EUR",
        transit_time="4 days",
        equipment_type="Tenteli / Curtainsider",
        pricing_basis="all_in",
        recorded_by="Pilot Operator",
        recorded_at=NOW,
    )
    resumed = resume_supplier_rfq_workflow(
        workflow_id=workflow.workflow_id,
        rfq_repository=rfqs,
        approval_repository=approvals,
        quote_case_repository=cases,
        mina_job_repository=jobs,
        master_data_repository=masters,
        price_repository=prices,
    )
    decision = resumed.get("supplier_quote_selection_decision")
    supplier_quote = resumed.get("supplier_quote")
    customer_quote = resumed.get("customer_quote")
    quote_case = resumed.get("quote_case")
    check(
        decision is not None
        and decision.selected_price_offer_id == phone_offer.offer_id
        and decision.selected_price_source == "phone"
        and supplier_quote is not None
        and supplier_quote.price_source == "phone"
        and supplier_quote.cost == 2200
        and customer_quote is not None
        and customer_quote.final_price == 2420
        and quote_case is not None
        and quote_case.quote_approval is not None
        and quote_case.quote_approval.approval_status == "pending",
        "RFQ and phone prices share real quote progression and preserve source authority",
    )
    persisted_job = jobs.get(job.job_id)
    check(
        persisted_job is not None
        and persisted_job.quote_case_id == quote_case.case_id
        and persisted_job.stage == "quote_ready",
        "winning non-email supplier price reaches normal MINA quote approval lifecycle",
    )

    return {
        "name": "Runtime authority cutover",
        "passed": not failures,
        "failures": failures,
        "passes": passes,
    }
