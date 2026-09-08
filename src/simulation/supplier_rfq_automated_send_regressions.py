from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from pathlib import Path
from tempfile import TemporaryDirectory

import src.api as controlled_api
from src.core.mail import MailSendResult
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_rfq import SupplierRFQDraft
from src.core.supplier_rfq_lifecycle import reconcile_supplier_rfq_send
from src.workflow.mail_delivery import send_supplier_rfq_via_mail


class _Sender:
    def __init__(self, status: str = "sent", complete_metadata: bool = True):
        self.status = status
        self.complete_metadata = complete_metadata
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        if self.status == "delivery_outcome_unknown":
            return MailSendResult(
                operation_id=request.operation_id,
                status="delivery_outcome_unknown",
                reason="synthetic uncertain provider outcome",
                provider_name="synthetic_provider",
            )
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
            provider_name="synthetic_provider" if self.complete_metadata else None,
            provider_message_id="supplier-provider-ref-1" if self.complete_metadata else None,
            sent_at=datetime(2026, 9, 1, 14, 0, 0),
        )



class _BlockingSender(_Sender):
    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def send(self, request):
        self.calls.append(request)
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("blocking sender timed out")
        return MailSendResult(
            operation_id=request.operation_id, status="sent", reason="accepted",
            provider_name="synthetic_provider", provider_message_id="supplier-race-1",
            sent_at=datetime(2026, 9, 1, 14, 30, 0),
        )

def _approved_draft(rfq_id: str = "rfq-auto-send") -> SupplierRFQDraft:
    return SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id="workflow-auto-send",
        supplier_name="Carrier",
        priority=1,
        recipient_email="supplier@example.test",
        subject=f"[MINAI-RFQ:{rfq_id}] Test",
        body="Synthetic RFQ body",
        status="approved",
        approved_by="Tan",
        approved_at=datetime(2026, 9, 1, 13, 55, 0),
    )


def _repo(root: Path, run_id: str):
    store = SQLitePilotStore(root / "pilot.sqlite3", run_id=run_id)
    return SQLiteSupplierRFQRepository(store)


def evaluate_supplier_rfq_automated_send_regressions() -> dict:
    failures = []
    route = "/supplier-rfqs/rfq-1/send"
    if not route_allowed("POST", route):
        failures.append("controlled supplier RFQ send route is not pilot-allowed")
    if not route_allowed("POST", "/supplier-rfqs/rfq-1/send-reconciliation"):
        failures.append("controlled supplier RFQ reconciliation route is not pilot-allowed")
    route_paths = {r.path for r in controlled_api.app.routes if hasattr(r, "path")}
    if "/supplier-rfqs/{rfq_id}/send" not in route_paths:
        failures.append("supplier RFQ send API route is not exposed")
    if "/supplier-rfqs/{rfq_id}/send-reconciliation" not in route_paths:
        failures.append("supplier RFQ reconciliation API route is not exposed")

    with TemporaryDirectory(prefix="minai-supplier-auto-send-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-auto-send")
        draft = _approved_draft()
        repo.save_drafts([draft])
        sender = _Sender()
        result = send_supplier_rfq_via_mail(
            repository=repo,
            rfq_id=draft.rfq_id,
            sender=sender,
        )
        durable = repo.get_draft(draft.rfq_id)
        evidence = repo.list_automated_sent_evidence(draft.rfq_id)
        if result.delivery.status != "sent" or durable is None or durable.status != "awaiting_response":
            failures.append("provider-confirmed supplier send did not advance lifecycle")
        if result.automated_sent_evidence is None or len(evidence) != 1:
            failures.append("supplier automated send evidence was not durable")
        elif (
            evidence[0].provider_message_id != "supplier-provider-ref-1"
            or evidence[0].recipient_email != "supplier@example.test"
        ):
            failures.append("supplier automated evidence lost provider or recipient metadata")
        original_repo = controlled_api.supplier_rfq_repository
        try:
            controlled_api.supplier_rfq_repository = repo
            api_read = controlled_api.get_supplier_rfq(draft.rfq_id)
        finally:
            controlled_api.supplier_rfq_repository = original_repo
        if len(api_read.get("automated_sent_evidence", [])) != 1:
            failures.append("supplier automated evidence is not visible on RFQ readback")

        duplicate = send_supplier_rfq_via_mail(
            repository=repo,
            rfq_id=draft.rfq_id,
            sender=sender,
        )
        if duplicate.delivery.status != "rejected_before_provider":
            failures.append("duplicate supplier send was not rejected before provider")
        if len(sender.calls) != 1 or len(repo.list_automated_sent_evidence(draft.rfq_id)) != 1:
            failures.append("duplicate supplier send reached provider or duplicated evidence")

        original_repo = controlled_api.supplier_rfq_repository
        original_sender = controlled_api.outbound_mail_sender
        try:
            controlled_api.supplier_rfq_repository = repo
            controlled_api.outbound_mail_sender = sender
            try:
                controlled_api.send_supplier_rfq_endpoint(draft.rfq_id)
            except controlled_api.HTTPException as exc:
                if exc.status_code != 409:
                    failures.append("duplicate supplier send API did not return lifecycle conflict")
            else:
                failures.append("duplicate supplier send API returned success")
        finally:
            controlled_api.supplier_rfq_repository = original_repo
            controlled_api.outbound_mail_sender = original_sender

    with TemporaryDirectory(prefix="minai-supplier-auto-race-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-auto-race")
        draft = _approved_draft("rfq-concurrent-send")
        repo.save_drafts([draft])
        sender = _BlockingSender()
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(
                send_supplier_rfq_via_mail, repository=repo, rfq_id=draft.rfq_id,
                sender=sender, triggered_by="Ops A",
            )
            if not sender.entered.wait(timeout=5):
                failures.append("concurrent supplier RFQ first send did not reach provider")
                sender.release.set()
            second = send_supplier_rfq_via_mail(
                repository=repo, rfq_id=draft.rfq_id, sender=sender, triggered_by="Ops B",
            )
            if second.delivery.status != "rejected_before_provider":
                failures.append("concurrent supplier RFQ duplicate was not rejected before provider")
            sender.release.set()
            first.result(timeout=5)
        durable = repo.get_draft(draft.rfq_id)
        if len(sender.calls) != 1 or durable is None or durable.status != "awaiting_response" or len(repo.list_automated_sent_evidence(draft.rfq_id)) != 1:
            failures.append("concurrent supplier RFQ send did not reserve exactly one provider delivery")

    with TemporaryDirectory(prefix="minai-supplier-auto-fail-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-auto-fail")
        draft = _approved_draft("rfq-provider-fail")
        repo.save_drafts([draft])
        failed = send_supplier_rfq_via_mail(
            repository=repo,
            rfq_id=draft.rfq_id,
            sender=_Sender("failed"),
        )
        durable = repo.get_draft(draft.rfq_id)
        if failed.delivery.status != "failed" or durable is None or durable.status != "approved":
            failures.append("provider failure advanced supplier RFQ lifecycle")
        if repo.list_automated_sent_evidence(draft.rfq_id):
            failures.append("provider failure created supplier automated evidence")

        original_repo = controlled_api.supplier_rfq_repository
        original_sender = controlled_api.outbound_mail_sender
        try:
            controlled_api.supplier_rfq_repository = repo
            controlled_api.outbound_mail_sender = _Sender("failed")
            try:
                controlled_api.send_supplier_rfq_endpoint(draft.rfq_id)
            except controlled_api.HTTPException as exc:
                if exc.status_code != 503:
                    failures.append("provider failure API did not return service unavailable")
            else:
                failures.append("provider failure API returned success")
        finally:
            controlled_api.supplier_rfq_repository = original_repo
            controlled_api.outbound_mail_sender = original_sender

    with TemporaryDirectory(prefix="minai-supplier-auto-metadata-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-auto-metadata")
        draft = _approved_draft("rfq-missing-metadata")
        repo.save_drafts([draft])
        incomplete = send_supplier_rfq_via_mail(
            repository=repo,
            rfq_id=draft.rfq_id,
            sender=_Sender(complete_metadata=False),
        )
        durable = repo.get_draft(draft.rfq_id)
        if (
            incomplete.delivery.status != "delivery_outcome_unknown"
            or durable is None
            or durable.status != "send_outcome_unknown"
        ):
            failures.append("missing provider metadata did not lock Supplier RFQ for reconciliation")
        if repo.list_automated_sent_evidence(draft.rfq_id):
            failures.append("missing provider metadata created supplier evidence")

    with TemporaryDirectory(prefix="minai-supplier-reconcile-not-sent-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-reconcile-not-sent")
        draft = _approved_draft("rfq-reconcile-not-sent")
        repo.save_drafts([draft])
        send_supplier_rfq_via_mail(
            repository=repo, rfq_id=draft.rfq_id,
            sender=_Sender("delivery_outcome_unknown"), triggered_by="Ops",
        )
        reconciled = reconcile_supplier_rfq_send(
            repo, draft.rfq_id, outcome="confirmed_not_sent", reconciled_by="Ops",
            note="Checked Outlook Sent Items.",
        )
        if (reconciled.status != "approved"
                or reconciled.send_reconciliation_evidence[-1].outcome != "confirmed_not_sent"):
            failures.append("confirmed-not-sent supplier RFQ reconciliation did not reopen send")
        retry = send_supplier_rfq_via_mail(
            repository=repo, rfq_id=draft.rfq_id, sender=_Sender("sent"), triggered_by="Ops",
        )
        if retry.delivery.status != "sent":
            failures.append("supplier RFQ could not retry after confirmed-not-sent reconciliation")

    with TemporaryDirectory(prefix="minai-supplier-reconcile-sent-") as temp_dir:
        repo = _repo(Path(temp_dir), "supplier-reconcile-sent")
        draft = _approved_draft("rfq-reconcile-sent")
        repo.save_drafts([draft])
        send_supplier_rfq_via_mail(
            repository=repo, rfq_id=draft.rfq_id,
            sender=_Sender("delivery_outcome_unknown"), triggered_by="Ops",
        )
        observed = datetime(2026, 9, 1, 14, 5, 0, tzinfo=timezone.utc)
        reconciled = reconcile_supplier_rfq_send(
            repo, draft.rfq_id, outcome="confirmed_sent", reconciled_by="Ops",
            observed_sent_at=observed,
        )
        if (reconciled.status != "awaiting_response" or reconciled.sent_at != observed
                or reconciled.send_reconciliation_evidence[-1].reconciled_by != "Ops"):
            failures.append("confirmed-sent supplier RFQ reconciliation lost operator evidence")
        duplicate = send_supplier_rfq_via_mail(
            repository=repo, rfq_id=draft.rfq_id, sender=_Sender("sent"), triggered_by="Ops",
        )
        if duplicate.delivery.status != "rejected_before_provider":
            failures.append("confirmed-sent supplier RFQ reconciliation allowed duplicate retry")

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_supplier_rfq_automated_send_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Supplier RFQ automated send surface")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
