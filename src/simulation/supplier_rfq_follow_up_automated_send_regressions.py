from __future__ import annotations

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import HTTPException

import src.api as controlled_api
from src.core.mail import MailSendResult
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQFollowUpDraft
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQTransitionError,
    record_supplier_rfq_follow_up_manually_sent,
)
from src.workflow.mail_delivery import send_supplier_rfq_follow_up_via_mail


class _Sender:
    def __init__(self, status: str = "sent"):
        self.status = status
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        if self.status != "sent":
            return MailSendResult(
                operation_id=request.operation_id,
                status="failed",
                reason="synthetic provider failure",
            )
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="accepted",
            provider_name="synthetic_provider",
            provider_message_id="follow-up-provider-ref-1",
            sent_at=datetime(2026, 9, 1, 15, 0, 0),
        )


def _repo(root: Path, run_id: str):
    return SQLiteSupplierRFQRepository(
        SQLitePilotStore(root / "pilot.sqlite3", run_id=run_id)
    )


def _seed(repo, suffix: str = "1"):
    rfq_id = f"rfq-follow-up-{suffix}"
    follow_up_id = f"follow-up-{suffix}"
    repo.save_drafts([
        SupplierRFQDraft(
            rfq_id=rfq_id,
            workflow_id="workflow-follow-up",
            supplier_name="Carrier",
            priority=1,
            recipient_email="supplier@example.test",
            subject="RFQ",
            body="RFQ body",
            status="clarification_required",
        )
    ])
    follow_up = SupplierRFQFollowUpDraft(
        follow_up_id=follow_up_id,
        rfq_id=rfq_id,
        workflow_id="workflow-follow-up",
        sequence_number=1,
        recipient_email="supplier@example.test",
        subject=f"[MINAI-RFQ:{rfq_id}] Transit süresi teyidi",
        body="Lütfen transit süresini teyit eder misiniz?",
        status="approved",
        approved_by="Tan",
        approved_at=datetime(2026, 9, 1, 14, 55, 0),
    )
    repo.save_follow_up_drafts([follow_up])
    return follow_up


def evaluate_supplier_rfq_follow_up_automated_send_regressions() -> dict:
    failures: list[str] = []
    route = "/supplier-rfq-follow-ups/follow-up-1/send"
    if not route_allowed("POST", route):
        failures.append("controlled follow-up send route is not pilot-allowed")
    paths = {r.path for r in controlled_api.app.routes if hasattr(r, "path")}
    if "/supplier-rfq-follow-ups/{follow_up_id}/send" not in paths:
        failures.append("follow-up send API route is not exposed")

    with TemporaryDirectory(prefix="minai-follow-up-auto-") as temp_dir:
        repo = _repo(Path(temp_dir), "follow-up-auto")
        follow_up = _seed(repo)
        sender = _Sender()
        result = send_supplier_rfq_follow_up_via_mail(
            repository=repo,
            follow_up_id=follow_up.follow_up_id,
            sender=sender,
        )
        durable = repo.get_follow_up_draft(follow_up.follow_up_id)
        evidence = repo.list_follow_up_automated_sent_evidence(follow_up.follow_up_id)
        if result.delivery.status != "sent" or durable is None or durable.status != "awaiting_response":
            failures.append("provider-confirmed follow-up send did not advance lifecycle")
        if len(evidence) != 1 or evidence[0].provider_message_id != "follow-up-provider-ref-1":
            failures.append("follow-up automated send evidence was not durable")
        if result.mail_request is None or result.mail_request.correlation_reference != f"MINAI-RFQ:{follow_up.rfq_id}":
            failures.append("follow-up send lost parent RFQ correlation reference")

        original_repo = controlled_api.supplier_rfq_repository
        try:
            controlled_api.supplier_rfq_repository = repo
            readback = controlled_api.get_supplier_rfq_follow_up(follow_up.follow_up_id)
        finally:
            controlled_api.supplier_rfq_repository = original_repo
        if len(readback.get("automated_sent_evidence", [])) != 1:
            failures.append("follow-up automated evidence is not visible on readback")

        duplicate = send_supplier_rfq_follow_up_via_mail(
            repository=repo,
            follow_up_id=follow_up.follow_up_id,
            sender=sender,
        )
        if duplicate.delivery.status != "rejected_before_provider" or len(sender.calls) != 1:
            failures.append("duplicate follow-up send reached provider")
        try:
            record_supplier_rfq_follow_up_manually_sent(
                repo, follow_up.follow_up_id, recorded_by="Tan"
            )
        except SupplierRFQTransitionError:
            pass
        else:
            failures.append("manual follow-up evidence was allowed after automated send")

    with TemporaryDirectory(prefix="minai-follow-up-fail-") as temp_dir:
        repo = _repo(Path(temp_dir), "follow-up-fail")
        follow_up = _seed(repo, "failure")
        failed = send_supplier_rfq_follow_up_via_mail(
            repository=repo,
            follow_up_id=follow_up.follow_up_id,
            sender=_Sender("failed"),
        )
        durable = repo.get_follow_up_draft(follow_up.follow_up_id)
        if failed.delivery.status != "failed" or durable is None or durable.status != "approved":
            failures.append("provider failure advanced follow-up lifecycle")
        if repo.list_follow_up_automated_sent_evidence(follow_up.follow_up_id):
            failures.append("provider failure created follow-up automated evidence")

        original_repo = controlled_api.supplier_rfq_repository
        original_sender = controlled_api.outbound_mail_sender
        try:
            controlled_api.supplier_rfq_repository = repo
            controlled_api.outbound_mail_sender = _Sender("failed")
            try:
                controlled_api.send_supplier_rfq_follow_up_endpoint(follow_up.follow_up_id)
            except HTTPException as exc:
                if exc.status_code != 503:
                    failures.append("provider failure did not map to HTTP 503")
            else:
                failures.append("provider failure returned HTTP success")
        finally:
            controlled_api.supplier_rfq_repository = original_repo
            controlled_api.outbound_mail_sender = original_sender

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_supplier_rfq_follow_up_automated_send_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Supplier RFQ follow-up automated send surface")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
