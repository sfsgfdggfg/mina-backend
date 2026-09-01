from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import src.api as controlled_api
from src.core.mail import MailSendResult
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_rfq import SupplierRFQDraft
from src.workflow.mail_delivery import send_supplier_rfq_via_mail


class _Sender:
    def __init__(self, status: str = "sent", complete_metadata: bool = True):
        self.status = status
        self.complete_metadata = complete_metadata
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
            provider_name="synthetic_provider" if self.complete_metadata else None,
            provider_message_id="supplier-provider-ref-1" if self.complete_metadata else None,
            sent_at=datetime(2026, 9, 1, 14, 0, 0),
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
    route_paths = {r.path for r in controlled_api.app.routes if hasattr(r, "path")}
    if "/supplier-rfqs/{rfq_id}/send" not in route_paths:
        failures.append("supplier RFQ send API route is not exposed")

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
        if incomplete.delivery.status != "failed" or durable is None or durable.status != "approved":
            failures.append("missing provider metadata advanced supplier RFQ lifecycle")
        if repo.list_automated_sent_evidence(draft.rfq_id):
            failures.append("missing provider metadata created supplier evidence")

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
