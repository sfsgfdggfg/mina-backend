from __future__ import annotations

from datetime import datetime

from src.ai.quote_generator import generate_quote_draft
from src.ai.supplier_follow_up_generator import build_supplier_follow_up_draft
from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
from src.core.action_recommendation import generate_action_recommendation
from src.core.commodity_profile import get_commodity_record
from src.core.customer_memory import enrich_shipment_with_customer_memory
from src.core.data_provenance import DataProvenanceError
from src.core.equipment import decide_equipment
from src.core.missing_info import check_missing_information
from src.core.mail import OutboundMailRequest
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import link_mina_job_quote_case
from src.core.road_rfq_readiness import apply_road_rfq_readiness
from src.core.pilot_scope import evaluate_pilot_scope
from src.core.operational_consistency import check_operational_consistency
from src.core.operational_data import OperationalDataSources
from src.core.pricing import calculate_customer_quote
from src.core.pricing_policy import PricingFormula, resolve_pricing_policy
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
from src.core.supplier_dispatch_control import secondary_dispatch_gate
from src.core.supplier_rfq import SupplierRFQFollowUpDraft
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
    mina_job_repository: MinaJobRepository | None = None,
    operational_data_sources: OperationalDataSources | None = None,
    quote_pricing_override: PricingFormula | None = None,
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
            quote_pricing_override=quote_pricing_override,
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

    pending_rfq_drafts = list(result.pop("_rfq_drafts_to_save", []))
    pending_follow_up_drafts = list(
        result.pop("_follow_up_drafts_to_save", [])
    )
    pending_rfq_ids = [draft.rfq_id for draft in pending_rfq_drafts]
    persisted_rfq_ids = list(dict.fromkeys([*started.rfq_ids, *pending_rfq_ids]))

    result_type = result.get("result_type")
    if result_type == "data_provenance_blocked":
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "provenance_blocked",
                "last_provenance_blocked_at": datetime.utcnow(),
                "last_provenance_blocked_result_type": result_type,
                "rfq_ids": persisted_rfq_ids,
                "updated_at": datetime.utcnow(),
            }
        )
    elif result.get("quote_case") is not None:
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "completed",
                "quote_progressed_at": datetime.utcnow(),
                "rfq_ids": persisted_rfq_ids,
                "updated_at": datetime.utcnow(),
            }
        )
    else:
        persisted = started.__class__.model_validate(
            {
                **started.model_dump(),
                "quote_progression_status": "ready",
                "rfq_ids": persisted_rfq_ids,
                "updated_at": datetime.utcnow(),
            }
        )
    if result.get("quote_case") is not None:
        with atomic_repository_transaction(
            rfq_repository,
            approval_repository,
            quote_case_repository,
            mina_job_repository,
        ):
            _require_unchanged_progression_state(
                rfq_repository,
                workflow,
            )
            if pending_rfq_drafts:
                rfq_repository.save_drafts(pending_rfq_drafts)
            if pending_follow_up_drafts:
                rfq_repository.save_follow_up_drafts(pending_follow_up_drafts)
            result["quote_approval"] = approval_repository.save(
                result["quote_approval"]
            )
            result["quote_case"] = quote_case_repository.save(
                result["quote_case"]
            )
            if mina_job_repository is not None and persisted.mina_job_id:
                result["mina_job"] = link_mina_job_quote_case(
                    repository=mina_job_repository,
                    job_id=persisted.mina_job_id,
                    quote_case_id=result["quote_case"].case_id,
                )
            persisted = rfq_repository.save_workflow(persisted)
    else:
        with atomic_repository_transaction(rfq_repository):
            _require_unchanged_progression_state(
                rfq_repository,
                workflow,
            )
            if pending_rfq_drafts:
                rfq_repository.save_drafts(pending_rfq_drafts)
            if pending_follow_up_drafts:
                rfq_repository.save_follow_up_drafts(pending_follow_up_drafts)
            persisted = rfq_repository.save_workflow(persisted)
    result["supplier_rfq_workflow"] = persisted
    return result


def _next_supplier_rfq_draft(
    *,
    workflow,
    shipment,
    equipment_decision,
    supplier_selection,
    existing_drafts,
):
    existing_names = {draft.supplier_name for draft in existing_drafts}
    next_supplier = next(
        (
            supplier
            for supplier in supplier_selection.get("selected_suppliers", [])
            if supplier.get("supplier_name") not in existing_names
        ),
        None,
    )
    if next_supplier is None:
        return None
    generated = generate_supplier_rfq_drafts(
        workflow_id=workflow.workflow_id,
        shipment=shipment,
        equipment_decision=equipment_decision,
        supplier_selection={
            **supplier_selection,
            "selected_suppliers": [next_supplier],
        },
    )
    return generated[0] if generated else None


def _draft_for_rfq(drafts, rfq_id):
    return next((draft for draft in drafts if draft.rfq_id == rfq_id), None)


def _follow_up_mail_request(
    follow_up: SupplierRFQFollowUpDraft,
) -> OutboundMailRequest:
    return OutboundMailRequest(
        operation_id=follow_up.operation_id,
        recipients=[follow_up.recipient_email],
        subject=follow_up.subject,
        body_text=follow_up.body,
        purpose="supplier_rfq",
        correlation_reference=follow_up.reference_token,
        reference_metadata={
            "rfq_id": follow_up.rfq_id,
            "follow_up_id": follow_up.follow_up_id,
            "action": "supplier_clarification",
        },
    )


def _active_follow_up(
    repository: SupplierRFQRepository,
    rfq_id: str,
) -> SupplierRFQFollowUpDraft | None:
    candidates = sorted(
        repository.list_follow_up_drafts(rfq_id),
        key=lambda item: item.sequence_number,
        reverse=True,
    )
    return next(
        (
            item
            for item in candidates
            if item.status in {"draft", "approved", "awaiting_response"}
        ),
        None,
    )


def _progress_supplier_rfq_workflow(
    *,
    workflow,
    rfq_repository: SupplierRFQRepository,
    operational_data_sources: OperationalDataSources | None = None,
    quote_pricing_override: PricingFormula | None = None,
) -> dict:

    shipment = workflow.shipment
    customer_memory = enrich_shipment_with_customer_memory(
        shipment=shipment,
        email_text=workflow.email_text,
        sender_address=workflow.sender_address,
        operational_data_sources=operational_data_sources,
    )
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
    if not supplier_selection.get("selected_suppliers"):
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="supplier_selection_required",
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
            valid_responses=[],
            validation=None,
            comparisons=[],
            selection_decision=None,
            supplier_quote=None,
            result_type="supplier_selection_required",
            action_recommendation=action_recommendation,
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
    active_follow_up_record = next(
        (
            follow_up
            for draft in supplier_rfq_drafts
            if draft.status == "clarification_required"
            for follow_up in [
                _active_follow_up(rfq_repository, draft.rfq_id)
            ]
            if follow_up is not None
        ),
        None,
    )
    if active_follow_up_record is not None:
        operational_consistency = check_operational_consistency(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            supplier_selection=supplier_selection,
            supplier_quote=None,
            operational_data_sources=operational_data_sources,
        )
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
            comparisons=[],
            selection_decision=None,
            supplier_quote=None,
            result_type="supplier_response_required",
            action_recommendation=action_recommendation,
            supplier_follow_up_draft=(
                _follow_up_mail_request(active_follow_up_record)
            ),
            supplier_follow_up_record=active_follow_up_record,
        )

    supplier_quote_comparisons = build_supplier_quote_comparisons(
        responses=valid_supplier_rfq_responses,
        supplier_selection=supplier_selection,
        drafts=supplier_rfq_drafts,
        shipment=shipment,
        expected_equipment=(
            equipment_decision.selected_equipment
        ),
        require_commercial_safety=(
            shipment.transport_mode == "road"
        ),
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

    # Secondary suppliers are not prepared at initial dispatch. They become
    # eligible only after the primary-group gate is explicitly satisfied.
    dispatch_gate = secondary_dispatch_gate(
        rfq_repository, workflow.workflow_id
    )
    if dispatch_gate["allowed"]:
        existing_secondary = [
            draft
            for draft in supplier_rfq_drafts
            if draft.dispatch_tier == "secondary"
        ]
        if existing_secondary:
            held_secondary = [
                draft for draft in existing_secondary if draft.status == "draft"
            ]
            fallback_draft = None
        else:
            held_secondary = []
            fallback_draft = _next_supplier_rfq_draft(
                workflow=workflow,
                shipment=shipment,
                equipment_decision=equipment_decision,
                supplier_selection=supplier_selection,
                existing_drafts=supplier_rfq_drafts,
            )
        if held_secondary or fallback_draft is not None:
            visible_drafts = (
                supplier_rfq_drafts
                if fallback_draft is None
                else [*supplier_rfq_drafts, fallback_draft]
            )
            action_recommendation = generate_action_recommendation(
                shipment=shipment,
                equipment_decision=equipment_decision,
                risk_assessment=risk_assessment,
                missing_info=missing_info,
                result_type="supplier_rfq_approval_required",
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
                quote_readiness=None,
                drafts=visible_drafts,
                responses=supplier_rfq_responses,
                valid_responses=valid_supplier_rfq_responses,
                validation=supplier_rfq_response_validation,
                comparisons=supplier_quote_comparisons,
                selection_decision=supplier_quote_selection_decision,
                supplier_quote=None,
                result_type="supplier_rfq_approval_required",
                action_recommendation=action_recommendation,
            )
            if fallback_draft is not None:
                result["_rfq_drafts_to_save"] = [fallback_draft]
            return result

    if supplier_quote is None:
        # Prefer clarifying a real quoted response when its missing/contradictory
        # commercial facts can be fixed on the same RFQ.
        fixable_comparison = next(
            (
                comparison
                for comparison in supplier_quote_comparisons
                if not comparison.commercial_eligible
                and any(
                    reason in {
                        "supplier_transit_missing_or_unparseable",
                        "supplier_quote_expired",
                        "supplier_equipment_mismatch",
                        "supplier_price_has_unpriced_extras",
                        "supplier_has_excluded_costs",
                    }
                    for reason in comparison.commercial_rejection_reasons
                )
            ),
            None,
        )
        if fixable_comparison is not None:
            current_draft = _draft_for_rfq(
                supplier_rfq_drafts, fixable_comparison.rfq_id
            )
            existing_follow_up = (
                _active_follow_up(rfq_repository, fixable_comparison.rfq_id)
                if current_draft is not None
                else None
            )
            follow_up_record = existing_follow_up
            follow_up = (
                _follow_up_mail_request(existing_follow_up)
                if existing_follow_up is not None
                else None
            )
            if follow_up is None and current_draft is not None:
                existing_history = rfq_repository.list_follow_up_drafts(
                    current_draft.rfq_id
                )
                sequence_number = (
                    max(
                        (item.sequence_number for item in existing_history),
                        default=0,
                    )
                    + 1
                )
                generated_follow_up = build_supplier_follow_up_draft(
                    draft=current_draft,
                    rejection_reasons=(
                        fixable_comparison.commercial_rejection_reasons
                    ),
                    sequence_number=sequence_number,
                )
                if generated_follow_up is not None:
                    follow_up_record = SupplierRFQFollowUpDraft(
                        rfq_id=current_draft.rfq_id,
                        workflow_id=current_draft.workflow_id,
                        sequence_number=sequence_number,
                        recipient_email=generated_follow_up.recipients[0],
                        subject=generated_follow_up.subject,
                        body=generated_follow_up.body_text,
                        rejection_reasons=list(
                            fixable_comparison.commercial_rejection_reasons
                        ),
                    )
                    follow_up = _follow_up_mail_request(follow_up_record)
            if follow_up is not None and current_draft is not None:
                reopened = current_draft.model_copy(
                    update={"status": "clarification_required"}
                )
                visible_drafts = [
                    reopened if draft.rfq_id == reopened.rfq_id else draft
                    for draft in supplier_rfq_drafts
                ]
                action_recommendation = generate_action_recommendation(
                    shipment=shipment,
                    equipment_decision=equipment_decision,
                    risk_assessment=risk_assessment,
                    missing_info=missing_info,
                    result_type="supplier_response_required",
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
                    quote_readiness=None,
                    drafts=visible_drafts,
                    responses=supplier_rfq_responses,
                    valid_responses=valid_supplier_rfq_responses,
                    validation=supplier_rfq_response_validation,
                    comparisons=supplier_quote_comparisons,
                    selection_decision=supplier_quote_selection_decision,
                    supplier_quote=None,
                    result_type="supplier_response_required",
                    action_recommendation=action_recommendation,
                    supplier_follow_up_draft=follow_up,
                    supplier_follow_up_record=follow_up_record,
                )
                result["_rfq_drafts_to_save"] = [reopened]
                if (
                    follow_up_record is not None
                    and existing_follow_up is None
                ):
                    result["_follow_up_drafts_to_save"] = [follow_up_record]
                return result

        # A terminal negative or a supplier that cannot meet the deadline should
        # advance to the next selected carrier by preparing (not sending) an RFQ.
        terminal_negative = any(
            response.status in {"no_capacity", "declined"}
            for response in valid_supplier_rfq_responses
        )
        deadline_miss = any(
            "required_delivery_date_not_achievable"
            in comparison.commercial_rejection_reasons
            for comparison in supplier_quote_comparisons
        )
        waiting_on_existing = any(
            draft.status in {
                "draft", "approved", "sent", "awaiting_response",
                "clarification_required",
            }
            and not (draft.dispatch_tier == "secondary" and draft.status == "draft")
            for draft in supplier_rfq_drafts
        )
        if (terminal_negative or deadline_miss) and not waiting_on_existing:
            fallback_draft = _next_supplier_rfq_draft(
                workflow=workflow,
                shipment=shipment,
                equipment_decision=equipment_decision,
                supplier_selection=supplier_selection,
                existing_drafts=supplier_rfq_drafts,
            )
            if fallback_draft is not None:
                action_recommendation = generate_action_recommendation(
                    shipment=shipment,
                    equipment_decision=equipment_decision,
                    risk_assessment=risk_assessment,
                    missing_info=missing_info,
                    result_type="supplier_rfq_approval_required",
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
                    quote_readiness=None,
                    drafts=[*supplier_rfq_drafts, fallback_draft],
                    responses=supplier_rfq_responses,
                    valid_responses=valid_supplier_rfq_responses,
                    validation=supplier_rfq_response_validation,
                    comparisons=supplier_quote_comparisons,
                    selection_decision=supplier_quote_selection_decision,
                    supplier_quote=None,
                    result_type="supplier_rfq_approval_required",
                    action_recommendation=action_recommendation,
                )
                result["_rfq_drafts_to_save"] = [fallback_draft]
                return result

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

    customer_pricing_policy = (
        customer_memory.profile.pricing_policy
        if customer_memory.matched
        and customer_memory.profile is not None
        else None
    )
    pricing_policy_resolution = resolve_pricing_policy(
        currency=supplier_quote.currency,
        customer_pricing_policy=customer_pricing_policy,
        quote_override=quote_pricing_override,
    )
    if not pricing_policy_resolution.resolved:
        action_recommendation = generate_action_recommendation(
            shipment=shipment,
            equipment_decision=equipment_decision,
            risk_assessment=risk_assessment,
            missing_info=missing_info,
            result_type="pricing_policy_required",
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
            result_type="pricing_policy_required",
            action_recommendation=action_recommendation,
            pricing_policy_resolution=pricing_policy_resolution,
        )

    customer_quote = calculate_customer_quote(
        supplier_quote, pricing_policy_resolution
    )
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
        mina_job_id=workflow.mina_job_id,
        mina_code=workflow.mina_code,
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
        pricing_policy_resolution=pricing_policy_resolution,
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
    supplier_follow_up_draft=None,
    supplier_follow_up_record=None,
    pricing_policy_resolution=None,
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
        "pricing_policy_resolution": pricing_policy_resolution,
        "customer_quote": None,
        "quote_draft": None,
        "quote_approval": None,
        "quote_send_safety": None,
        "quote_case": None,
        "clarification_draft": None,
        "management_review_draft": None,
        "supplier_follow_up_draft": supplier_follow_up_draft,
        "supplier_follow_up_record": supplier_follow_up_record,
        "result_type": result_type,
        "action_recommendation": action_recommendation,
    }
