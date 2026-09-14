from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope
from src.core.master_data import MasterContact, SupplierGeographyCapability
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import (
    create_customer_master,
    create_supplier_master,
    update_customer_master,
)
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.models import Package, Shipment
from src.core.pricing_policy import PricingFormula
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.extraction_confirmation import (
    ExtractionCorrectionError,
    confirm_extraction_proposal,
)
from src.workflow.outlook_inbound_ingestion import process_controlled_outlook_customer_mail
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


def _shipment(customer_name: str = "Customer A") -> Shipment:
    return Shipment(
        customer_name=customer_name,
        pickup_country="Türkiye", pickup_city="Adana",
        delivery_country="Almanya", delivery_city="Hamburg", delivery_postcode="20095",
        commodity="Tekstil", gross_weight_kg=12000, service_type="FTL", transport_mode="road",
        cargo_ready_date="2026-09-15", is_adr=False,
        is_temperature_controlled=False, is_high_value=False,
        packages=[Package(package_type="pallet", quantity=12, length_cm=120,
                          width_cm=80, height_cm=150, weight_kg=1000)],
    )


def _masters() -> InMemoryMasterDataRepository:
    repo = InMemoryMasterDataRepository()
    for key, name, sender, margin in (
        ("a", "Customer A", "a@customer.invalid", 10),
        ("b", "Customer B", "b@customer.invalid", 20),
    ):
        create_customer_master(
            repository=repo, entry_id=key, customer_name=name,
            trusted_sender_addresses=[sender],
            pricing_policy=PricingFormula(method="cost_markup_percentage", value=margin),
            updated_by="Regression", created_at=NOW,
        )
    create_supplier_master(
        repository=repo, entry_id="supplier", supplier_name="Road Supplier", role="primary",
        contacts=[MasterContact(contact_name="Pricing", email="pricing@supplier.invalid",
                                roles=["pricing"], is_primary=True, active=True)],
        geographies=[SupplierGeographyCapability(scope_type="country", scope_name="Almanya",
                                                  strength="main_market", source="manual")],
        service_types=["FTL"], equipment_types=["Tenteli / Curtainsider"],
        priority_routes=["Türkiye-Almanya"], reliability_score=.9, price_score=.8,
        speed_score=.8, notes="Regression supplier.", updated_by="Regression", created_at=NOW,
    )
    return repo


def _mail() -> InboundMailEnvelope:
    return InboundMailEnvelope(
        external_message_id="identity-binding-1", provider_name="microsoft_graph",
        mailbox_id="ops@example.invalid", sender_address="a@customer.invalid",
        recipient_addresses=["ops@example.invalid"], subject="Adana Hamburg FTL",
        body_text="Adana Hamburg 12 palet 12000 kg tekstil.", received_at=NOW, source="email",
    )


def evaluate_customer_email_identity_binding_regressions() -> dict:
    failures: list[str] = []
    masters = _masters()
    proposals = InMemoryExtractionProposalRepository()
    intake = process_controlled_outlook_customer_mail(
        mail=_mail(),
        shipment_parser=lambda _: ShipmentProposalSnapshot.model_validate(_shipment().model_dump()),
        proposal_repository=proposals, operational_data_sources=None,
        master_data_repository=masters,
    )
    proposal = intake.get("extraction_proposal")
    if proposal is None or proposal.trusted_customer_name != "Customer A":
        failures.append("trusted Outlook customer identity was not durably bound to proposal")
    else:
        jobs = InMemoryMinaJobRepository()
        try:
            confirm_extraction_proposal(
                repository=proposals, proposal_id=proposal.proposal_id,
                operator_identity="Regression Operator",
                corrections={"customer_name": "Customer B"}, mina_job_repository=jobs,
            )
        except ExtractionCorrectionError:
            pass
        else:
            failures.append("confirmation changed a trusted Outlook customer identity")
        stored = proposals.get(proposal.proposal_id)
        if stored is None or stored.extraction_status != "proposed" or jobs.list_all():
            failures.append("rejected trusted-identity correction mutated proposal or created MINA job")

    wrong = process_shipment(
        shipment=_shipment("Customer B"), email_text="manual email",
        sender_address="a@customer.invalid", rfq_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(), master_data_repository=masters,
    )
    if (wrong.get("result_type") != "customer_identity_verification_required"
            or wrong.get("supplier_rfq_drafts") or wrong.get("supplier_rfq_workflow") is not None):
        failures.append("master-data email identity mismatch reached supplier RFQ authority")

    rfqs = InMemorySupplierRFQRepository()
    good = process_shipment(
        shipment=_shipment("Customer A"), email_text="trusted email",
        sender_address="a@customer.invalid", rfq_repository=rfqs,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(), master_data_repository=masters,
    )
    workflow = good.get("supplier_rfq_workflow")
    if good.get("result_type") != "supplier_rfq_approval_required" or workflow is None:
        failures.append("valid trusted customer identity no longer reaches RFQ approval")
    else:
        customer_a = next(x for x in masters.list_customers() if x.customer_name == "Customer A")
        update_customer_master(
            repository=masters, customer_id=customer_a.customer_id, updated_by="Regression",
            occurred_at=NOW, trusted_sender_addresses=["changed@customer.invalid"],
        )
        resumed = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id, rfq_repository=rfqs,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(), master_data_repository=masters,
        )
        if (resumed.get("result_type") != "customer_identity_verification_required"
                or resumed.get("quote_case") is not None
                or resumed["supplier_rfq_workflow"].quote_progression_status != "ready"):
            failures.append("customer trust drift did not block quote progression fail-closed")

    import src.api as api
    original = (api.master_data_repository, api.extraction_proposal_repository, api.parse_email_with_ai)
    parser_calls: list[str] = []
    try:
        api.master_data_repository = _masters()
        api.extraction_proposal_repository = InMemoryExtractionProposalRepository()
        api.parse_email_with_ai = lambda text: (parser_calls.append(str(text)) or ShipmentProposalSnapshot.model_validate(_shipment().model_dump()))
        with patch.dict("os.environ", {"MINAI_PILOT_MODE": "1"}, clear=False):
            for sender, expected in ((None, "pilot_manual_email_sender_required"),
                                     ("unknown@customer.invalid", "sender_not_in_verified_pilot_scope")):
                try:
                    api.process_email(api.ProcessEmailRequest(email_text="manual pilot email", sender_address=sender))
                except HTTPException as exc:
                    if exc.detail != expected:
                        failures.append(f"manual pilot email wrong rejection: {exc.detail}")
                else:
                    failures.append("manual pilot email bypassed sender trust before AI")
            if parser_calls:
                failures.append("rejected manual pilot email reached AI parser")
            accepted = api.process_email(api.ProcessEmailRequest(
                email_text="manual pilot email", sender_address="a@customer.invalid"
            ))
            bound = accepted.get("extraction_proposal") or {}
            if (accepted.get("result_type") != "extraction_confirmation_required"
                    or bound.get("trusted_customer_name") != "Customer A"
                    or len(parser_calls) != 1):
                failures.append("trusted manual pilot email did not bind customer identity before AI proposal")
    finally:
        api.master_data_repository, api.extraction_proposal_repository, api.parse_email_with_ai = original

    return {"name": "Customer email identity binding", "passed": not failures, "failures": failures}
