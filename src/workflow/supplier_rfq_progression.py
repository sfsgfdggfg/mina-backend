from __future__ import annotations

from datetime import datetime

from src.ai.quote_generator import generate_quote_draft
from src.core.action_recommendation import generate_action_recommendation
from src.core.commodity_profile import get_commodity_record
from src.core.customer_memory import enrich_shipment_with_customer_memory
from src.core.data_provenance import DataProvenanceError
from src.core.equipment import decide_equipment
from src.core.missing_info import check_missing_information
from src.core.pilot_scope import evaluate_pilot_scope
from src.core.operational_consistency import check_operational_consistency
from src.core.operational_data import OperationalDataSources
from src.core.pricing import calculate_customer_quote
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_readiness import decide_quote_readiness
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.regulatory_compliance import assess_regulatory_compliance
from src.core.risk import assess_risk
from src.core.supplier_quote_comparison import (
    build_supplier_quote_comparisons,
)
from src.core.supplier_quote_selection import (
    build_supplier_quote_selection_decision,
    select_supplier_quote_from_comparisons,
)
from src.core.supplier_rfq_lifecycle import (
    validate_supplier_rfq_responses,
)
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_selection import select_suppliers_for_shipment
from src.workflow.pipeline import build_data_provenance_blocked_result


class SupplierRFQWorkflowNotFoundError(LookupError):
    pass


class SupplierRFQWorkflowProgressionError(ValueError):
    pass


def _require_unchanged_progression_state(
    rfq_repository: SupplierRFQRepository,
    expected,
) -> None:
    current = rfq_repository.get_workflow(expected.workflow_id)
    if current is None:
        raise SupplierRFQWorkflowNotFoundError(
            f"Supplier RFQ workflow not found: {expected.workflow_id}"
        )
    expected_state = (
        expected.quote_progression_status,
        expected.quote_progression_attempt_count,
        expected.quote_progression_started_at,
        expected.quote_progressed_at,
        expected.last_provenance_blocked_at,
        expected.last_provenance_blocked_result_type,
    )
    current_state = (
        current.quote_progression_status,
        current.quote_progression_attempt_count,
        current.quote_progression_started_at,
        current.quote_progressed_at,
        current.last_provenance_blocked_at,
        current.last_provenance_blocked_result_type,
    )
    if current_state != expected_state:
        raise SupplierRFQWorkflowProgressionError(
            "Supplier RFQ quote progression changed during processing."
        )


def resume_supplier_rfq_workflow(
    *,
    workflow_id: str,
    rfq_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    operational_data_sources: OperationalDataSources | None = None,
) -> dict:
    workflow = rfq_repository.get_workflow(workflow_id)
    if workflow is None:
        raise SupplierRFQWorkflowNotFoundError(
            f"Supplier RFQ workflow not found: {workflow_id}"
        )
    if workflow.quote_progression_status in {"in_progress", "completed"}:
        raise SupplierRFQWorkflowProgressionError(
            "Supplier RFQ quote progression has already started."
        )

    started = workflow.__class__.model_validate(
        {
            **workflow.model_dump(),
            "quote_progression_status": "in_progress",
            "quote_progression_attempt_count": (
                workflow.quote_progression_attempt_count + 1
            ),
            "quote_progression_started_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
    )
    try:
        result = _progress_supplier_rfq_workflow(
            workflow=started,
            rfq_repository=rfq_repository,
            operational_data_sources=operational_data_sources,
        )
    except DataProvenanceError:
        drafts = [
            draft
            for draft in rfq_repository.list_drafts()
            if draft.workflow_id == workflow_id
        ]
        responses = [
            response
            for draft in drafts
            for response in rfq_repository.list_responses(draft.rfq_id)
        ]
        result = build_data_provenance_blocked_result(
            started.shipment,
            supplier_rfq_workflow=started,
            supplier_rfq_drafts=drafts,
            supplier_rfq_responses=responses,
        )

    result_type = result.get("result_type")
    if result_type == "data_provenance_blocked":
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "provenance_blocked",
                "last_provenance_blocked_at": datetime.utcnow(),
                "last_provenance_blocked_result_type": result_type,
                "updated_at": datetime.utcnow(),
            }
        )
    elif result.get("quote_case") is not None:
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "completed",
                "quote_progressed_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        )
    else:
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "ready",
                "updated_at": datetime.utcnow(),
            }
        )
    if result.get("quote_case") is not None:
        with atomic_repository_transaction(
            rfq_repository,
            approval_repository,
            quote_case_repository,
        ):
            _require_unchanged_progression_state(
                rfq_repository,
                workflow,
            )
            result["quote_approval"] = approval_repository.save(
                result["quote_approval"]
            )
            result["quote_case"] = quote_case_repository.save(
                result["quote_case"]
            )
            persisted = rfq_repository.save_workflow(persisted)
    else:
        with atomic_repository_transaction(rfq_repository):
            _require_unchanged_progression_state(
                rfq_repository,
                workflow,
            )
            persisted = rfq_repository.save_workflow(persisted)
    result["supplier_rfq_workflow"] = persisted
    return result


def _progress_supplier_rfq_workflow(
    *,
    workflow,
    rfq_repository: SupplierRFQRepository,
    operational_data_sources: OperationalDataSources | None = None,
) -> dict:

    shipment = workflow.shipment
    customer_memory = enrich_shipment_with_customer_memory(
        shipment=shipment,
        email_text=workflow.email_text,
        operational_data_sources=operational_data_sources,
    )
    commodity_profile = get_commodity_record(shipment.commodity)
    missing_info = check_missing_information(shipment)
    regulatory_compliance = assess_regulatory_compliance(shipment)
    equipment_decision = decide_equipment(shipment)
    risk_assessment = assess_risk(
        shipment=shipment,
        customer_memory=customer_memory,
    )
    pilot_scope = evaluate_pilot_scope(shipment)
    supplier_rfq_drafts = [
        draft
        for draft in rfq_repository.list_drafts()
        if draft.workflow_id == workflow.workflow_id
    ]
    supplier_rfq_responses = [
        response
        for draft in supplier_rfq_drafts
        for response in rfq_repository.list_responses(draft.rfq_id)
    ]
    if not pilot_scope.eligible:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="pilot_scope_excluded",
        )
        return _result(
            workflow=workflow,
            pilot_scope=pilot_scope,
            customer_memory=customer_memory,
            commodity_profile=commodity_profile,
            missing_info=missing_info,
            regulatory_compliance=regulatory_compliance,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            supplier_selection=None,
            operational_consistency=None,
            quote_readiness=None,
            drafts=supplier_rfq_drafts,
            responses=supplier_rfq_responses,
            valid_responses=[],
            validation=None,
            comparisons=[],
            selection_decision=None,
            supplier_quote=None,
            result_type="pilot_scope_excluded",
            action_recommendation=action_recommendation,
        )
    supplier_selection = select_suppliers_for_shipment(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        operational_data_sources=operational_data_sources,
    )
    (
        valid_supplier_rfq_responses,
        supplier_rfq_response_validation,
    ) = validate_supplier_rfq_responses(
        drafts=supplier_rfq_drafts,
        responses=supplier_rfq_responses,
    )
    pilot_scope = evaluate_pilot_scope(
        shipment,
        supplier_responses=valid_supplier_rfq_responses,
    )
    if not pilot_scope.eligible:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="pilot_scope_excluded",
        )
        return _result(
            workflow=workflow,
            pilot_scope=pilot_scope,
            customer_memory=customer_memory,
            commodity_profile=commodity_profile,
            missing_info=missing_info,
            regulatory_compliance=regulatory_compliance,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            supplier_selection=supplier_selection,
            operational_consistency=None,
            quote_readiness=None,
            drafts=supplier_rfq_drafts,
            responses=supplier_rfq_responses,
            valid_responses=valid_supplier_rfq_responses,
            validation=supplier_rfq_response_validation,
            comparisons=[],
            selection_decision=None,
            supplier_quote=None,
            result_type="pilot_scope_excluded",
            action_recommendation=action_recommendation,
        )
    supplier_quote_comparisons = build_supplier_quote_comparisons(
        responses=valid_supplier_rfq_responses,
        supplier_selection=supplier_selection,
        drafts=supplier_rfq_drafts,
    )
    supplier_quote = select_supplier_quote_from_comparisons(
        comparisons=supplier_quote_comparisons,
        responses=valid_supplier_rfq_responses,
    )
    supplier_quote_selection_decision = (
        build_supplier_quote_selection_decision(
            comparisons=supplier_quote_comparisons,
        )
    )
    operational_consistency = check_operational_consistency(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_selection=supplier_selection,
        supplier_quote=supplier_quote,
        operational_data_sources=operational_data_sources,
    )

    if supplier_quote is None:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="supplier_response_required",
        )
        return _result(
            workflow=workflow,
            pilot_scope=pilot_scope,
            customer_memory=customer_memory,
            commodity_profile=commodity_profile,
            missing_info=missing_info,
            regulatory_compliance=regulatory_compliance,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            supplier_selection=supplier_selection,
            operational_consistency=operational_consistency,
            quote_readiness=None,
            drafts=supplier_rfq_drafts,
            responses=supplier_rfq_responses,
            valid_responses=valid_supplier_rfq_responses,
            validation=supplier_rfq_response_validation,
            comparisons=supplier_quote_comparisons,
            selection_decision=supplier_quote_selection_decision,
            supplier_quote=None,
            result_type="supplier_response_required",
            action_recommendation=action_recommendation,
        )

    quote_readiness = decide_quote_readiness(
        missing_info=missing_info,
        risk_assessment=risk_assessment,
        operational_consistency=operational_consistency,
        regulatory_compliance=regulatory_compliance,
    )
    if not quote_readiness.can_generate_quote:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type=quote_readiness.result_type,
        )
        return _result(
            workflow=workflow,
            pilot_scope=pilot_scope,
            customer_memory=customer_memory,
            commodity_profile=commodity_profile,
            missing_info=missing_info,
            regulatory_compliance=regulatory_compliance,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            supplier_selection=supplier_selection,
            operational_consistency=operational_consistency,
            quote_readiness=quote_readiness,
            drafts=supplier_rfq_drafts,
            responses=supplier_rfq_responses,
            valid_responses=valid_supplier_rfq_responses,
            validation=supplier_rfq_response_validation,
            comparisons=supplier_quote_comparisons,
            selection_decision=supplier_quote_selection_decision,
            supplier_quote=supplier_quote,
            result_type=quote_readiness.result_type,
            action_recommendation=action_recommendation,
        )

    customer_quote = calculate_customer_quote(supplier_quote)
    quote_draft = generate_quote_draft(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
    )
    quote_approval = QuoteApproval(
        quote_snapshot=QuoteApprovalSnapshot.from_quote(
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
        )
    )
    quote_send_safety = evaluate_quote_send_safety(
        approval=quote_approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        regulatory_compliance=regulatory_compliance,
    )
    quote_case = QuoteCase(
        shipment=shipment,
        supplier_rfq_workflow_id=workflow.workflow_id,
        supplier_quote_selection_decision=(
            supplier_quote_selection_decision
        ),
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=quote_approval,
        quote_send_safety=quote_send_safety,
        regulatory_compliance=regulatory_compliance,
    )
    action_recommendation = generate_action_recommendation(
        shipment=shipment,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        missing_info=missing_info,
        result_type=quote_readiness.result_type,
    )
    result = _result(
        workflow=workflow,
        pilot_scope=pilot_scope,
        customer_memory=customer_memory,
        commodity_profile=commodity_profile,
        missing_info=missing_info,
        regulatory_compliance=regulatory_compliance,
        equipment_decision=equipment_decision,
        risk_assessment=risk_assessment,
        supplier_selection=supplier_selection,
        operational_consistency=operational_consistency,
        quote_readiness=quote_readiness,
        drafts=supplier_rfq_drafts,
        responses=supplier_rfq_responses,
        valid_responses=valid_supplier_rfq_responses,
        validation=supplier_rfq_response_validation,
        comparisons=supplier_quote_comparisons,
        selection_decision=supplier_quote_selection_decision,
        supplier_quote=supplier_quote,
        result_type=quote_readiness.result_type,
        action_recommendation=action_recommendation,
    )
    result.update(
        {
            "customer_quote": customer_quote,
            "quote_draft": quote_draft,
            "quote_approval": quote_approval,
            "quote_send_safety": quote_send_safety,
            "quote_case": quote_case,
        }
    )
    return result


def _result(
    *,
    workflow,
    pilot_scope,
    customer_memory,
    commodity_profile,
    missing_info,
    regulatory_compliance,
    equipment_decision,
    risk_assessment,
    supplier_selection,
    operational_consistency,
    quote_readiness,
    drafts,
    responses,
    valid_responses,
    validation,
    comparisons,
    selection_decision,
    supplier_quote,
    result_type,
    action_recommendation,
) -> dict:
    return {
        "shipment": workflow.shipment,
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
        "supplier_rfq_workflow": workflow,
        "supplier_rfq_drafts": drafts,
        "supplier_rfq_responses": responses,
        "valid_supplier_rfq_responses": valid_responses,
        "supplier_rfq_response_validation": validation,
        "supplier_quote_comparisons": comparisons,
        "supplier_quote_selection_decision": selection_decision,
        "supplier_quote": supplier_quote,
        "customer_quote": None,
        "quote_draft": None,
        "quote_approval": None,
        "quote_send_safety": None,
        "quote_case": None,
        "clarification_draft": None,
        "management_review_draft": None,
        "result_type": result_type,
        "action_recommendation": action_recommendation,
    }
