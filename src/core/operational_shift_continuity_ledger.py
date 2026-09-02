from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.operational_shift_close_attestation import (
    evaluate_operational_shift_close_receipt_status,
)
from src.core.operational_shift_close_receipt_repository import (
    OperationalShiftCloseReceiptRepository,
)
from src.core.operational_shift_open_acceptance import (
    evaluate_operational_shift_open_acceptance_status,
)
from src.core.operational_shift_open_acceptance_receipt_repository import (
    OperationalShiftOpenAcceptanceReceiptRepository,
)
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository

SHIFT_CONTINUITY_LEDGER_LIMIT = 20


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return (
        current.replace(tzinfo=timezone.utc)
        if current.tzinfo is None
        else current.astimezone(timezone.utc)
    )


def _operational_state_key(close) -> tuple:
    if close.state_event_id is None:
        return ("receipt", close.receipt_id)
    return (
        "durable_state",
        close.state_event_id,
        close.pending_work_count,
        close.critical_pending_count,
        close.active_assignment_count,
        close.expired_assignment_count,
        close.incomplete_handoff_count,
        close.critical_uncovered_count,
    )


def _group_close_cycles(closes, acceptances) -> list[list]:
    ordered = sorted(closes, key=lambda item: (item.attested_at, item.receipt_id))
    acceptances_by_close: dict[str, list] = {}
    for item in acceptances:
        acceptances_by_close.setdefault(item.source_close_receipt_id, []).append(item)
    cycles: list[list] = []
    for close in ordered:
        if not cycles:
            cycles.append([close])
            continue
        current_cycle = cycles[-1]
        same_state = _operational_state_key(current_cycle[-1]) == _operational_state_key(close)
        prior_acceptance = any(
            acceptance.accepted_at < close.attested_at
            for prior_close in current_cycle
            for acceptance in acceptances_by_close.get(prior_close.receipt_id, [])
        )
        if same_state and not prior_acceptance:
            current_cycle.append(close)
        else:
            cycles.append([close])
    return cycles


def build_operational_shift_continuity_ledger(
    *,
    receipt_repository: OperationalShiftCloseReceiptRepository,
    acceptance_repository: OperationalShiftOpenAcceptanceReceiptRepository,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository,
    proposal_repository,
    supplier_repository,
    approval_repository,
    quote_case_repository,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc(now)
    closes = receipt_repository.list_all()
    acceptances = acceptance_repository.list_all()
    retained_close_ids = {item.receipt_id for item in closes}
    unmatched_acceptance_count = sum(
        1 for item in acceptances if item.source_close_receipt_id not in retained_close_ids
    )
    grouped_acceptances: dict[str, list] = {}
    for item in acceptances:
        grouped_acceptances.setdefault(item.source_close_receipt_id, []).append(item)

    cycles = list(reversed(_group_close_cycles(closes, acceptances)))
    listed_cycles = cycles[:SHIFT_CONTINUITY_LEDGER_LIMIT]
    items: list[dict[str, Any]] = []
    historical_gap_count = 0
    temporal_integrity_error_count = 0
    open_cycle_count = 0
    complete_cycle_count = 0
    stale_cycle_count = 0

    for index, cycle_closes in enumerate(listed_cycles):
        anchor = max(cycle_closes, key=lambda item: (item.attested_at, item.receipt_id))
        cycle_close_ids = {item.receipt_id for item in cycle_closes}
        candidates = sorted(
            (
                item
                for close_id in cycle_close_ids
                for item in grouped_acceptances.get(close_id, [])
            ),
            key=lambda item: (item.accepted_at, item.receipt_id),
        )
        valid = [item for item in candidates if item.accepted_at >= anchor.attested_at]
        invalid_count = len(candidates) - len(valid)
        has_newer_cycle = index > 0

        if valid:
            completion_status = "complete"
            complete_cycle_count += 1
        elif has_newer_cycle:
            completion_status = "gap"
            historical_gap_count += 1
        else:
            completion_status = "open"
            open_cycle_count += 1

        temporal_integrity_error_count += invalid_count
        current_acceptance_count: int | None = None
        if has_newer_cycle:
            evidence_freshness = "historical"
        elif valid:
            current_acceptance_count = 0
            for acceptance in valid:
                status = evaluate_operational_shift_open_acceptance_status(
                    acceptance,
                    receipt_repository=receipt_repository,
                    assignment_repository=assignment_repository,
                    attachment_repository=attachment_repository,
                    proposal_repository=proposal_repository,
                    supplier_repository=supplier_repository,
                    approval_repository=approval_repository,
                    quote_case_repository=quote_case_repository,
                    now=current,
                )
                if status["current_for_open_state"]:
                    current_acceptance_count += 1
            evidence_freshness = "current" if current_acceptance_count else "stale"
        else:
            close_status = evaluate_operational_shift_close_receipt_status(
                anchor,
                assignment_repository=assignment_repository,
                attachment_repository=attachment_repository,
                proposal_repository=proposal_repository,
                supplier_repository=supplier_repository,
                approval_repository=approval_repository,
                quote_case_repository=quote_case_repository,
                now=current,
            )
            evidence_freshness = close_status["current_status"]

        if evidence_freshness == "stale":
            stale_cycle_count += 1

        attention_codes: list[str] = []
        if completion_status == "open":
            attention_codes.append("latest_close_awaiting_acceptance")
        elif completion_status == "gap":
            attention_codes.append("historical_close_without_acceptance")
        if invalid_count:
            attention_codes.append("acceptance_temporal_integrity_error")

        items.append({
            "anchor_close_receipt_id": anchor.receipt_id,
            "first_close_attested_at": min(item.attested_at for item in cycle_closes),
            "last_close_attested_at": anchor.attested_at,
            "close_attestation_count": len(cycle_closes),
            "completion_status": completion_status,
            "evidence_freshness": evidence_freshness,
            "acceptance_count": len(valid),
            "first_accepted_at": valid[0].accepted_at if valid else None,
            "last_accepted_at": valid[-1].accepted_at if valid else None,
            "current_acceptance_count": current_acceptance_count,
            "invalid_acceptance_count": invalid_count,
            "attention_codes": attention_codes,
        })

    audit_attention_codes: list[str] = []
    if not cycles:
        audit_attention_codes.append("no_shift_close_evidence")
    if open_cycle_count:
        audit_attention_codes.append("latest_close_awaiting_acceptance")
    if historical_gap_count:
        audit_attention_codes.append("historical_continuity_gap_present")
    if temporal_integrity_error_count:
        audit_attention_codes.append("acceptance_temporal_integrity_error")

    latest = items[0] if items else None
    return {
        "generated_at": current,
        "scope": "organization_shift_continuity",
        "ledger_status": "attention" if audit_attention_codes else "clear",
        "audit_attention_required": bool(audit_attention_codes),
        "audit_attention_codes": audit_attention_codes,
        "current_cycle": (
            None
            if latest is None
            else {
                "completion_status": latest["completion_status"],
                "evidence_freshness": latest["evidence_freshness"],
                "last_close_attested_at": latest["last_close_attested_at"],
                "acceptance_count": latest["acceptance_count"],
            }
        ),
        "counts": {
            "retained_close_receipt_count": len(closes),
            "retained_cycle_count": len(cycles),
            "listed_cycle_count": len(items),
            "listed_complete_cycle_count": complete_cycle_count,
            "listed_open_cycle_count": open_cycle_count,
            "listed_historical_gap_count": historical_gap_count,
            "listed_stale_cycle_count": stale_cycle_count,
            "listed_temporal_integrity_error_count": temporal_integrity_error_count,
            "retention_boundary_unmatched_acceptance_count": unmatched_acceptance_count,
        },
        "items": items,
        "authority": {
            "ledger_is_read_only_audit_projection": True,
            "ledger_does_not_open_or_close_shift": True,
            "ledger_does_not_assign_or_transfer_work": True,
            "stale_evidence_is_not_by_itself_a_continuity_gap": True,
            "existing_assignment_and_workflow_guards_remain_authoritative": True,
        },
    }
