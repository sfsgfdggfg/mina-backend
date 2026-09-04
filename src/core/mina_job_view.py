from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.automation_action_repository import AutomationActionRepository
from src.core.automation_policy_repository import AgencyAutomationPolicyRepository
from src.core.automation_policy_service import resolve_effective_automation_policy
from src.core.master_data_repository import MasterDataRepository
from src.core.operation_execution_repository import OperationExecutionRepository
from src.core.operation_execution_service import build_operation_execution_view
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import build_learning_fact_view
from src.core.automation_planning import customer_deadline_plan, supplier_reminder_plan
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import (
    allowed_next_stages,
    get_mina_job_or_raise,
)
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.supplier_price_repository import SupplierPriceRepository
from src.core.supplier_price_service import PRICE_SOURCING_STAGES, build_job_supplier_price_view


def _route_text(job) -> str:
    pickup = job.shipment.pickup_city or job.shipment.pickup_country or "?"
    delivery = job.shipment.delivery_city or job.shipment.delivery_country or "?"
    return f"{pickup} → {delivery}"


def build_mina_job_list(repository: MinaJobRepository) -> dict[str, Any]:
    jobs = []
    for job in reversed(repository.list_all()):
        jobs.append({
            "job_id": job.job_id,
            "mina_code": job.mina_code,
            "stage": job.stage,
            "is_closed": job.is_closed,
            "lifecycle_version": job.lifecycle_version,
            "job_kind": job.job_kind,
            "intake_channel": job.intake_channel,
            "sales_owner": job.sales_owner,
            "operations_owner": job.operations_owner,
            "customer_name": job.shipment.customer_name,
            "route": _route_text(job),
            "transport_mode": job.shipment.transport_mode,
            "opened_at": job.opened_at,
            "updated_at": job.updated_at,
        })
    return {"jobs": jobs}


def build_mina_job_detail(
    *, repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    quote_case_repository: QuoteCaseRepository,
    action_repository: AutomationActionRepository,
    price_repository: SupplierPriceRepository | None = None,
    master_data_repository: MasterDataRepository | None = None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None = None,
    operation_execution_repository: OperationExecutionRepository | None = None,
    learning_fact_repository: LearningFactRepository | None = None,
    job_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    job = get_mina_job_or_raise(repository, job_id=job_id)
    current = now or datetime.now(timezone.utc)
    workflow = (
        supplier_repository.get_workflow(job.supplier_rfq_workflow_id)
        if job.supplier_rfq_workflow_id else None
    )
    supplier_rows: list[dict[str, Any]] = []
    if workflow is not None:
        for draft in supplier_repository.list_drafts():
            if draft.workflow_id != workflow.workflow_id:
                continue
            responses = supplier_repository.list_responses(draft.rfq_id)
            acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
            plan = supplier_reminder_plan(
                supplier_repository=supplier_repository,
                action_repository=action_repository,
                draft=draft,
                now=current,
                mina_job_repository=repository,
                master_data_repository=master_data_repository,
                agency_policy_repository=agency_policy_repository,
            )
            latest_response = max(responses, key=lambda item: item.received_at) if responses else None
            latest_ack = max(acknowledgements, key=lambda item: item.acknowledged_at) if acknowledgements else None
            supplier_rows.append({
                "rfq_id": draft.rfq_id,
                "supplier_name": draft.supplier_name,
                "dispatch_tier": draft.dispatch_tier,
                "status": draft.status,
                "sent_at": draft.sent_at,
                "responded_at": draft.responded_at,
                "latest_acknowledgement_at": None if latest_ack is None else latest_ack.acknowledged_at,
                "commercial_response": None if latest_response is None else {
                    "status": latest_response.status,
                    "cost": latest_response.cost,
                    "currency": latest_response.currency,
                    "transit_time": latest_response.transit_time,
                },
                "reminder": {
                    key: plan.get(key)
                    for key in ("state", "action_type", "due_at", "resume_at", "reason")
                    if plan.get(key) is not None
                },
            })
    customer_plan: dict[str, Any] | None = None
    supplier_auto_effective: bool | None = None
    customer_auto_effective: bool | None = None
    supplier_policy = None
    customer_policy = None
    if workflow is not None:
        supplier_policy = resolve_effective_automation_policy(
            action="supplier_reminder",
            legacy_dispatch_enabled=workflow.dispatch_policy.automatic_supplier_reminders_enabled,
            mina_job_repository=repository, job_id=job.job_id,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
        )
        customer_policy = resolve_effective_automation_policy(
            action="customer_deadline_update",
            legacy_dispatch_enabled=workflow.dispatch_policy.automatic_customer_deadline_updates_enabled,
            mina_job_repository=repository, job_id=job.job_id,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
        )
        supplier_auto_effective = supplier_policy.effective_mode == "automatic"
        customer_auto_effective = customer_policy.effective_mode == "automatic"
        customer_plan = customer_deadline_plan(
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            workflow=workflow,
            now=current,
            mina_job_repository=repository,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
        )

    quote_case = (
        quote_case_repository.get(job.quote_case_id)
        if job.quote_case_id else None
    )
    quote_summary = None
    if quote_case is not None:
        approval = quote_case.quote_approval
        quote_summary = {
            "case_id": quote_case.case_id,
            "revision_count": len(quote_case.quote_revisions),
            "current_revision_number": len(quote_case.quote_revisions),
            "approval_status": None if approval is None else approval.approval_status,
            "manual_send_count": len(quote_case.manual_sent_evidence),
            "automated_send_count": len(quote_case.automated_sent_evidence),
        }
    timeline = [event.model_dump() for event in repository.list_events(job.job_id)]
    supplier_prices = (
        build_job_supplier_price_view(
            price_repository=price_repository, mina_repository=repository,
            supplier_repository=supplier_repository, job_id=job.job_id,
        )
        if price_repository is not None
        else None
    )
    operation = (
        build_operation_execution_view(
            execution_repository=operation_execution_repository,
            mina_repository=repository, job_id=job.job_id,
        )
        if operation_execution_repository is not None
        else None
    )
    learning = (
        build_learning_fact_view(
            repository=learning_fact_repository, subject_type="operation", subject_id=job.job_id,
        )
        if learning_fact_repository is not None
        else None
    )
    return {
        "job": job.model_dump(),
        "summary": {
            "mina_code": job.mina_code,
            "stage": job.stage,
            "is_closed": job.is_closed,
            "lifecycle_version": job.lifecycle_version,
            "job_kind": job.job_kind,
            "intake_channel": job.intake_channel,
            "sales_owner": job.sales_owner,
            "operations_owner": job.operations_owner,
            "customer_name": job.shipment.customer_name,
            "route": _route_text(job),
            "transport_mode": job.shipment.transport_mode,
            "customer_quote_deadline_at": job.shipment.customer_quote_deadline_at,
        },
        "automation": {
            "overrides": job.automation_overrides.model_dump(),
            "supplier_reminders_effective": supplier_auto_effective,
            "customer_deadline_updates_effective": customer_auto_effective,
            "customer_deadline_plan": customer_plan,
            "supplier_reminder_policy": None if supplier_policy is None else supplier_policy.model_dump(),
            "customer_deadline_update_policy": None if customer_policy is None else customer_policy.model_dump(),
        },
        "suppliers": supplier_rows,
        "supplier_prices": supplier_prices,
        "operation": operation,
        "learning": learning,
        "quote": quote_summary,
        "timeline": timeline,
        "controls": {
            "automation_overrides_editable": not job.is_closed,
            "stage_transition_available": not job.is_closed,
            "allowed_next_stages": allowed_next_stages(job),
            "supplier_reminder_preview_available": not job.is_closed,
            "supplier_price_entry_available": (not job.is_closed and job.stage in PRICE_SOURCING_STAGES),
        },
    }
