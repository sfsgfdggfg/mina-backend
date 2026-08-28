from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
from src.core.models import EquipmentDecision, Package, Shipment
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.relative_dates import infer_supplier_vehicle_available_date
from src.core.supplier_rfq import SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_lifecycle import attach_supplier_rfq_response
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Synthetic Human Flow",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=20000,
        transport_mode="road",
        service_type="FTL",
        equipment_type="Tenteli / Curtainsider",
        cargo_ready_date="2026-09-10",
        required_delivery_date=None,
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[Package(
            package_type="pallet", quantity=20,
            length_cm=120, width_cm=80, height_cm=150,
        )],
    )


def _setup():
    shipment = _shipment()
    selection = select_suppliers_for_shipment(
        shipment=shipment,
        equipment_decision=EquipmentDecision(
            selected_equipment="Tenteli / Curtainsider",
            reason="Synthetic", confidence=1.0,
        ),
    )
    first = selection["selected_suppliers"][0]
    workflow = SupplierRFQWorkflow(shipment=shipment)
    draft = generate_supplier_rfq_drafts(
        workflow_id=workflow.workflow_id,
        shipment=shipment,
        equipment_decision=EquipmentDecision(
            selected_equipment="Tenteli / Curtainsider",
            reason="Synthetic", confidence=1.0,
        ),
        supplier_selection={**selection, "selected_suppliers": [first]},
    )[0].model_copy(update={
        "status": "awaiting_response",
        "sent_at": datetime(2026, 8, 28, 9, 0, 0),
    })
    repo = InMemorySupplierRFQRepository()
    repo.save_drafts([draft])
    repo.save_workflow(workflow.model_copy(update={"rfq_ids": [draft.rfq_id]}))
    return repo, workflow, draft, selection


def evaluate_human_operational_flow_regressions() -> dict:
    failures: list[str] = []

    # Relative supplier availability is evidence when explicitly stated.
    if infer_supplier_vehicle_available_date(
        "Aracımız hazırdır. Hemen yükleme yapabiliriz.",
        datetime.fromisoformat("2026-08-28T08:30:00+00:00"),
    ) != "2026-08-28":
        failures.append("supplier immediate availability did not resolve to message date")
    if infer_supplier_vehicle_available_date(
        "Aracımız hazır değil.",
        datetime.fromisoformat("2026-08-28T08:30:00+00:00"),
    ) is not None:
        failures.append("negative supplier availability inferred a date")

    # Terminal negative response prepares, but never sends, the next supplier RFQ.
    repo, workflow, draft, selection = _setup()
    attach_supplier_rfq_response(repo, SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="no_capacity",
        source="manual",
        received_at=datetime(2026, 8, 28, 9, 30, 0),
    ))
    approvals = InMemoryQuoteApprovalRepository()
    cases = InMemoryQuoteCaseRepository()
    with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False):
        fallback = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repo,
            approval_repository=approvals,
            quote_case_repository=cases,
        )
    drafts = [d for d in repo.list_drafts() if d.workflow_id == workflow.workflow_id]
    if (
        fallback.get("result_type") != "supplier_rfq_approval_required"
        or len(drafts) != 2
        or len({d.supplier_name for d in drafts}) != 2
        or sum(d.status == "draft" for d in drafts) != 1
        or len(repo.get_workflow(workflow.workflow_id).rfq_ids) != 2
    ):
        failures.append("terminal negative response did not prepare next supplier RFQ")

    # Incomplete quote reopens the same RFQ for clarification; final reply on the
    # same RFQ is accepted and can later progress to a customer quote case.
    repo, workflow, draft, selection = _setup()
    attach_supplier_rfq_response(repo, SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="quoted",
        cost=2400,
        currency="EUR",
        source="manual",
        received_at=datetime(2026, 8, 28, 10, 0, 0),
    ))
    approvals = InMemoryQuoteApprovalRepository()
    cases = InMemoryQuoteCaseRepository()
    with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False):
        clarification = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repo,
            approval_repository=approvals,
            quote_case_repository=cases,
        )
    reopened = repo.get_draft(draft.rfq_id)
    follow_up = clarification.get("supplier_follow_up_draft")
    if (
        clarification.get("result_type") != "supplier_response_required"
        or reopened is None
        or reopened.status != "clarification_required"
        or follow_up is None
        or draft.reference_token not in follow_up.body_text
        or "transit" not in follow_up.body_text.lower()
    ):
        failures.append("incomplete quote did not reopen same RFQ with follow-up draft")

    final = SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="quoted",
        cost=2400,
        currency="EUR",
        transit_time="4-5 gün",
        source="manual",
        received_at=datetime(2026, 8, 28, 10, 30, 0),
    )
    try:
        attach_supplier_rfq_response(repo, final)
    except Exception as exc:
        failures.append(f"clarified final response on same RFQ was rejected: {type(exc).__name__}")
    else:
        with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False):
            completed = resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=repo,
                approval_repository=approvals,
                quote_case_repository=cases,
            )
        if completed.get("quote_case") is None or completed.get("supplier_quote") is None:
            failures.append("clarified supplier response did not progress to quote case")

    # Indicative road requests can progress with route-level facts only and
    # remain explicitly non-binding through the customer quote draft.
    indicative_repo = InMemorySupplierRFQRepository()
    indicative = Shipment(
        customer_name="Indicative Customer",
        pickup_country="Türkiye",
        pickup_city=None,
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity=None,
        gross_weight_kg=None,
        quote_mode="indicative",
        transport_mode="road",
        service_type="FTL",
        cargo_ready_date=None,
        is_adr=None,
        is_temperature_controlled=None,
        is_high_value=None,
        packages=[],
    )
    with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False):
        initial_indicative = process_shipment(
            indicative, rfq_repository=indicative_repo
        )
    indicative_drafts = initial_indicative.get("supplier_rfq_drafts") or []
    if (
        initial_indicative.get("result_type") != "supplier_rfq_approval_required"
        or len(indicative_drafts) != 1
        or "İNDİKATİF" not in indicative_drafts[0].body
    ):
        failures.append("minimal indicative request did not reach RFQ approval")
    else:
        d = indicative_drafts[0].model_copy(update={
            "status": "awaiting_response",
            "sent_at": datetime(2026, 8, 28, 11, 0, 0),
        })
        indicative_repo.save_drafts([d])
        attach_supplier_rfq_response(indicative_repo, SupplierRFQResponse(
            rfq_id=d.rfq_id,
            supplier_name=d.supplier_name,
            rfq_priority=d.priority,
            status="quoted",
            cost=2200,
            currency="EUR",
            source="manual",
            received_at=datetime(2026, 8, 28, 11, 30, 0),
        ))
        indicative_approvals = InMemoryQuoteApprovalRepository()
        indicative_cases = InMemoryQuoteCaseRepository()
        with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False):
            indicative_done = resume_supplier_rfq_workflow(
                workflow_id=initial_indicative["supplier_rfq_workflow"].workflow_id,
                rfq_repository=indicative_repo,
                approval_repository=indicative_approvals,
                quote_case_repository=indicative_cases,
            )
        qdraft = indicative_done.get("quote_draft")
        if (
            indicative_done.get("quote_case") is None
            or qdraft is None
            or "İNDİKATİF / BAĞLAYICI DEĞİLDİR" not in qdraft.body
            or "yeniden teyit" not in qdraft.body
            or "Yükleme: Türkiye" not in qdraft.body
            or "Yükleme: -, Türkiye" in qdraft.body
            or "Transit Süre: Belirtilmedi" in qdraft.body
            or "Teklif Geçerliliği: Belirtilmedi" in qdraft.body
        ):
            failures.append("indicative supplier price did not produce clean non-binding quote case")

    return {
        "name": "Human operational flow",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_human_operational_flow_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
