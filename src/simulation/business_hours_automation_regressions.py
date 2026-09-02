from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.business_calendar import (
    SUPPLIER_HOLIDAY_COVERAGE_YEARS,
    SupplierHolidayCalendarCoverageError,
    add_supplier_business_minutes,
    is_supplier_business_time,
    supplier_calendar_metadata,
)
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import MailSendResult
from src.core.models import Shipment
from src.core.operational_work_queue import build_operational_work_queue
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.automation_scheduler import run_automation_tick
from src.workflow.mail_delivery import send_supplier_rfq_via_mail

ISTANBUL = ZoneInfo("Europe/Istanbul")


class _Sender:
    def __init__(self, sent_at: datetime):
        self.sent_at = sent_at
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="synthetic success",
            provider_name="synthetic-provider",
            provider_message_id=f"m-{len(self.requests)}",
            sent_at=self.sent_at,
        )


def _policy():
    return SupplierDispatchPolicy(mode="parallel", initial_supplier_count=2)


def _workflow(*, deadline=None):
    return SupplierRFQWorkflow(
        workflow_id="wf-hours",
        shipment=Shipment(
            customer_name="Synthetic",
            transport_mode="road",
            equipment_type="Tenteli",
            customer_quote_deadline_at=deadline,
        ),
        sender_address="customer@example.invalid",
        customer_subject="Road quote",
        automation_timing_version=1,
        dispatch_policy=_policy(),
    )


def _draft(*, status="awaiting_response", sent_at=None):
    return SupplierRFQDraft(
        rfq_id="rfq-hours",
        workflow_id="wf-hours",
        supplier_name="Synthetic Primary",
        priority=1,
        recipient_email="supplier@example.invalid",
        supplier_role="primary",
        dispatch_tier="primary",
        subject="Synthetic RFQ",
        body="Synthetic body",
        status=status,
        sent_at=sent_at,
        approved_by="operator" if status == "approved" else None,
        approved_at=(
            datetime(2026, 9, 4, 18, 0, tzinfo=ISTANBUL)
            if status == "approved" else None
        ),
    )


def _queue(repo, actions, now):
    return build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=repo,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        automation_action_repository=actions,
        now=now,
    )


def evaluate_business_hours_automation_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    policy = _policy()
    friday_1820 = datetime(2026, 9, 4, 18, 20, tzinfo=ISTANBUL)
    friday_1730 = datetime(2026, 9, 4, 17, 30, tzinfo=ISTANBUL)
    metadata = supplier_calendar_metadata()
    check(
        metadata["timezone"] == "Europe/Istanbul"
        and metadata["start"] == "09:00"
        and metadata["end"] == "18:30"
        and metadata["weekdays"] == [0, 1, 2, 3, 4]
        and metadata["configurable"] is False,
        "supplier communication calendar is fixed weekdays 09:00-18:30 Istanbul",
    )
    check(
        add_supplier_business_minutes(friday_1820, 30).astimezone(ISTANBUL)
        == datetime(2026, 9, 7, 9, 20, tzinfo=ISTANBUL)
        and add_supplier_business_minutes(friday_1730, 120).astimezone(ISTANBUL)
        == datetime(2026, 9, 7, 10, 0, tzinfo=ISTANBUL),
        "supplier timers pause overnight and across weekends",
    )
    check(
        not is_supplier_business_time(datetime(2026, 10, 29, 10, 0, tzinfo=ISTANBUL))
        and is_supplier_business_time(datetime(2026, 10, 28, 12, 30, tzinfo=ISTANBUL))
        and not is_supplier_business_time(datetime(2026, 10, 28, 13, 0, tzinfo=ISTANBUL))
        and not is_supplier_business_time(datetime(2026, 5, 27, 10, 0, tzinfo=ISTANBUL))
        and tuple(SUPPLIER_HOLIDAY_COVERAGE_YEARS) == (2026, 2027, 2028),
        "Turkey official holidays and half-day eves close supplier communication",
    )
    check(
        add_supplier_business_minutes(
            datetime(2026, 5, 26, 12, 50, tzinfo=ISTANBUL), 30
        ).astimezone(ISTANBUL)
        == datetime(2026, 6, 1, 9, 20, tzinfo=ISTANBUL)
        and add_supplier_business_minutes(
            datetime(2026, 10, 28, 12, 50, tzinfo=ISTANBUL), 30
        ).astimezone(ISTANBUL)
        == datetime(2026, 10, 30, 9, 20, tzinfo=ISTANBUL),
        "half-day holiday closing pauses and resumes supplier timers correctly",
    )
    try:
        is_supplier_business_time(datetime(2029, 1, 2, 10, 0, tzinfo=ISTANBUL))
    except SupplierHolidayCalendarCoverageError:
        uncovered_year_blocked = True
    else:
        uncovered_year_blocked = False
    check(
        uncovered_year_blocked,
        "unverified future holiday year fails closed for supplier automation",
    )

    weekend_repo = InMemorySupplierRFQRepository()
    weekend_actions = InMemoryAutomationActionRepository()
    weekend_repo.save_workflow(_workflow())
    weekend_repo.save_drafts([_draft(sent_at=friday_1820)])
    weekend_sender = _Sender(datetime(2026, 9, 7, 9, 20, tzinfo=ISTANBUL))
    saturday = datetime(2026, 9, 5, 12, 0, tzinfo=ISTANBUL)
    run_automation_tick(
        supplier_repository=weekend_repo,
        action_repository=weekend_actions,
        sender=weekend_sender,
        now=saturday,
    )
    weekend_queue = _queue(weekend_repo, weekend_actions, saturday)
    monday_0920 = datetime(2026, 9, 7, 9, 20, tzinfo=ISTANBUL)
    run_automation_tick(
        supplier_repository=weekend_repo,
        action_repository=weekend_actions,
        sender=weekend_sender,
        now=monday_0920,
    )
    check(
        len(weekend_sender.requests) == 1
        and not weekend_queue["items"]
        and len(weekend_actions.list_all()) == 1
        and weekend_actions.list_all()[0].status == "sent",
        "weekend automation and contact escalation stay paused until business time",
    )

    deadline_repo = InMemorySupplierRFQRepository()
    deadline_actions = InMemoryAutomationActionRepository()
    deadline_repo.save_workflow(
        _workflow(deadline=datetime(2026, 9, 4, 20, 0, tzinfo=ISTANBUL))
    )
    deadline_sender = _Sender(datetime(2026, 9, 4, 19, 55, tzinfo=ISTANBUL))
    run_automation_tick(
        supplier_repository=deadline_repo,
        action_repository=deadline_actions,
        sender=deadline_sender,
        now=datetime(2026, 9, 4, 18, 25, tzinfo=ISTANBUL),
    )
    check(not deadline_sender.requests, "customer deadline does not inherit supplier closing time")
    run_automation_tick(
        supplier_repository=deadline_repo,
        action_repository=deadline_actions,
        sender=deadline_sender,
        now=datetime(2026, 9, 4, 19, 55, tzinfo=ISTANBUL),
    )
    check(
        len(deadline_sender.requests) == 1
        and deadline_sender.requests[0].purpose == "customer_status_update",
        "20:00 customer deadline sends one proactive update at 19:55",
    )

    future_repo = InMemorySupplierRFQRepository()
    future_actions = InMemoryAutomationActionRepository()
    future_repo.save_workflow(
        _workflow(deadline=datetime(2029, 1, 7, 20, 0, tzinfo=ISTANBUL))
    )
    future_sender = _Sender(datetime(2029, 1, 7, 19, 55, tzinfo=ISTANBUL))
    run_automation_tick(
        supplier_repository=future_repo,
        action_repository=future_actions,
        sender=future_sender,
        now=datetime(2029, 1, 7, 19, 55, tzinfo=ISTANBUL),
    )
    check(
        len(future_sender.requests) == 1
        and future_sender.requests[0].purpose == "customer_status_update",
        "customer deadline automation remains independent of supplier holiday coverage",
    )

    initial_repo = InMemorySupplierRFQRepository()
    initial_repo.save_workflow(_workflow())
    initial_draft = _draft(status="approved", sent_at=None)
    initial_repo.save_drafts([initial_draft])
    initial_sender = _Sender(datetime(2026, 9, 7, 9, 0, tzinfo=ISTANBUL))
    weekend_send = send_supplier_rfq_via_mail(
        repository=initial_repo,
        rfq_id=initial_draft.rfq_id,
        sender=initial_sender,
        enforce_business_hours=True,
        now=saturday,
    )
    monday_send = send_supplier_rfq_via_mail(
        repository=initial_repo,
        rfq_id=initial_draft.rfq_id,
        sender=initial_sender,
        enforce_business_hours=True,
        now=datetime(2026, 9, 7, 9, 0, tzinfo=ISTANBUL),
    )
    check(
        weekend_send.delivery.status == "rejected_before_provider"
        and monday_send.delivery.status == "sent"
        and len(initial_sender.requests) == 1,
        "approved initial supplier RFQ waits outside business hours",
    )

    for item in passes:
        print("PASS", item)
    for item in failures:
        print("FAIL", item)
    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_business_hours_automation_regressions()
    print(
        "\nBusiness-hours automation regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
