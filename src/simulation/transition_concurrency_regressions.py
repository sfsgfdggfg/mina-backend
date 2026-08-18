from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import src.workflow.extraction_confirmation as extraction_workflow
from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Package, Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteExtractionProposalRepository
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    confirm_extraction_proposal,
)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Concurrency Regression",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=12000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-09-15",
        required_delivery_date="2026-09-22",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=12,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )


def evaluate_transition_concurrency_regressions() -> dict:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "transition-concurrency.sqlite3"
        store = SQLitePilotStore(db_path, run_id="transition-concurrency")
        repository = SQLiteExtractionProposalRepository(store)
        proposal = repository.save(
            ShipmentExtractionProposal(
                inbound_mail=InboundMailEnvelope(
                    body_text="Privacy-safe concurrent confirmation inquiry.",
                    privacy_transformed=True,
                ),
                proposed_shipment=ShipmentProposalSnapshot.model_validate(
                    _shipment().model_dump()
                ),
            )
        )

        original_validate = extraction_workflow._validated_confirmed_shipment

        def delayed_validate(*args, **kwargs):
            time.sleep(0.20)
            return original_validate(*args, **kwargs)

        start = threading.Barrier(3)
        outcomes: list[str] = []
        outcome_lock = threading.Lock()

        def worker(operator: str) -> None:
            start.wait()
            try:
                confirm_extraction_proposal(
                    repository=repository,
                    proposal_id=proposal.proposal_id,
                    operator_identity=operator,
                )
            except ExtractionConfirmationTransitionError:
                outcome = "blocked"
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
            else:
                outcome = "confirmed"
            with outcome_lock:
                outcomes.append(outcome)

        with patch.object(
            extraction_workflow,
            "_validated_confirmed_shipment",
            side_effect=delayed_validate,
        ):
            threads = [
                threading.Thread(target=worker, args=("operator-a",)),
                threading.Thread(target=worker, args=("operator-b",)),
            ]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=5)

        require(
            "concurrent extraction workers finish",
            all(not thread.is_alive() for thread in threads),
        )
        require(
            "concurrent extraction confirmation serialized",
            outcomes.count("confirmed") == 1
            and outcomes.count("blocked") == 1
            and len(outcomes) == 2,
        )
        durable = repository.get(proposal.proposal_id)
        require(
            "concurrent extraction leaves one durable confirmation",
            durable is not None
            and durable.extraction_status == "confirmed"
            and durable.confirmed_shipment is not None
            and durable.confirmed_by in {"operator-a", "operator-b"},
        )

    return {
        "name": "State transition concurrency",
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }



def _evaluate_quote_decision_concurrency() -> dict:
    import tempfile
    import threading
    import time
    from pathlib import Path
    from unittest.mock import patch

    import src.core.quote_approval_service as quote_service
    from src.core.pilot_store import SQLitePilotStore
    from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
    from src.core.quote_approval_service import (
        QuoteApprovalTransitionError,
        approve_quote,
        reject_quote,
    )
    from src.core.sqlite_repositories import SQLiteQuoteApprovalRepository

    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "quote-concurrency.sqlite3"
        store = SQLitePilotStore(db_path, run_id="quote-concurrency")
        repository = SQLiteQuoteApprovalRepository(store)
        approval = repository.save(
            QuoteApproval(
                quote_snapshot=QuoteApprovalSnapshot(
                    supplier_name="Concurrent Supplier",
                    supplier_cost=1000,
                    final_price=1200,
                    currency="EUR",
                    quote_subject="Concurrent quote",
                    quote_body="Concurrent quote body",
                )
            )
        )

        original_load = quote_service._load_approval

        def delayed_load(*args, **kwargs):
            loaded = original_load(*args, **kwargs)
            time.sleep(0.20)
            return loaded

        start = threading.Barrier(3)
        outcomes: list[str] = []
        outcome_lock = threading.Lock()

        def approve_worker() -> None:
            start.wait()
            try:
                approve_quote(
                    repository=repository,
                    approval_id=approval.approval_id,
                    approved_by="operator-approve",
                )
            except QuoteApprovalTransitionError:
                outcome = "blocked"
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
            else:
                outcome = "approved"
            with outcome_lock:
                outcomes.append(outcome)

        def reject_worker() -> None:
            start.wait()
            try:
                reject_quote(
                    repository=repository,
                    approval_id=approval.approval_id,
                    rejection_reason="Concurrent commercial rejection",
                    rejected_by="operator-reject",
                )
            except QuoteApprovalTransitionError:
                outcome = "blocked"
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
            else:
                outcome = "rejected"
            with outcome_lock:
                outcomes.append(outcome)

        with patch.object(
            quote_service,
            "_load_approval",
            side_effect=delayed_load,
        ):
            threads = [
                threading.Thread(target=approve_worker),
                threading.Thread(target=reject_worker),
            ]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=5)

        require(
            "concurrent quote decision workers finish",
            all(not thread.is_alive() for thread in threads),
        )
        require(
            "concurrent quote decisions serialized",
            len(outcomes) == 2
            and outcomes.count("blocked") == 1
            and (
                outcomes.count("approved") == 1
                or outcomes.count("rejected") == 1
            ),
        )
        durable = repository.get(approval.approval_id)
        require(
            "concurrent quote leaves one durable decision",
            durable is not None
            and durable.approval_status in {"approved", "rejected"}
            and (
                (
                    durable.approval_status == "approved"
                    and durable.approved_by == "operator-approve"
                    and durable.rejected_by is None
                )
                or (
                    durable.approval_status == "rejected"
                    and durable.rejected_by == "operator-reject"
                    and durable.approved_by is None
                )
            ),
        )

    return {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }


def _evaluate_supplier_response_concurrency() -> dict:
    import src.core.supplier_rfq_lifecycle as rfq_lifecycle
    from src.core.supplier_rfq import (
        SupplierRFQDraft,
        SupplierRFQResponse,
    )
    from src.core.supplier_rfq_lifecycle import (
        attach_supplier_rfq_response,
    )
    from src.core.supplier_rfq_repository import (
        DuplicateSupplierRFQResponseError,
    )
    from src.core.sqlite_repositories import (
        SQLiteSupplierRFQRepository,
    )

    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "supplier-response-concurrency.sqlite3"
        store = SQLitePilotStore(
            db_path,
            run_id="supplier-response-concurrency",
        )
        repository = SQLiteSupplierRFQRepository(store)
        draft = repository.save_drafts(
            [
                SupplierRFQDraft(
                    supplier_name="Concurrent Supplier",
                    priority=1,
                    recipient_email="ops@concurrent-supplier.example",
                    subject="Concurrent supplier RFQ",
                    body="Privacy-safe concurrent supplier RFQ.",
                    status="awaiting_response",
                )
            ]
        )[0]

        candidate_responses = [
            SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=draft.priority,
                status="quoted",
                cost=2200,
                currency="EUR",
                source="manual",
                recorded_by="worker-a",
            ),
            SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=draft.priority,
                status="quoted",
                cost=2250,
                currency="EUR",
                source="manual",
                recorded_by="worker-b",
            ),
        ]

        original_get_draft = rfq_lifecycle._get_draft

        def delayed_get_draft(*args, **kwargs):
            loaded = original_get_draft(*args, **kwargs)
            time.sleep(0.20)
            return loaded

        start = threading.Barrier(3)
        outcomes: list[str] = []
        outcome_lock = threading.Lock()

        def worker(response: SupplierRFQResponse) -> None:
            start.wait()
            try:
                attach_supplier_rfq_response(
                    repository=repository,
                    response=response,
                )
            except DuplicateSupplierRFQResponseError:
                outcome = "blocked"
            except Exception as exc:
                outcome = f"error:{type(exc).__name__}"
            else:
                outcome = "attached"
            with outcome_lock:
                outcomes.append(outcome)

        with patch.object(
            rfq_lifecycle,
            "_get_draft",
            side_effect=delayed_get_draft,
        ):
            threads = [
                threading.Thread(
                    target=worker,
                    args=(candidate_responses[0],),
                ),
                threading.Thread(
                    target=worker,
                    args=(candidate_responses[1],),
                ),
            ]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=5)

        require(
            "concurrent supplier response workers finish",
            all(not thread.is_alive() for thread in threads),
        )
        require(
            "concurrent supplier responses serialized",
            len(outcomes) == 2
            and outcomes.count("attached") == 1
            and outcomes.count("blocked") == 1,
        )

        durable_draft = repository.get_draft(draft.rfq_id)
        durable_responses = repository.list_responses(draft.rfq_id)
        durable_response = (
            durable_responses[0]
            if len(durable_responses) == 1
            else None
        )
        require(
            "concurrent supplier response leaves one durable response",
            durable_draft is not None
            and durable_draft.status == "responded"
            and durable_draft.responded_at is not None
            and durable_response is not None
            and durable_response.recorded_by in {"worker-a", "worker-b"}
            and durable_response.cost in {2200, 2250}
            and durable_draft.responded_at
            == durable_response.received_at,
        )

    return {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }


_extraction_only_evaluator = evaluate_transition_concurrency_regressions


def evaluate_transition_concurrency_regressions() -> dict:
    base = _extraction_only_evaluator()
    quote = _evaluate_quote_decision_concurrency()
    supplier_response = _evaluate_supplier_response_concurrency()
    failures = [
        *base["failures"],
        *quote["failures"],
        *supplier_response["failures"],
    ]
    checks = {
        **base["checks"],
        **quote["checks"],
        **supplier_response["checks"],
    }
    return {
        "name": "State transition concurrency",
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }

def main() -> int:
    result = evaluate_transition_concurrency_regressions()
    for name, passed in result["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(
        "\nState transition concurrency regressions: "
        + ("PASS" if result["passed"] else "FAIL")
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
