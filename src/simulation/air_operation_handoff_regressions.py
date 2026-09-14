from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_operation_handoff_repository import (
    InMemoryAirOperationHandoffRepository,
    SQLiteAirOperationHandoffRepository,
)
from src.core.air_operation_handoff_service import (
    AirOperationHandoffTransitionError,
    prepare_air_operation_handoff,
)
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import transition_mina_job_stage
from src.core.operation_start_repository import InMemoryOperationStartMessageRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_approval_service import approve_quote
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.quote_manual_sent import record_customer_quote_manually_sent
from src.core.sqlite_repositories import (
    SQLiteMinaJobRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
)
from src.simulation.air_quote_preparation_regressions import (
    NOW,
    _availability_repo,
    _customer_repo,
    _job,
    _prepare,
    _setup,
    _validity_repo,
)


APPROVED_AT = datetime(2026, 9, 14, 13, 5, tzinfo=timezone.utc)
SENT_AT = datetime(2026, 9, 14, 13, 10, tzinfo=timezone.utc)
ACCEPTED_AT = datetime(2026, 9, 14, 13, 15, tzinfo=timezone.utc)
HANDOFF_AT = datetime(2026, 9, 14, 13, 20, tzinfo=timezone.utc)


def _prepared_chain(*, job_repo=None, cases=None, approvals=None, key="air-p243"):
    setup = _setup()
    source_repo = setup[0]
    customer_repo, customer = _customer_repo()
    validity_repo = _validity_repo(source_repo)
    availability_repo = _availability_repo(source_repo)
    job_repo = job_repo or InMemoryMinaJobRepository()
    cases = cases or InMemoryQuoteCaseRepository()
    approvals = approvals or InMemoryQuoteApprovalRepository()
    job = _job(job_repo, key=key)
    prepared = _prepare(
        setup=setup,
        customer_repo=customer_repo,
        customer=customer,
        job_repo=job_repo,
        job=job,
        cases=cases,
        approvals=approvals,
        availability_repo=availability_repo,
        validity_repo=validity_repo,
    )
    return job_repo, cases, approvals, job, prepared


def _approve_send_accept(*, job_repo, cases, approvals, prepared):
    case = prepared.quote_case
    approval = prepared.quote_approval
    assert case is not None and approval is not None
    approved = approve_quote(
        repository=approvals,
        approval_id=approval.approval_id,
        approved_by="Air Approval Operator",
        approved_at=APPROVED_AT,
        quote_case_repository=cases,
    )
    sent = record_customer_quote_manually_sent(
        quote_case_repository=cases,
        approval_repository=approvals,
        case_id=case.case_id,
        expected_approval_id=approved.approval_id,
        recipient_email="air.customer@example.com",
        sent_by="Air Send Operator",
        sent_at=SENT_AT,
        mina_job_repository=job_repo,
    )
    current_job = job_repo.get(prepared.mina_job.job_id)
    assert current_job is not None
    accepted = transition_mina_job_stage(
        repository=job_repo,
        mina_code=current_job.mina_code,
        target_stage="accepted",
        actor="Air Sales Operator",
        occurred_at=ACCEPTED_AT,
    )
    return sent.quote_case, approved, accepted


def evaluate_air_operation_handoff_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    job_repo, cases, approvals, job, prepared = _prepared_chain()
    handoffs = InMemoryAirOperationHandoffRepository()

    pending_blocked = False
    try:
        prepare_air_operation_handoff(
            job_id=job.job_id,
            handed_off_by="Air Ops",
            handoff_repository=handoffs,
            mina_repository=job_repo,
            quote_case_repository=cases,
            approval_repository=approvals,
            handed_off_at=HANDOFF_AT,
        )
    except AirOperationHandoffTransitionError as exc:
        pending_blocked = str(exc) == "air_operation_handoff_requires_current_approved_quote"
    check(
        pending_blocked and handoffs.list_all() == [],
        "pending air quote approval cannot create an operation handoff",
    )

    case = prepared.quote_case
    approval = prepared.quote_approval
    assert case is not None and approval is not None
    approve_quote(
        repository=approvals,
        approval_id=approval.approval_id,
        approved_by="Air Approval Operator",
        approved_at=APPROVED_AT,
        quote_case_repository=cases,
    )
    unsent_blocked = False
    try:
        prepare_air_operation_handoff(
            job_id=job.job_id,
            handed_off_by="Air Ops",
            handoff_repository=handoffs,
            mina_repository=job_repo,
            quote_case_repository=cases,
            approval_repository=approvals,
            handed_off_at=HANDOFF_AT,
        )
    except AirOperationHandoffTransitionError as exc:
        unsent_blocked = str(exc) == "air_operation_handoff_requires_durable_current_quote_sent_evidence"
    check(
        unsent_blocked and handoffs.list_all() == [],
        "approved but unsent air quote cannot create an operation handoff",
    )

    record_customer_quote_manually_sent(
        quote_case_repository=cases,
        approval_repository=approvals,
        case_id=case.case_id,
        expected_approval_id=approval.approval_id,
        recipient_email="air.customer@example.com",
        sent_by="Air Send Operator",
        sent_at=SENT_AT,
        mina_job_repository=job_repo,
    )
    before_acceptance_blocked = False
    try:
        prepare_air_operation_handoff(
            job_id=job.job_id,
            handed_off_by="Air Ops",
            handoff_repository=handoffs,
            mina_repository=job_repo,
            quote_case_repository=cases,
            approval_repository=approvals,
            handed_off_at=HANDOFF_AT,
        )
    except AirOperationHandoffTransitionError as exc:
        before_acceptance_blocked = str(exc) == "air_operation_handoff_requires_exactly_one_customer_acceptance_event"
    check(
        before_acceptance_blocked and handoffs.list_all() == [],
        "sent air quote still requires explicit durable customer acceptance before handoff",
    )

    current_job = job_repo.get(job.job_id)
    assert current_job is not None
    transition_mina_job_stage(
        repository=job_repo,
        mina_code=current_job.mina_code,
        target_stage="accepted",
        actor="Air Sales Operator",
        occurred_at=ACCEPTED_AT,
    )
    road_messages = InMemoryOperationStartMessageRepository()
    result = prepare_air_operation_handoff(
        job_id=job.job_id,
        handed_off_by="Air Ops Operator",
        handoff_repository=handoffs,
        mina_repository=job_repo,
        quote_case_repository=cases,
        approval_repository=approvals,
        handed_off_at=HANDOFF_AT,
    )
    current_job = job_repo.get(job.job_id)
    check(
        result.status == "prepared"
        and result.created is True
        and current_job is not None
        and current_job.stage == "operation_opened"
        and result.handoff.air_quote_context == case.air_quote_context
        and result.handoff.accepted_by == "Air Sales Operator"
        and result.handoff.accepted_at == ACCEPTED_AT
        and result.handoff.handed_off_by == "Air Ops Operator",
        "accepted approved sent air quote freezes exact quote provenance and opens the existing MINA operation lifecycle",
    )
    check(
        len(result.handoff.customer_quote_sent_evidence) == 1
        and result.handoff.customer_quote_sent_evidence[0].evidence_kind == "manual_external_send"
        and result.handoff.customer_quote_sent_evidence[0].sent_at == SENT_AT,
        "air handoff freezes current-revision durable customer quote sent evidence instead of inferring delivery",
    )
    check(
        result.booking_confirmed is False
        and result.airline_contact_performed is False
        and result.booking_authority is False
        and result.outbound_authority is False
        and result.runtime_authoritative is False
        and road_messages.list_all() == [],
        "air operation handoff creates no airline booking outbound delivery or road operation-start message",
    )
    check(
        any(
            event.event_type == "air_operation_handoff_created"
            and event.resource_id == result.handoff.handoff_id
            and event.metadata.get("booking_confirmed") is False
            for event in job_repo.list_events(job.job_id)
        ),
        "air handoff records a durable MINA timeline event with booking explicitly false",
    )

    repeated = prepare_air_operation_handoff(
        job_id=job.job_id,
        handed_off_by="Second Air Ops",
        handoff_repository=handoffs,
        mina_repository=job_repo,
        quote_case_repository=cases,
        approval_repository=approvals,
        handed_off_at=HANDOFF_AT,
    )
    check(
        repeated.status == "existing"
        and repeated.created is False
        and repeated.handoff.handoff_id == result.handoff.handoff_id
        and len(handoffs.list_all()) == 1,
        "air handoff is idempotent after the job has entered operation_opened",
    )

    # Stage-only acceptance without current-revision send evidence must not authorize handoff.
    fake_job_repo, fake_cases, fake_approvals, fake_job, fake_prepared = _prepared_chain(key="air-p243-stage-only")
    fake_case = fake_prepared.quote_case
    fake_approval = fake_prepared.quote_approval
    assert fake_case is not None and fake_approval is not None
    approve_quote(
        repository=fake_approvals,
        approval_id=fake_approval.approval_id,
        approved_by="Air Approval Operator",
        approved_at=APPROVED_AT,
        quote_case_repository=fake_cases,
    )
    fake_current = fake_job_repo.get(fake_job.job_id)
    assert fake_current is not None
    transition_mina_job_stage(
        repository=fake_job_repo,
        mina_code=fake_current.mina_code,
        target_stage="quote_sent",
        actor="Unsafe Stage Operator",
        occurred_at=SENT_AT,
    )
    transition_mina_job_stage(
        repository=fake_job_repo,
        mina_code=fake_current.mina_code,
        target_stage="accepted",
        actor="Unsafe Stage Operator",
        occurred_at=ACCEPTED_AT,
    )
    stage_only_blocked = False
    try:
        prepare_air_operation_handoff(
            job_id=fake_job.job_id,
            handed_off_by="Air Ops",
            handoff_repository=InMemoryAirOperationHandoffRepository(),
            mina_repository=fake_job_repo,
            quote_case_repository=fake_cases,
            approval_repository=fake_approvals,
            handed_off_at=HANDOFF_AT,
        )
    except AirOperationHandoffTransitionError as exc:
        stage_only_blocked = str(exc) == "air_operation_handoff_requires_durable_current_quote_sent_evidence"
    check(
        stage_only_blocked,
        "generic quote_sent and accepted stage changes cannot substitute for durable customer quote sent evidence",
    )
    direct_operation_open_blocked = False
    try:
        transition_mina_job_stage(
            repository=fake_job_repo,
            mina_code=fake_current.mina_code,
            target_stage="operation_opened",
            actor="Unsafe Stage Operator",
            occurred_at=HANDOFF_AT,
        )
    except Exception as exc:
        direct_operation_open_blocked = "requires durable air operation handoff authority" in str(exc)
    check(
        direct_operation_open_blocked,
        "generic air accepted-to-operation_opened transition cannot bypass the durable handoff authority gate",
    )

    # SQLite reconstruction keeps the complete frozen handoff chain.
    with TemporaryDirectory(prefix="minai-air-p243-") as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"
        store = SQLitePilotStore(db_path, run_id="air-p243-a")
        sqlite_jobs = SQLiteMinaJobRepository(store)
        sqlite_cases = SQLiteQuoteCaseRepository(store)
        sqlite_approvals = SQLiteQuoteApprovalRepository(store)
        sqlite_handoffs = SQLiteAirOperationHandoffRepository(store)
        _, _, _, sqlite_job, sqlite_prepared = _prepared_chain(
            job_repo=sqlite_jobs,
            cases=sqlite_cases,
            approvals=sqlite_approvals,
            key="air-p243-sqlite",
        )
        _approve_send_accept(
            job_repo=sqlite_jobs,
            cases=sqlite_cases,
            approvals=sqlite_approvals,
            prepared=sqlite_prepared,
        )
        sqlite_result = prepare_air_operation_handoff(
            job_id=sqlite_job.job_id,
            handed_off_by="Durable Air Ops",
            handoff_repository=sqlite_handoffs,
            mina_repository=sqlite_jobs,
            quote_case_repository=sqlite_cases,
            approval_repository=sqlite_approvals,
            handed_off_at=HANDOFF_AT,
        )
        reopened = SQLitePilotStore(db_path, run_id="air-p243-b")
        rebuilt_handoff = SQLiteAirOperationHandoffRepository(reopened).find_by_job(sqlite_job.job_id)
        rebuilt_job = SQLiteMinaJobRepository(reopened).get(sqlite_job.job_id)
        check(
            rebuilt_handoff is not None
            and rebuilt_handoff.handoff_id == sqlite_result.handoff.handoff_id
            and rebuilt_handoff.air_quote_context.source_sha256 == sqlite_result.handoff.air_quote_context.source_sha256
            and rebuilt_handoff.customer_quote_sent_evidence[0].sent_at == SENT_AT
            and rebuilt_job is not None and rebuilt_job.stage == "operation_opened",
            "air operation handoff and MINA operation stage survive SQLite reconstruction with frozen provenance",
        )

    check(
        "air_operation_handoffs" in PERSISTENT_STATE_NAMESPACES
        and "air_operation_handoff_by_job" in PERSISTENT_STATE_NAMESPACES,
        "air operation handoff namespaces are protected from ordinary retention purge",
    )
    check(
        route_allowed("GET", "/mina-jobs/job-1/air-operation-handoff")
        and route_allowed("POST", "/mina-jobs/job-1/air-operation-handoff"),
        "pilot access admits only the bounded air operation handoff read and mutation routes",
    )

    from src import api
    originals = (
        api.air_operation_handoff_repository,
        api.mina_job_repository,
        api.quote_case_repository,
        api.quote_approval_repository,
    )
    try:
        api.air_operation_handoff_repository = handoffs
        api.mina_job_repository = job_repo
        api.quote_case_repository = cases
        api.quote_approval_repository = approvals
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.pilot_operator = "Authenticated Air Ops"
        api_result = api.prepare_mina_job_air_operation_handoff(job.job_id, request)
        api_view = api.get_mina_job_air_operation_handoff(job.job_id)
    finally:
        (
            api.air_operation_handoff_repository,
            api.mina_job_repository,
            api.quote_case_repository,
            api.quote_approval_repository,
        ) = originals
    check(
        api_result["status"] == "existing"
        and api_result["booking_authority"] is False
        and api_view["handoff_exists"] is True
        and api_view["booking_confirmed"] is False,
        "controlled API exposes the durable air handoff without granting booking or outbound authority",
    )

    root = Path(__file__).resolve().parents[2]
    service = (root / "src" / "core" / "air_operation_handoff_service.py").read_text(encoding="utf-8")
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "start_operation(" not in service
        and "dispatch_outbound_mail" not in service
        and "booking_confirmed: bool = False" in service
        and "_authenticated_operator(http_request)" in (root / "src" / "api.py").read_text(encoding="utf-8"),
        "air handoff service does not call road operation-start mail or booking execution paths",
    )
    check(
        "Havayolu Operasyonuna Devret" in ui
        and "BOOKING HENÜZ YOK" in ui
        and "Road araç/plaka/sürücü kontrolleri air işine uygulanmaz" in ui,
        "browser separates air handoff from road vehicle execution and keeps booking boundary visible",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_operation_handoff_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir operation handoff regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
