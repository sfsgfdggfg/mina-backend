from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from src.core.business_calendar import (
    SupplierHolidayCalendarCoverageError,
    is_supplier_business_time,
    next_supplier_business_open,
)
from src.core.mail import OutboundMailRequest, OutboundMailSender
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import MinaJobTransitionError, transition_mina_job_stage
from src.core.operation_start import OperationStartMessage, OperationStartSendReconciliationEvidence
from src.core.operation_start_repository import OperationStartMessageRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.mail_delivery import dispatch_outbound_mail


class OperationStartError(ValueError):
    pass


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Operation-start timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _actor(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _message_id(*, job_id: str, kind: str, supplier_name: str) -> str:
    identity = f"minai-operation-start:{job_id}:{kind}:{supplier_name.strip().casefold()}"
    return str(uuid5(NAMESPACE_URL, identity))


def _relationship(master_repository: MasterDataRepository | None, supplier_name: str):
    if master_repository is None:
        return None
    profile = master_repository.find_supplier_by_name(supplier_name)
    return None if profile is None or not profile.active else profile.relationship


def _draft_for_supplier(
    supplier_repository: SupplierRFQRepository,
    *, workflow_id: str, supplier_name: str, rfq_id: str | None = None,
):
    if rfq_id:
        draft = supplier_repository.get_draft(rfq_id)
        if draft is not None and draft.workflow_id == workflow_id:
            return draft
    candidates = [
        draft for draft in supplier_repository.list_drafts()
        if draft.workflow_id == workflow_id and draft.supplier_name == supplier_name
    ]
    return candidates[0] if candidates else None


def _recipient_for_supplier(
    *, master_repository: MasterDataRepository | None,
    supplier_repository: SupplierRFQRepository,
    workflow_id: str,
    supplier_name: str,
    rfq_id: str | None = None,
) -> str | None:
    draft = _draft_for_supplier(
        supplier_repository, workflow_id=workflow_id,
        supplier_name=supplier_name, rfq_id=rfq_id,
    )
    if draft is not None and draft.recipient_email:
        return draft.recipient_email
    if master_repository is None:
        return None
    profile = master_repository.find_supplier_by_name(supplier_name)
    if profile is None:
        return None
    active = [contact for contact in profile.contacts if contact.active and contact.email]
    primary = next((contact for contact in active if contact.is_primary), None)
    operations = next((contact for contact in active if "operations" in contact.roles), None)
    selected = primary or operations or (active[0] if active else None)
    return None if selected is None else selected.email


def _shipment_lines(shipment) -> list[str]:
    pickup = shipment.pickup_address or " / ".join(filter(None, [
        shipment.pickup_city, shipment.pickup_area, shipment.pickup_postcode, shipment.pickup_country,
    ])) or "Yükleme yeri ayrıca teyit edilecek"
    delivery = shipment.delivery_address or " / ".join(filter(None, [
        shipment.delivery_city, shipment.delivery_area, shipment.delivery_postcode, shipment.delivery_country,
    ])) or "Teslimat yeri ayrıca teyit edilecek"
    lines = [f"Yükleme: {pickup}", f"Teslimat: {delivery}"]
    pickup_contact = " / ".join(filter(None, [shipment.pickup_contact_name, shipment.pickup_contact_phone]))
    if pickup_contact:
        lines.append(f"Yükleme irtibatı: {pickup_contact}")
    delivery_contact = " / ".join(filter(None, [shipment.delivery_contact_name, shipment.delivery_contact_phone]))
    if delivery_contact:
        lines.append(f"Teslimat irtibatı: {delivery_contact}")
    if shipment.cargo_ready_date:
        lines.append(f"Yük hazır / yükleme tarihi: {shipment.cargo_ready_date}")
    if shipment.required_delivery_date:
        lines.append(f"Beklenen teslim tarihi: {shipment.required_delivery_date}")
    if shipment.commodity:
        lines.append(f"Yük: {shipment.commodity}")
    if shipment.gross_weight_kg is not None:
        approx = "yaklaşık " if shipment.weight_is_approximate else ""
        lines.append(f"Ağırlık: {approx}{shipment.gross_weight_kg:g} kg")
    if shipment.equipment_type:
        lines.append(f"Araç / ekipman: {shipment.equipment_type}")
    if shipment.special_notes:
        lines.append(f"Özel not: {shipment.special_notes}")
    return lines


def _selected_supplier_body(*, mina_code: str, shipment, supplier_quote) -> str:
    lines = [
        "Merhaba,",
        "",
        f"{mina_code} referanslı yük için ilettiğiniz teklif kabul edilmiştir. Yükü sizinle organize edeceğiz.",
        f"Mutabık kalınan tedarikçi fiyatı: {supplier_quote.cost:g} {supplier_quote.currency}.",
        "",
        "Toplama / yükleme bilgileri:",
        *_shipment_lines(shipment),
        "",
        "Lütfen uygun araç bilgilerini mümkün olan en kısa sürede paylaşır mısınız?",
        "- Plaka",
        "- Sürücü adı soyadı",
        "- Sürücü telefon numarası",
        "- Gerekliyse araç / ekipman teyidi",
        "",
        "Teşekkür eder, iyi çalışmalar dileriz.",
    ]
    return "\n".join(lines)


def _closure_body(*, mina_code: str, closure_reason: str | None = None) -> str:
    reason = (closure_reason or "").strip()
    lines = [
        "Merhaba,",
        "",
        f"{mina_code} referanslı yük için desteğiniz ve teklifiniz için teşekkür ederiz.",
    ]
    if reason:
        lines.append(reason)
    else:
        lines.append("Bu yük için farklı bir çözümle ilerleme kararı aldık.")
    lines.extend([
        "Gösterdiğiniz ilgi için tekrar teşekkür ederiz.",
        "Önümüzdeki işlerimizde yeniden birlikte çalışmayı memnuniyetle isteriz.",
        "",
        "İyi çalışmalar dileriz.",
    ])
    return "\n".join(lines)


def _initial_status(mode: str, automatic_contact_blocked: bool) -> str:
    if automatic_contact_blocked:
        return "manual_required"
    if mode == "automatic":
        return "approval_required"  # upgraded to sent by the automatic dispatch pass
    if mode == "manual":
        return "manual_required"
    return "approval_required"


def _message_request(message: OperationStartMessage) -> OutboundMailRequest:
    return OutboundMailRequest(
        operation_id=f"operation-start:{message.message_id}",
        recipients=[message.recipient_email],
        subject=message.subject,
        body_text=message.body_text,
        purpose=("supplier_operation" if message.kind == "selected_supplier_confirmation" else "supplier_closure"),
        correlation_reference=message.mina_code,
        reference_metadata={
            "job_id": message.job_id,
            "mina_code": message.mina_code,
            "message_id": message.message_id,
            "supplier_name": message.supplier_name,
        },
    )


def _append_event(
    repository: MinaJobRepository, *, job_id: str, event_type: str,
    actor: str, occurred_at: datetime, resource_id: str, metadata: dict[str, Any],
) -> None:
    job = repository.get(job_id)
    if job is None:
        return
    repository.append_event(MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code, event_type=event_type,
        occurred_at=occurred_at, actor=actor, resource_type="operation_start_message",
        resource_id=resource_id, metadata=metadata,
    ))
    repository.save(job.model_copy(update={"updated_at": occurred_at}))


def _advance_selected_supplier_confirmation(
    *, mina_repository: MinaJobRepository, job_id: str, actor: str, occurred_at: datetime,
) -> None:
    job = mina_repository.get(job_id)
    if job is None or job.is_closed:
        return
    if job.stage == "operation_opened":
        transition_mina_job_stage(
            repository=mina_repository, mina_code=job.mina_code,
            target_stage="supplier_confirmation_pending", actor=actor,
            reason="selected_supplier_operation_email_sent", occurred_at=occurred_at,
        )


def _supplier_is_quoted(
    supplier_repository: SupplierRFQRepository, *, rfq_id: str | None, supplier_name: str,
    workflow_id: str,
) -> bool:
    draft = _draft_for_supplier(
        supplier_repository, workflow_id=workflow_id,
        supplier_name=supplier_name, rfq_id=rfq_id,
    )
    if draft is None:
        return False
    responses = supplier_repository.list_responses(draft.rfq_id)
    if not responses:
        return False
    latest = max(responses, key=lambda item: item.received_at)
    return latest.status == "quoted" and latest.is_price_usable


def build_operation_start_view(
    repository: OperationStartMessageRepository, *, job_id: str,
) -> dict[str, Any]:
    messages = sorted(repository.list_for_job(job_id), key=lambda item: (item.created_at, item.message_id))
    return {
        "job_id": job_id,
        "messages": [item.model_dump() for item in messages],
        "pending_count": sum(item.status in {"approval_required", "manual_required", "sending", "failed"} for item in messages),
        "sent_count": sum(item.status == "sent" for item in messages),
        "selected_supplier_message": next(
            (item.model_dump() for item in messages if item.kind == "selected_supplier_confirmation"), None
        ),
    }


def _dispatch_message(
    *, repository: OperationStartMessageRepository, mina_repository: MinaJobRepository,
    message: OperationStartMessage, sender: OutboundMailSender | None,
    actor: str, now: datetime,
) -> OperationStartMessage:
    reserved = repository.reserve_send(message.message_id, actor=actor, decided_at=now)
    if reserved is None:
        current = repository.get(message.message_id)
        if current is not None and current.status == "sent":
            return current
        raise OperationStartError("Operation-start message is already being decided or sent.")
    message = reserved
    try:
        if not is_supplier_business_time(now):
            resume_at = next_supplier_business_open(now)
            reason = f"Supplier operation email is outside communication hours; next opening is {resume_at.isoformat()}."
            return repository.save(message.model_copy(update={
                "status": "failed", "decision_reason": reason, "attention_reason": reason,
            }))
    except SupplierHolidayCalendarCoverageError as exc:
        reason = str(exc)
        return repository.save(message.model_copy(update={
            "status": "failed", "decision_reason": reason, "attention_reason": reason,
        }))
    delivery = dispatch_outbound_mail(_message_request(message), sender)
    if delivery.status == "delivery_outcome_unknown":
        unknown = message.model_copy(update={
            "status": "delivery_outcome_unknown",
            "decided_at": now,
            "decided_by": actor,
            "decision_reason": delivery.reason,
            "attention_reason": delivery.reason,
            "provider_name": delivery.provider_name,
        })
        return repository.save(unknown)
    if delivery.status != "sent":
        failed = message.model_copy(update={
            "status": "failed",
            "decided_at": now,
            "decided_by": actor,
            "decision_reason": delivery.reason,
            "attention_reason": delivery.reason,
        })
        return repository.save(failed)
    sent = message.model_copy(update={
        "status": "sent",
        "decided_at": now,
        "decided_by": actor,
        "decision_reason": "approved_and_sent",
        "sent_at": delivery.sent_at or now,
        "sent_by": actor,
        "provider_name": delivery.provider_name,
        "provider_message_id": delivery.provider_message_id,
        "attention_reason": None,
    })
    saved = repository.save(sent)
    event_type = (
        "selected_supplier_operation_email_sent"
        if saved.kind == "selected_supplier_confirmation"
        else "supplier_closure_email_sent"
    )
    _append_event(
        mina_repository, job_id=saved.job_id, event_type=event_type,
        actor=actor, occurred_at=saved.sent_at or now, resource_id=saved.message_id,
        metadata={"supplier_name": saved.supplier_name, "kind": saved.kind},
    )
    if saved.kind == "selected_supplier_confirmation":
        _advance_selected_supplier_confirmation(
            mina_repository=mina_repository, job_id=saved.job_id,
            actor=actor, occurred_at=saved.sent_at or now,
        )
    return saved


def reconcile_operation_start_message_delivery(
    *,
    repository: OperationStartMessageRepository,
    mina_repository: MinaJobRepository,
    message_id: str,
    outcome: str,
    actor: str,
    observed_sent_at: datetime | None = None,
    note: str | None = None,
    reconciled_at: datetime | None = None,
) -> OperationStartMessage:
    operator = _actor(actor)
    current_time = _now(reconciled_at)
    if outcome not in {"confirmed_sent", "confirmed_not_sent"}:
        raise ValueError("Operation-start reconciliation outcome is invalid.")
    if outcome == "confirmed_sent" and observed_sent_at is None:
        raise ValueError("Confirmed sent reconciliation requires the observed Outlook sent time.")
    sent_time = _now(observed_sent_at) if observed_sent_at is not None else None
    normalized_note = note.strip() if note and note.strip() else None
    with atomic_repository_transaction(repository, mina_repository):
        message = repository.get(message_id)
        if message is None:
            raise OperationStartError(f"Operation-start message not found: {message_id}")
        if message.status != "delivery_outcome_unknown":
            raise OperationStartError(
                "Operation-start reconciliation requires an unknown provider outcome."
            )
        evidence = OperationStartSendReconciliationEvidence(
            outcome=outcome, reconciled_by=operator, reconciled_at=current_time,
            observed_sent_at=sent_time, note=normalized_note,
        )
        if outcome == "confirmed_not_sent":
            return repository.save(message.model_copy(update={
                "status": "failed",
                "decision_reason": "operator_reconciled_not_sent",
                "attention_reason": normalized_note or "Outlook Sent Items confirmed that the message was not sent.",
                "send_reconciliation_evidence": [*message.send_reconciliation_evidence, evidence],
            }))
        sent = repository.save(message.model_copy(update={
            "status": "sent",
            "decision_reason": "operator_reconciled_sent",
            "attention_reason": None,
            "sent_at": sent_time,
            "sent_by": operator,
            "send_reconciliation_evidence": [*message.send_reconciliation_evidence, evidence],
        }))
        event_type = (
            "selected_supplier_operation_email_sent"
            if sent.kind == "selected_supplier_confirmation"
            else "supplier_closure_email_sent"
        )
        _append_event(
            mina_repository, job_id=sent.job_id, event_type=event_type,
            actor=operator, occurred_at=sent_time, resource_id=sent.message_id,
            metadata={"supplier_name": sent.supplier_name, "kind": sent.kind, "reconciled": True},
        )
        if sent.kind == "selected_supplier_confirmation":
            _advance_selected_supplier_confirmation(
                mina_repository=mina_repository, job_id=sent.job_id,
                actor=operator, occurred_at=sent_time,
            )
        return sent


def start_operation(
    *, mina_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    supplier_repository: SupplierRFQRepository,
    master_repository: MasterDataRepository | None,
    message_repository: OperationStartMessageRepository,
    sender: OutboundMailSender | None,
    job_id: str,
    actor: str,
    closure_reason: str | None = None,
    now: datetime | None = None,
    allow_automatic_delivery: bool = True,
) -> dict[str, Any]:
    current = _now(now)
    operator = _actor(actor)
    existing = message_repository.list_for_job(job_id)
    if existing:
        return build_operation_start_view(message_repository, job_id=job_id)
    job = mina_repository.get(job_id)
    if job is None:
        raise OperationStartError(f"MINA job not found: {job_id}")
    if job.stage != "accepted":
        raise OperationStartError("Operation can start only after the customer quote is accepted.")
    if not job.quote_case_id:
        raise OperationStartError("Accepted MINA job has no linked quote case.")
    case = quote_case_repository.get(job.quote_case_id)
    if case is None or case.supplier_quote_selection_decision is None or case.supplier_quote is None:
        raise OperationStartError("Operation start requires durable selected-supplier and supplier-price evidence.")
    selection = case.supplier_quote_selection_decision
    selected_name = selection.selected_supplier
    if case.supplier_quote.supplier_name != selected_name:
        raise OperationStartError("Selected supplier does not match the accepted supplier quote.")
    workflow_id = job.supplier_rfq_workflow_id or case.supplier_rfq_workflow_id
    if not workflow_id:
        raise OperationStartError("Operation start requires the linked supplier RFQ workflow.")
    selected_recipient = _recipient_for_supplier(
        master_repository=master_repository, supplier_repository=supplier_repository,
        workflow_id=workflow_id, supplier_name=selected_name,
        rfq_id=selection.selected_rfq_id,
    )
    if not selected_recipient:
        raise OperationStartError("Selected supplier has no verified email recipient.")

    warnings: list[str] = []
    selected_rel = _relationship(master_repository, selected_name)
    selected_mode = "approval_required" if selected_rel is None else selected_rel.operation_email_mode
    selected_blocked = False if selected_rel is None else selected_rel.automatic_contact_blocked
    selected_message = OperationStartMessage(
        message_id=_message_id(job_id=job.job_id, kind="selected_supplier_confirmation", supplier_name=selected_name),
        job_id=job.job_id, mina_code=job.mina_code, supplier_name=selected_name,
        recipient_email=selected_recipient, kind="selected_supplier_confirmation",
        outbound_mode=selected_mode,
        subject=f"{job.mina_code} - Yük onayı ve toplama talimatı",
        body_text=_selected_supplier_body(
            mina_code=job.mina_code, shipment=job.shipment, supplier_quote=case.supplier_quote,
        ),
        status=_initial_status(selected_mode, selected_blocked),
        created_at=current, created_by=operator,
        attention_reason=("supplier_automatic_contact_blocked" if selected_blocked else None),
    )
    messages = [selected_message]
    for alternative in selection.rejected_alternatives:
        if alternative.supplier_name == selected_name:
            continue
        if not _supplier_is_quoted(
            supplier_repository, rfq_id=alternative.rfq_id,
            supplier_name=alternative.supplier_name, workflow_id=workflow_id,
        ):
            continue
        recipient = _recipient_for_supplier(
            master_repository=master_repository, supplier_repository=supplier_repository,
            workflow_id=workflow_id, supplier_name=alternative.supplier_name,
            rfq_id=alternative.rfq_id,
        )
        if not recipient:
            warnings.append(f"closure_recipient_missing:{alternative.supplier_name}")
            continue
        rel = _relationship(master_repository, alternative.supplier_name)
        mode = "approval_required" if rel is None else rel.closure_email_mode
        blocked = False if rel is None else rel.automatic_contact_blocked
        messages.append(OperationStartMessage(
            message_id=_message_id(job_id=job.job_id, kind="supplier_closure", supplier_name=alternative.supplier_name),
            job_id=job.job_id, mina_code=job.mina_code,
            supplier_name=alternative.supplier_name, recipient_email=recipient,
            kind="supplier_closure", outbound_mode=mode,
            subject=f"{job.mina_code} - Teklifiniz için teşekkürler",
            body_text=_closure_body(mina_code=job.mina_code, closure_reason=closure_reason),
            status=_initial_status(mode, blocked), created_at=current, created_by=operator,
            attention_reason=("supplier_automatic_contact_blocked" if blocked else None),
        ))

    with atomic_repository_transaction(message_repository, mina_repository):
        concurrent_existing = message_repository.list_for_job(job_id)
        if concurrent_existing:
            return build_operation_start_view(message_repository, job_id=job_id)
        transition_mina_job_stage(
            repository=mina_repository, mina_code=job.mina_code,
            target_stage="operation_opened", actor=operator,
            reason="customer_accepted_supplier_selected", occurred_at=current,
        )
        for message in messages:
            message_repository.save(message)
        _append_event(
            mina_repository, job_id=job.job_id, event_type="operation_start_prepared",
            actor=operator, occurred_at=current, resource_id=job.job_id,
            metadata={
                "selected_supplier": selected_name,
                "message_count": len(messages),
                "closure_message_count": len(messages) - 1,
            },
        )

    # External delivery is intentionally outside the database transaction.
    # Shadow runtime may prepare automatic messages but must never dispatch them.
    if not allow_automatic_delivery:
        view = build_operation_start_view(message_repository, job_id=job_id)
        view["warnings"] = [*warnings, "outbound_shadow_mode_delivery_blocked"]
        return view
    for message in list(message_repository.list_for_job(job_id)):
        if message.outbound_mode != "automatic" or message.status != "approval_required":
            continue
        try:
            _dispatch_message(
                repository=message_repository, mina_repository=mina_repository,
                message=message, sender=sender, actor=operator, now=current,
            )
        except OperationStartError as exc:
            message_repository.save(message.model_copy(update={
                "attention_reason": str(exc),
            }))
    view = build_operation_start_view(message_repository, job_id=job_id)
    view["warnings"] = warnings
    return view


def decide_operation_start_message(
    *, repository: OperationStartMessageRepository,
    mina_repository: MinaJobRepository,
    sender: OutboundMailSender | None,
    message_id: str,
    decision: str,
    actor: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> OperationStartMessage:
    current = _now(now)
    operator = _actor(actor)
    message = repository.get(message_id)
    if message is None:
        raise OperationStartError(f"Operation-start message not found: {message_id}")
    if message.status == "sent":
        return message
    if message.status == "rejected":
        raise OperationStartError("Rejected operation-start message cannot be sent.")
    if message.status == "sending":
        raise OperationStartError(
            "Operation-start send is currently reserved; wait for provider outcome before another decision."
        )
    if message.status == "delivery_outcome_unknown":
        raise OperationStartError(
            "Operation-start provider outcome is unknown; reconcile Outlook Sent Items before another decision."
        )
    if decision == "reject":
        rejection = (reason or "").strip()
        if not rejection:
            raise OperationStartError("Rejecting an operation-start message requires a reason.")
        saved = repository.save(message.model_copy(update={
            "status": "rejected", "decided_at": current, "decided_by": operator,
            "decision_reason": rejection,
        }))
        _append_event(
            mina_repository, job_id=saved.job_id, event_type="operation_start_message_rejected",
            actor=operator, occurred_at=current, resource_id=saved.message_id,
            metadata={"supplier_name": saved.supplier_name, "kind": saved.kind, "reason": rejection},
        )
        return saved
    if decision != "approve":
        raise OperationStartError("Operation-start decision must be approve or reject.")
    return _dispatch_message(
        repository=repository, mina_repository=mina_repository, message=message,
        sender=sender, actor=operator, now=current,
    )


def record_operation_start_message_manually_sent(
    *, repository: OperationStartMessageRepository,
    mina_repository: MinaJobRepository,
    message_id: str,
    actor: str,
    now: datetime | None = None,
) -> OperationStartMessage:
    current = _now(now)
    operator = _actor(actor)
    message = repository.get(message_id)
    if message is None:
        raise OperationStartError(f"Operation-start message not found: {message_id}")
    if message.status == "sent":
        return message
    if message.status == "rejected":
        raise OperationStartError("Rejected operation-start message cannot be recorded as sent.")
    if message.status == "delivery_outcome_unknown":
        raise OperationStartError(
            "Operation-start provider outcome is unknown; use send reconciliation instead of manual sent evidence."
        )
    if (
        message.status == "sending"
        and message.decided_at is not None
        and current - _now(message.decided_at) < timedelta(minutes=10)
    ):
        raise OperationStartError(
            "Provider send reservation is still fresh; wait before recording external send evidence."
        )
    saved = repository.save(message.model_copy(update={
        "status": "sent", "decided_at": current, "decided_by": operator,
        "decision_reason": "manual_external_send_recorded",
        "sent_at": current, "sent_by": operator,
        "attention_reason": None,
    }))
    event_type = (
        "selected_supplier_operation_email_sent"
        if saved.kind == "selected_supplier_confirmation" else "supplier_closure_email_sent"
    )
    _append_event(
        mina_repository, job_id=saved.job_id, event_type=event_type,
        actor=operator, occurred_at=current, resource_id=saved.message_id,
        metadata={"supplier_name": saved.supplier_name, "kind": saved.kind, "send_mode": "manual_external"},
    )
    if saved.kind == "selected_supplier_confirmation":
        _advance_selected_supplier_confirmation(
            mina_repository=mina_repository, job_id=saved.job_id, actor=operator, occurred_at=current,
        )
    return saved
