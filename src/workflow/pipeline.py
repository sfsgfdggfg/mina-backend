from src.core.action_recommendation import generate_action_recommendation
from src.ai.clarification_generator import generate_clarification_draft
from src.ai.approval_generator import generate_management_review_draft
from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts

from src.core.customer_memory import enrich_shipment_with_customer_memory
from src.core.equipment import decide_equipment
from src.core.risk import assess_risk
from src.core.missing_info import check_missing_information
from src.core.road_rfq_readiness import apply_road_rfq_readiness
from src.core.supplier_selection import select_suppliers_for_shipment
from src.core.supplier_dispatch_policy import (
    SupplierDispatchPolicy,
    resolve_supplier_dispatch_policy,
)
from src.core.operational_consistency import check_operational_consistency
from src.core.quote_approval_repository import (
    QuoteApprovalRepository,
)
from src.core.quote_case_repository import (
    QuoteCaseRepository,
)
from src.core.commodity_profile import get_commodity_record
from src.core.quote_readiness import decide_quote_readiness
from src.core.regulatory_compliance import (
    assess_regulatory_compliance,
)
from src.core.supplier_rfq import SupplierRFQWorkflow
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
    SupplierRFQRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.data_provenance import (
    DataProvenanceError,
    SAFE_DATA_PROVENANCE_BLOCK_REASON,
)
from src.core.pilot_scope import evaluate_pilot_scope
from src.core.models import Shipment
from src.core.operational_data import OperationalDataSources


def build_data_provenance_blocked_result(
    shipment: Shipment,
    *,
    customer_memory=None,
    commodity_profile=None,
    missing_info=None,
    regulatory_compliance=None,
    equipment_decision=None,
    risk_assessment=None,
    pilot_scope=None,
    supplier_rfq_workflow=None,
    supplier_rfq_drafts=None,
    supplier_rfq_responses=None,
) -> dict:
    commodity_profile = (
        commodity_profile
        if commodity_profile is not None
        else get_commodity_record(shipment.commodity)
    )
    missing_info = missing_info or check_missing_information(shipment)
    regulatory_compliance = (
        regulatory_compliance or assess_regulatory_compliance(shipment)
    )
    equipment_decision = equipment_decision or decide_equipment(shipment)
    risk_assessment = risk_assessment or assess_risk(
        shipment=shipment,
        customer_memory=customer_memory,
    )
    pilot_scope = pilot_scope or evaluate_pilot_scope(shipment)
    supplier_selection = {
        "selected_suppliers": [],
        "rejected_suppliers": [],
        "selection_strategy": None,
        "source": "data_provenance_engine",
        "data_source": "operational_master_data",
        "provenance_status": "blocked",
        "provenance_reason": SAFE_DATA_PROVENANCE_BLOCK_REASON,
    }
    action_recommendation = generate_action_recommendation(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        missing_info=missing_info,
        result_type="data_provenance_blocked",
    )
    return {
        "shipment": shipment,
        "pilot_scope": pilot_scope,
        "customer_memory": customer_memory,
        "commodity_profile": commodity_profile,
        "missing_info": missing_info,
        "regulatory_compliance": regulatory_compliance,
        "equipment_decision": equipment_decision,
        "risk_assessment": risk_assessment,
        "supplier_selection": supplier_selection,
        "operational_consistency": None,
        "quote_readiness": None,
        "supplier_rfq_workflow": supplier_rfq_workflow,
        "supplier_rfq_drafts": supplier_rfq_drafts or [],
        "supplier_rfq_responses": supplier_rfq_responses or [],
        "valid_supplier_rfq_responses": [],
        "supplier_rfq_response_validation": None,
        "supplier_quote_comparisons": [],
        "supplier_quote_selection_decision": None,
        "supplier_quote": None,
        "customer_quote": None,
        "quote_draft": None,
        "quote_approval": None,
        "quote_send_safety": None,
        "quote_case": None,
        "clarification_draft": None,
        "management_review_draft": None,
        "action_recommendation": action_recommendation,
        "result_type": "data_provenance_blocked",
    }


def process_shipment(
    shipment: Shipment,
    email_text: str | None = None,
    sender_address: str | None = None,
    rfq_repository: SupplierRFQRepository | None = None,
    approval_repository: QuoteApprovalRepository | None = None,
    quote_case_repository: QuoteCaseRepository | None = None,
    _persist_rfq_transition: bool = True,
    operational_data_sources: OperationalDataSources | None = None,
    supplier_dispatch_policy: SupplierDispatchPolicy | None = None,
):
    if not isinstance(shipment, Shipment) or isinstance(
        shipment,
        ShipmentProposalSnapshot,
    ):
        raise TypeError(
            "Operational workflow requires a human-confirmed Shipment snapshot."
        )
    if rfq_repository is None:
        rfq_repository = InMemorySupplierRFQRepository()

    try:
        customer_memory = enrich_shipment_with_customer_memory(
            shipment=shipment,
            email_text=email_text,
            sender_address=sender_address,
            operational_data_sources=operational_data_sources,
        )
    except DataProvenanceError:
        return build_data_provenance_blocked_result(shipment)

    commodity_profile = get_commodity_record(shipment.commodity)
    missing_info = apply_road_rfq_readiness(
        shipment,
        check_missing_information(shipment),
    )
    regulatory_compliance = assess_regulatory_compliance(shipment)
    equipment_decision = decide_equipment(shipment)
    risk_assessment = assess_risk(
        shipment=shipment,
        customer_memory=customer_memory,
    )

    pilot_scope = evaluate_pilot_scope(shipment)
    if not pilot_scope.eligible:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="pilot_scope_excluded",
        )
        return {
            "shipment": shipment,
            "pilot_scope": pilot_scope,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "regulatory_compliance": regulatory_compliance,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": None,
            "operational_consistency": None,
            "quote_readiness": None,
            "supplier_rfq_workflow": None,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "valid_supplier_rfq_responses": [],
            "supplier_rfq_response_validation": None,
            "supplier_quote_comparisons": [],
            "supplier_quote_selection_decision": None,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "quote_approval": None,
            "quote_send_safety": None,
            "quote_case": None,
            "clarification_draft": None,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
            "result_type": "pilot_scope_excluded",
        }

    # 1. RED risk varsa önce yönetici onayına gider
    try:
        supplier_selection = select_suppliers_for_shipment(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            operational_data_sources=operational_data_sources,
        )
    except DataProvenanceError:
        return build_data_provenance_blocked_result(
            shipment,
            customer_memory=customer_memory,
            commodity_profile=commodity_profile,
            missing_info=missing_info,
            regulatory_compliance=regulatory_compliance,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            pilot_scope=pilot_scope,
        )

    operational_consistency = check_operational_consistency(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_selection=supplier_selection,
        supplier_quote=None,
        operational_data_sources=operational_data_sources,
    )

    quote_readiness = decide_quote_readiness(
        missing_info=missing_info,
        risk_assessment=risk_assessment,
        operational_consistency=operational_consistency,
        regulatory_compliance=regulatory_compliance,
    )

    if quote_readiness.result_type in {
        "blocked",
        "regulatory_blocked",
        "regulatory_review",
    }:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type=quote_readiness.result_type,
        )

        return {
            "shipment": shipment,
            "pilot_scope": pilot_scope,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "regulatory_compliance": regulatory_compliance,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "valid_supplier_rfq_responses": [],
            "supplier_rfq_response_validation": None,
            "supplier_quote_comparisons": [],
            "supplier_quote_selection_decision": None,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "quote_approval": None,
            "quote_send_safety": None,
            "quote_case": None,
            "clarification_draft": None,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
        }

    if quote_readiness.result_type == "management_review":
        management_review_draft = generate_management_review_draft(
            shipment=shipment,
            risk_assessment=risk_assessment,
        )
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="management_review",
        )
        

        return {
            "shipment": shipment,
            "pilot_scope": pilot_scope,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "regulatory_compliance": regulatory_compliance,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "valid_supplier_rfq_responses": [],
            "supplier_rfq_response_validation": None,
            "supplier_quote_comparisons": [],
            "supplier_quote_selection_decision": None,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "quote_approval": None,
            "quote_send_safety": None,
            "quote_case": None,
            "clarification_draft": None,
            "management_review_draft": management_review_draft,
            "action_recommendation": action_recommendation,
        }

    # 2. RED değilse kritik eksik bilgi kontrol edilir
    if quote_readiness.result_type == "clarification":
        clarification_draft = generate_clarification_draft(
            shipment=shipment,
            missing_info=missing_info,
        )
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="clarification",
        )

        return {
            "shipment": shipment,
            "pilot_scope": pilot_scope,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "regulatory_compliance": regulatory_compliance,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "valid_supplier_rfq_responses": [],
            "supplier_rfq_response_validation": None,
            "supplier_quote_comparisons": [],
            "supplier_quote_selection_decision": None,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "quote_approval": None,
            "quote_send_safety": None,
            "quote_case": None,
            "clarification_draft": clarification_draft,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
        }

    if (
        quote_readiness.can_generate_quote
        and not supplier_selection.get("selected_suppliers")
    ):
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="supplier_selection_required",
        )

        return {
            "shipment": shipment,
            "pilot_scope": pilot_scope,
            "customer_memory": customer_memory,
            "commodity_profile": commodity_profile,
            "missing_info": missing_info,
            "regulatory_compliance": regulatory_compliance,
            "equipment_decision": equipment_decision,
            "risk_assessment": risk_assessment,
            "supplier_selection": supplier_selection,
            "operational_consistency": operational_consistency,
            "quote_readiness": quote_readiness,
            "supplier_rfq_workflow": None,
            "supplier_rfq_drafts": [],
            "supplier_rfq_responses": [],
            "valid_supplier_rfq_responses": [],
            "supplier_rfq_response_validation": None,
            "supplier_quote_comparisons": [],
            "supplier_quote_selection_decision": None,
            "supplier_quote": None,
            "customer_quote": None,
            "quote_draft": None,
            "quote_approval": None,
            "quote_send_safety": None,
            "quote_case": None,
            "clarification_draft": None,
            "management_review_draft": None,
            "action_recommendation": action_recommendation,
            "result_type": "supplier_selection_required",
        }

    # 3. Her şey uygunsa supplier RFQ taslakları hazırlanır.
    dispatch_policy = (
        supplier_dispatch_policy
        if supplier_dispatch_policy is not None
        else resolve_supplier_dispatch_policy()
    )
    # RFQ oluşturmak gönderim değildir; insan onayı beklenir.
    supplier_rfq_workflow = SupplierRFQWorkflow(
        shipment=shipment,
        email_text=email_text,
        sender_address=sender_address,
        dispatch_policy=dispatch_policy,
    )
    initial_supplier_selection = {
        **supplier_selection,
        "selected_suppliers": supplier_selection["selected_suppliers"][
            : dispatch_policy.initial_supplier_count
        ],
    }
    supplier_rfq_drafts = generate_supplier_rfq_drafts(
        workflow_id=supplier_rfq_workflow.workflow_id,
        shipment=shipment,
        equipment_decision=equipment_decision,
        supplier_selection=initial_supplier_selection,
    )

    supplier_rfq_workflow = SupplierRFQWorkflow.model_validate(
        {
            **supplier_rfq_workflow.model_dump(),
            "rfq_ids": [draft.rfq_id for draft in supplier_rfq_drafts],
        }
    )
    if _persist_rfq_transition:
        with atomic_repository_transaction(rfq_repository):
            supplier_rfq_drafts = rfq_repository.save_drafts(
                supplier_rfq_drafts
            )
            supplier_rfq_workflow = rfq_repository.save_workflow(
                supplier_rfq_workflow
            )
    action_recommendation = generate_action_recommendation(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        missing_info=missing_info,
        result_type="supplier_rfq_approval_required",
    )

    return {
        "shipment": shipment,
        "pilot_scope": pilot_scope,
        "customer_memory": customer_memory,
        "commodity_profile": commodity_profile,
        "missing_info": missing_info,
        "regulatory_compliance": regulatory_compliance,
        "equipment_decision": equipment_decision,
        "risk_assessment": risk_assessment,
        "supplier_selection": supplier_selection,
        "operational_consistency": operational_consistency,
        "quote_readiness": quote_readiness,
        "supplier_rfq_workflow": supplier_rfq_workflow,
        "supplier_rfq_drafts": supplier_rfq_drafts,
        "supplier_rfq_responses": [],
        "valid_supplier_rfq_responses": [],
        "supplier_rfq_response_validation": None,
        "supplier_quote_comparisons": [],
        "supplier_quote_selection_decision": None,
        "supplier_quote": None,
        "customer_quote": None,
        "quote_draft": None,
        "quote_approval": None,
        "quote_send_safety": None,
        "quote_case": None,
        "clarification_draft": None,
        "management_review_draft": None,
        "result_type": "supplier_rfq_approval_required",
        "action_recommendation": action_recommendation,
    }
