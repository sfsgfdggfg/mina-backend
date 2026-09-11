from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from src.core.supplier_intelligence_policy import resolve_supplier_operational_learning_policy
from src.core.supplier_rfq import SupplierRFQDraft
from src.core.supplier_rfq_repository import SupplierRFQRepository


class SupplierNextBestAction(BaseModel):
    action: Literal[
        "wait", "contact_supplier", "management_contact",
        "manual_relationship_review", "follow_reminder_workflow", "none",
    ]
    label: str
    channel: Literal["phone", "whatsapp"] | None = None
    level: Literal["operator", "management"] | None = None
    source: Literal[
        "supplier_master", "confirmed_learning", "operational_rule",
        "current_evidence", "reminder_workflow",
    ]
    reason: str
    due_at: datetime | None = None
    automatic_action_allowed: bool = False
    secondary_release_allowed: bool = False


def _relationship(master_data_repository, supplier_name: str):
    if master_data_repository is None:
        return None
    supplier = master_data_repository.find_supplier_by_name(supplier_name)
    return None if supplier is None else supplier.relationship


def _latest_by_key(items, key):
    latest = {}
    for item in sorted(items, key=lambda value: value.escalated_at):
        latest[key(item)] = item
    return latest


def build_supplier_next_best_action(
    *, draft: SupplierRFQDraft, workflow, reminder_plan: dict[str, Any],
    supplier_repository: SupplierRFQRepository, master_data_repository=None,
    learning_fact_repository=None, as_of: datetime | None = None,
) -> SupplierNextBestAction:
    if supplier_repository.list_responses(draft.rfq_id):
        return SupplierNextBestAction(
            action="none", label="Ticari yanıt mevcut", source="current_evidence",
            reason="commercial_response_present",
        )
    state = str(reminder_plan.get("state") or "")
    if state in {"waiting", "outside_business_hours_waiting", "waiting_supplier_contact_escalation"}:
        due_at = reminder_plan.get("escalation_due_at") or reminder_plan.get("resume_at") or reminder_plan.get("due_at")
        return SupplierNextBestAction(
            action="wait", label="Bekle", source="reminder_workflow",
            reason=state, due_at=due_at,
        )

    if state != "human_contact_required":
        return SupplierNextBestAction(
            action="follow_reminder_workflow", label="Reminder akışını takip et",
            source="reminder_workflow", reason=state or "reminder_state_unknown",
        )

    relationship = _relationship(master_data_repository, draft.supplier_name)
    preferred = ["phone", "whatsapp"] if relationship is None else [
        channel for channel in relationship.preferred_contact_channels
        if channel in {"phone", "whatsapp"}
    ]
    if not preferred:
        preferred = ["phone", "whatsapp"]

    acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
    latest_ack = max(acknowledgements, key=lambda item: item.acknowledged_at) if acknowledgements else None
    policy = resolve_supplier_operational_learning_policy(
        supplier_name=draft.supplier_name,
        master_data_repository=master_data_repository,
        learning_repository=learning_fact_repository,
        base_first_reminder_minutes=workflow.dispatch_policy.no_response_reminder_minutes,
        base_acknowledged_wait_minutes=workflow.dispatch_policy.acknowledged_grace_minutes,
        acknowledgement_channel=None if latest_ack is None else latest_ack.channel,
        as_of=as_of,
    )
    escalation_advisory = None if policy is None else policy.preferred_escalation_channel_advisory
    management_advisory = False if policy is None else policy.management_escalation_advisory

    escalations = supplier_repository.list_escalation_evidence(draft.rfq_id)
    latest_operator = _latest_by_key(
        [item for item in escalations if item.level == "operator"],
        key=lambda item: item.channel,
    )
    latest_management = max(
        (item for item in escalations if item.level == "management"),
        key=lambda item: item.escalated_at,
        default=None,
    )
    if any(item.outcome == "acknowledged_working" for item in latest_operator.values()):
        return SupplierNextBestAction(
            action="wait", label="Tedarikçi yanıtını bekle", source="current_evidence",
            reason="operator_escalation_acknowledged_working",
        )
    if latest_management is not None and latest_management.outcome == "acknowledged_working":
        return SupplierNextBestAction(
            action="wait", label="Tedarikçi yanıtını bekle", source="current_evidence",
            reason="management_escalation_acknowledged_working",
        )

    failed_channels = {
        channel for channel, item in latest_operator.items()
        if item.outcome in {"no_response", "unreachable"}
    }
    available = [channel for channel in preferred if channel not in failed_channels]
    if available:
        manual_candidates = []
        if relationship is not None:
            if "phone" in available and relationship.phone_escalation_after_minutes is not None:
                manual_candidates.append(("phone", relationship.phone_escalation_after_minutes))
            if "whatsapp" in available and relationship.whatsapp_escalation_after_minutes is not None:
                manual_candidates.append(("whatsapp", relationship.whatsapp_escalation_after_minutes))
        if manual_candidates:
            channel = min(manual_candidates, key=lambda item: item[1])[0]
            return SupplierNextBestAction(
                action="contact_supplier", label=f"{'Telefon' if channel == 'phone' else 'WhatsApp'} ile takip et",
                channel=channel, level="operator", source="supplier_master",
                reason="explicit_supplier_escalation_timing_preference",
            )
        if escalation_advisory in available:
            channel = escalation_advisory
            return SupplierNextBestAction(
                action="contact_supplier", label=f"{'Telefon' if channel == 'phone' else 'WhatsApp'} ile takip et",
                channel=channel, level="operator", source="confirmed_learning",
                reason="confirmed_escalation_channel_history",
            )
        if policy is not None and policy.preferred_contact_channel_advisory in available:
            channel = policy.preferred_contact_channel_advisory
            return SupplierNextBestAction(
                action="contact_supplier", label=f"{'Telefon' if channel == 'phone' else 'WhatsApp'} ile takip et",
                channel=channel, level="operator", source="confirmed_learning",
                reason="confirmed_general_contact_history",
            )
        if len(available) == 1:
            channel = available[0]
            return SupplierNextBestAction(
                action="contact_supplier", label=f"{'Telefon' if channel == 'phone' else 'WhatsApp'} ile takip et",
                channel=channel, level="operator", source="current_evidence",
                reason="alternate_channel_after_failed_escalation",
            )
        return SupplierNextBestAction(
            action="contact_supplier", label="Telefon veya WhatsApp ile takip et",
            source="operational_rule", reason="human_contact_required_after_reminder",
        )

    management_allowed = relationship is None or relationship.management_escalation_allowed is not False
    if latest_management is not None and latest_management.outcome in {"no_response", "unreachable"}:
        return SupplierNextBestAction(
            action="manual_relationship_review", label="Tedarikçi ilişkisini manuel değerlendir",
            source="current_evidence", reason="management_escalation_already_failed",
        )
    if management_allowed:
        return SupplierNextBestAction(
            action="management_contact", label="Yönetici / patron eskalasyonu yap",
            level="management", channel="phone",
            source="confirmed_learning" if management_advisory else "operational_rule",
            reason=(
                "confirmed_management_escalation_history"
                if management_advisory else "operator_channels_exhausted_before_secondary"
            ),
        )
    return SupplierNextBestAction(
        action="manual_relationship_review", label="Tedarikçi ilişkisini manuel değerlendir",
        source="supplier_master", reason="management_escalation_explicitly_disabled",
    )
