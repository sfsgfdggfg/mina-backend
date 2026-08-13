from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Lock, Thread, local
from unittest.mock import patch

from src.core.pilot_access import authorize_pilot_request, route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQNotFoundError,
    SupplierRFQTransitionError,
    attach_supplier_rfq_response,
    record_supplier_rfq_manually_sent,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository


class InjectedPersistenceError(RuntimeError):
    pass


def _approved_draft(rfq_id: str = "manual-rfq-1") -> SupplierRFQDraft:
    return SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id="manual-workflow-1",
        supplier_name="Manual Evidence Supplier",
        priority=1,
        recipient_email="pricing@supplier.test",
        subject="Approved manual RFQ",
        body="Non-sensitive regression RFQ body.",
        status="approved",
        approved_by="Approver",
        approved_at=datetime(2026, 8, 13, 9, 0, 0),
    )


def _sqlite_repository(path: Path, run_id: str):
    store = SQLitePilotStore(path, run_id=run_id)
    return store, SQLiteSupplierRFQRepository(store)


def _pilot_env() -> dict[str, str]:
    return {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps(
            {"Authenticated Pilot Operator": "a" * 40}
        ),
    }


def _check_atomic_rollback(failures: list[str], root: Path) -> None:
    for failure_point in ("draft", "evidence"):
        db_path = root / f"rollback-{failure_point}.sqlite3"
        _, repository = _sqlite_repository(db_path, "rollback")
        draft = _approved_draft(f"rollback-{failure_point}")
        repository.save_drafts([draft])
        target = (
            repository.save_drafts
            if failure_point == "draft"
            else repository.save_manual_sent_evidence
        )

        def fail_after_write(*args, **kwargs):
            target(*args, **kwargs)
            raise InjectedPersistenceError(f"injected {failure_point} failure")

        method = (
            "save_drafts"
            if failure_point == "draft"
            else "save_manual_sent_evidence"
        )
        with patch.object(repository, method, side_effect=fail_after_write):
            try:
                record_supplier_rfq_manually_sent(
                    repository,
                    draft.rfq_id,
                    "Authenticated Pilot Operator",
                )
            except InjectedPersistenceError:
                pass
            else:
                failures.append(f"{failure_point} failure did not propagate")

        _, reopened = _sqlite_repository(db_path, "rollback-reopen")
        durable = reopened.get_draft(draft.rfq_id)
        if durable is None or durable.status != "approved":
            failures.append(f"{failure_point} failure changed RFQ state")
        if reopened.list_manual_sent_evidence(draft.rfq_id):
            failures.append(f"{failure_point} failure left manual-send evidence")


def _check_concurrency(failures: list[str], root: Path) -> None:
    db_path = root / "concurrent.sqlite3"
    store, repository = _sqlite_repository(db_path, "concurrent")
    draft = _approved_draft("concurrent-rfq")
    repository.save_drafts([draft])

    import src.core.supplier_rfq_lifecycle as lifecycle

    original_get = lifecycle._get_draft
    barrier = Barrier(2)
    call_state = local()
    results: list[str] = []
    results_lock = Lock()

    def synchronized_initial_read(candidate_repository, rfq_id):
        value = original_get(candidate_repository, rfq_id)
        count = getattr(call_state, "count", 0)
        call_state.count = count + 1
        if count == 0:
            barrier.wait()
        return value

    def attempt(operator: str) -> None:
        try:
            record_supplier_rfq_manually_sent(
                repository,
                draft.rfq_id,
                operator,
            )
        except SupplierRFQTransitionError:
            outcome = "rejected"
        else:
            outcome = "succeeded"
        with results_lock:
            results.append(outcome)

    with patch.object(
        lifecycle,
        "_get_draft",
        side_effect=synchronized_initial_read,
    ):
        threads = [
            Thread(target=attempt, args=(f"Pilot Operator {index}",))
            for index in (1, 2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    events = [
        event
        for event in store.list_events(
            entity_type="supplier_rfq",
            entity_id=draft.rfq_id,
        )
        if event["event_type"] == "supplier_rfq_manually_sent"
    ]
    if sorted(results) != ["rejected", "succeeded"]:
        failures.append(f"concurrent outcomes were unsafe: {results}")
    if len(events) != 1:
        failures.append("concurrent attempts created duplicate evidence")


def evaluate_manual_rfq_sent_regressions() -> dict:
    failures: list[str] = []
    recorded_at = datetime(2026, 8, 13, 10, 30, 0)

    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        db_path = root / "manual-send.sqlite3"
        store, repository = _sqlite_repository(db_path, "manual-send")
        approved = _approved_draft()
        repository.save_drafts([approved])

        with patch("src.api.send_supplier_rfq_via_mail") as outbound_send:
            awaiting, evidence = record_supplier_rfq_manually_sent(
                repository,
                approved.rfq_id,
                "Authenticated Pilot Operator",
                recorded_at=recorded_at,
            )
        if outbound_send.called:
            failures.append("manual transition invoked outbound delivery")
        if awaiting.status != "awaiting_response":
            failures.append("approved RFQ did not enter awaiting_response")
        if awaiting.sent_at != recorded_at:
            failures.append("manual send timestamp was not stored on RFQ")
        if (
            evidence.rfq_id != approved.rfq_id
            or evidence.recorded_by != "Authenticated Pilot Operator"
            or evidence.recorded_at != recorded_at
            or evidence.source != "manual_external_send"
        ):
            failures.append("manual send evidence is incomplete")

        durable_evidence = repository.list_manual_sent_evidence(approved.rfq_id)
        manual_events = [
            event
            for event in store.list_events(
                entity_type="supplier_rfq",
                entity_id=approved.rfq_id,
            )
            if event["event_type"] == "supplier_rfq_manually_sent"
        ]
        if len(durable_evidence) != 1 or len(manual_events) != 1:
            failures.append("manual send evidence did not persist exactly once")

        response = SupplierRFQResponse(
            rfq_id=approved.rfq_id,
            supplier_name=approved.supplier_name,
            rfq_priority=approved.priority,
            status="quoted",
            cost=1200,
            currency="EUR",
            received_at=datetime(2026, 8, 13, 11, 0, 0),
        )
        responded = attach_supplier_rfq_response(repository, response)
        if responded.status != "responded":
            failures.append("manual-send RFQ did not accept a response")
        for status in ("awaiting_response", "responded"):
            candidate = approved.model_copy(
                update={"rfq_id": f"duplicate-{status}", "status": status}
            )
            repository.save_drafts([candidate])
            try:
                record_supplier_rfq_manually_sent(
                    repository,
                    candidate.rfq_id,
                    "Authenticated Pilot Operator",
                )
            except SupplierRFQTransitionError:
                pass
            else:
                failures.append(f"manual send accepted {status} RFQ")

        try:
            record_supplier_rfq_manually_sent(
                repository,
                "unknown-rfq",
                "Authenticated Pilot Operator",
            )
        except SupplierRFQNotFoundError:
            pass
        else:
            failures.append("unknown RFQ manual send was accepted")

        draft_repository = InMemorySupplierRFQRepository()
        draft = approved.model_copy(
            update={"rfq_id": "draft-rfq", "status": "draft"}
        )
        draft_repository.save_drafts([draft])
        try:
            record_supplier_rfq_manually_sent(
                draft_repository,
                draft.rfq_id,
                "Authenticated Pilot Operator",
            )
        except SupplierRFQTransitionError:
            pass
        else:
            failures.append("draft RFQ was manually marked sent")

        _, reopened = _sqlite_repository(db_path, "manual-send-reopen")
        reopened_draft = reopened.get_draft(approved.rfq_id)
        reopened_evidence = reopened.list_manual_sent_evidence(approved.rfq_id)
        if reopened_draft is None or reopened_draft.status != "responded":
            failures.append("reopen did not preserve manually-sent lifecycle")
        if len(reopened_evidence) != 1:
            failures.append("reopen did not preserve manual-send evidence")

        _check_atomic_rollback(failures, root)
        _check_concurrency(failures, root)

    pilot_env = _pilot_env()
    route = "/supplier-rfqs/rfq-1/record-manually-sent"
    if not route_allowed("POST", route):
        failures.append("manual-send API route is not pilot-allowed")
    if route_allowed("POST", "/supplier-rfqs/rfq-1/send"):
        failures.append("automated send route became pilot-allowed")
    for authorization in (None, "Bearer invalid"):
        decision = authorize_pilot_request(
            method="POST",
            path=route,
            client_host="127.0.0.1",
            authorization=authorization,
            environ=pilot_env,
        )
        if decision.allowed or decision.status_code != 401:
            failures.append("manual-send route accepted missing/invalid bearer")

    import src.api as api

    api_repository = InMemorySupplierRFQRepository()
    api_draft = _approved_draft("api-rfq")
    api_repository.save_drafts([api_draft])

    class _State:
        pilot_operator = "Authenticated Pilot Operator"

    class _Request:
        state = _State()

    with patch.object(api, "supplier_rfq_repository", api_repository):
        with patch.object(api, "send_supplier_rfq_via_mail") as outbound_send:
            result = api.record_supplier_rfq_manually_sent_endpoint(
                api_draft.rfq_id,
                api.SupplierRFQManualSentRequest(
                    recorded_by="Body Supplied Impostor"
                ),
                _Request(),
            )
    if outbound_send.called:
        failures.append("manual-send API invoked outbound delivery")
    if (
        result["manual_sent_evidence"]["recorded_by"]
        != "Authenticated Pilot Operator"
    ):
        failures.append("body identity overrode authenticated pilot operator")

    return {
        "name": "Manual Supplier RFQ sent evidence",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_manual_rfq_sent_regressions()
    print(json.dumps(result, indent=2, default=str))
    raise SystemExit(0 if result["passed"] else 1)
