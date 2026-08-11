from __future__ import annotations

from datetime import datetime

from src.core.mail import MailSendResult
from src.core.models import Package, Shipment
from src.core.quote_approval_repository import (
    InMemoryQuoteApprovalRepository,
)
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_quote_comparison import (
    build_supplier_quote_comparisons,
)
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQNotFoundError,
    SupplierRFQTransitionError,
    approve_supplier_rfq,
    attach_supplier_rfq_response,
    send_supplier_rfq,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQResponseError,
    InMemorySupplierRFQRepository,
)
from src.simulation.supplier_simulator import (
    simulate_supplier_rfq_responses,
)
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import (
    resume_supplier_rfq_workflow,
)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Supplier RFQ Lifecycle Regression",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-09-10",
        is_adr=False,
        is_temperature_controlled=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )


def evaluate_supplier_rfq_lifecycle_regressions() -> dict:
    failures: list[str] = []
    rfq_repository = InMemorySupplierRFQRepository()
    approval_repository = InMemoryQuoteApprovalRepository()
    quote_case_repository = InMemoryQuoteCaseRepository()
    shipment = _shipment()

    initial = process_shipment(
        shipment=shipment,
        email_text=(
            "Adana'dan Hamburg'a 20 ton tekstil için komple tenteli "
            "araç fiyatı rica ederiz. Yük 10.09.2026 tarihinde hazırdır."
        ),
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )
    drafts = initial.get("supplier_rfq_drafts") or []
    if initial.get("result_type") != "supplier_rfq_approval_required":
        failures.append("main workflow should stop for RFQ approval")
    if not drafts or any(draft.status != "draft" for draft in drafts):
        failures.append("new supplier RFQs should remain draft")
    if initial.get("supplier_rfq_responses"):
        failures.append("main workflow must not fabricate supplier responses")
    if any(
        initial.get(key) is not None
        for key in (
            "supplier_quote",
            "customer_quote",
            "quote_draft",
            "quote_approval",
        )
    ):
        failures.append("pricing must not exist before supplier responses")

    if not drafts:
        return {
            "name": "Supplier RFQ operational lifecycle",
            "passed": False,
            "failures": failures,
        }

    draft = next(
        (item for item in drafts if item.recipient_email),
        drafts[0],
    )
    response = SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="quoted",
        cost=2200,
        currency="EUR",
        source="simulation",
    )
    try:
        attach_supplier_rfq_response(rfq_repository, response)
    except SupplierRFQTransitionError:
        pass
    else:
        failures.append("draft RFQ accepted a supplier response")

    unknown_response = response.model_copy(
        update={"rfq_id": "unknown-rfq-id"}
    )
    try:
        attach_supplier_rfq_response(rfq_repository, unknown_response)
    except SupplierRFQNotFoundError:
        pass
    else:
        failures.append("unknown RFQ response was not rejected")

    approved = approve_supplier_rfq(
        rfq_repository,
        draft.rfq_id,
        approved_by="Regression Operator",
    )
    if (
        approved.status != "approved"
        or approved.approved_by != "Regression Operator"
        or approved.approved_at is None
        or approved.sent_at is not None
    ):
        failures.append("RFQ approval metadata/state is incomplete")
    try:
        attach_supplier_rfq_response(rfq_repository, response)
    except SupplierRFQTransitionError:
        pass
    else:
        failures.append("approved but unsent RFQ accepted a response")

    if not approved.recipient_email:
        failures.append("regression supplier has no outbound recipient")
        return {
            "name": "Supplier RFQ operational lifecycle",
            "passed": False,
            "failures": failures,
        }

    confirmed_send = MailSendResult(
        operation_id=f"supplier-rfq:{draft.rfq_id}",
        status="sent",
        reason="Regression provider confirmed delivery.",
        provider_name="regression-provider",
        provider_message_id=f"message-{draft.rfq_id}",
        sent_at=datetime(2026, 8, 11, 10, 0, 0),
    )
    awaiting = send_supplier_rfq(
        rfq_repository,
        draft.rfq_id,
        confirmed_send,
    )
    if awaiting.status != "awaiting_response" or awaiting.sent_at is None:
        failures.append("approved RFQ did not enter awaiting_response")
    try:
        send_supplier_rfq(
            rfq_repository,
            draft.rfq_id,
            confirmed_send,
        )
    except SupplierRFQTransitionError:
        pass
    else:
        failures.append("duplicate RFQ send transition was accepted")

    unsent_simulation = simulate_supplier_rfq_responses(
        shipment=shipment,
        equipment_decision=initial["equipment_decision"],
        rfq_drafts=[item for item in drafts if item.rfq_id != draft.rfq_id],
    )
    if unsent_simulation:
        failures.append("simulator generated a response for unsent RFQ")
    simulated = simulate_supplier_rfq_responses(
        shipment=shipment,
        equipment_decision=initial["equipment_decision"],
        rfq_drafts=[awaiting],
    )
    if len(simulated) != 1:
        failures.append("sent RFQ did not produce one simulated response")
        return {
            "name": "Supplier RFQ operational lifecycle",
            "passed": False,
            "failures": failures,
        }
    responded = attach_supplier_rfq_response(
        rfq_repository,
        simulated[0],
    )
    if responded.status != "responded" or responded.responded_at is None:
        failures.append("validated response did not complete lifecycle")
    try:
        attach_supplier_rfq_response(rfq_repository, simulated[0])
    except DuplicateSupplierRFQResponseError:
        pass
    else:
        failures.append("duplicate supplier response was not rejected")

    unsent_draft = next(
        (item for item in drafts if item.rfq_id != draft.rfq_id),
        None,
    )
    responses_for_comparison = [simulated[0]]
    if unsent_draft is not None:
        responses_for_comparison.append(
            SupplierRFQResponse(
                rfq_id=unsent_draft.rfq_id,
                supplier_name=unsent_draft.supplier_name,
                rfq_priority=unsent_draft.priority,
                status="quoted",
                cost=1,
                currency="EUR",
                source="simulation",
            )
        )
    current_drafts = rfq_repository.list_drafts()
    comparisons = build_supplier_quote_comparisons(
        responses=responses_for_comparison,
        supplier_selection=initial["supplier_selection"],
        drafts=current_drafts,
    )
    if {item.rfq_id for item in comparisons} != {draft.rfq_id}:
        failures.append("comparison included a non-responded RFQ")

    workflow = initial["supplier_rfq_workflow"]
    resumed = resume_supplier_rfq_workflow(
        workflow_id=workflow.workflow_id,
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )
    if resumed.get("customer_quote") is None:
        failures.append("customer pricing did not resume after response")
    quote_approval = resumed.get("quote_approval")
    if quote_approval is None or quote_approval.approval_status != "pending":
        failures.append("commercial quote approval was not created as pending")
    if quote_approval and not approval_repository.get(
        quote_approval.approval_id
    ):
        failures.append("commercial quote approval was not persisted")

    return {
        "name": "Supplier RFQ operational lifecycle",
        "passed": not failures,
        "failures": failures,
    }
