from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.agency_incremental_learning import (
    SQLiteAgencyIncrementalLearningRepository,
)
from src.core.agency_learning_bootstrap import (
    AgencyLearningBootstrapSnapshot,
    SQLiteAgencyLearningBootstrapRepository,
    source_reference_hash,
)
from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_price_repository import InMemorySupplierPriceRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.continuous_structured_learning import derive_review_safe_structured_learning
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.pilot_store import SQLitePilotStore
from src.core.relationship_history import HistoricalMailMessage, analyze_relationship_history
from src.workflow.agency_incremental_learning import run_incremental_agency_learning


UTC = timezone.utc
AGENCY = "info@agency.test"
CUSTOMER = "ops@customer.example"
SUPPLIER = "pricing@supplier.example"
T0 = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)


def _mail(ref, at, sender, recipients, subject, body):
    return HistoricalMailMessage(
        source_reference=ref,
        sent_at=at,
        sender_address=sender,
        recipient_addresses=recipients,
        subject=subject,
        body_text=body,
        source="authorized_mailbox",
    )


class _Client:
    def __init__(self, messages):
        self.messages = list(messages)
        self.last_message_rejections = []
        self.last_relationship_history_scan = {}
        self.calls = []

    def list_relationship_history(self, *, start_at, end_at, max_messages):
        self.calls.append((start_at, end_at, max_messages))
        selected = [
            item for item in self.messages
            if start_at <= item.sent_at < end_at
        ]
        self.last_relationship_history_scan = {
            "truncated": False,
            "accepted_message_count": len(selected),
        }
        return selected[:max_messages]


def _masters():
    masters = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=masters,
        entry_id="customer",
        customer_name="Customer Example",
        updated_by="regression",
        trusted_sender_addresses=[CUSTOMER],
    )
    supplier = create_supplier_master(
        repository=masters,
        entry_id="supplier",
        supplier_name="Supplier Example",
        updated_by="regression",
        trusted_sender_addresses=[SUPPLIER],
    )
    return masters, customer, supplier


def evaluate_agency_incremental_learning_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    masters, customer, supplier = _masters()
    learning = InMemoryLearningFactRepository()

    old_context = _mail(
        "old-context",
        T0 - timedelta(hours=1),
        CUSTOMER,
        [AGENCY],
        "Adana Münih taşıma talebi",
        "20 ton tenteli araç için fiyat rica ederiz.",
    )
    late_first = _mail(
        "late-first",
        T0 - timedelta(minutes=20),
        CUSTOMER,
        [AGENCY],
        "Re: Eski zincir",
        "Ek bilgi bilginize.",
    )
    new_quote = _mail(
        "new-quote",
        T0 + timedelta(minutes=5),
        AGENCY,
        [CUSTOMER],
        "Re: Adana Münih taşıma talebi",
        "Talebinize istinaden navlun teklifimiz aşağıdaki gibidir. 2.500 EUR all in.",
    )
    late_supplier = _mail(
        "late-supplier",
        T0 - timedelta(minutes=30),
        AGENCY,
        [SUPPLIER],
        "LV1001 // ADANA MUNICH NAVLUN TLB",
        "Aşağıdaki bilgilere istinaden navlun teklifinizi rica ederiz.",
    )

    with TemporaryDirectory() as tmp:
        store = SQLitePilotStore(Path(tmp) / "state.sqlite3")
        bootstrap_repo = SQLiteAgencyLearningBootstrapRepository(store)
        incremental_repo = SQLiteAgencyIncrementalLearningRepository(store)
        bootstrap_repo.save(
            AgencyLearningBootstrapSnapshot(
                status="completed",
                provider="outlook",
                mailbox_id=AGENCY,
                started_at=T0 - timedelta(minutes=5),
                completed_at=T0,
                history_start_at=T0 - timedelta(days=180),
                history_end_at=T0,
                scanned_message_count=100,
                inbound_message_count=40,
                outbound_message_count=35,
                inferred_agency_addresses=[AGENCY],
                recent_source_hashes=[
                    source_reference_hash(old_context.source_reference)
                ],
            )
        )
        client = _Client([old_context, late_first, new_quote])

        first = run_incremental_agency_learning(
            client=client,
            provider="outlook",
            mailbox_id=AGENCY,
            master_repository=masters,
            learning_repository=learning,
            bootstrap_repository=bootstrap_repo,
            incremental_repository=incremental_repo,
            max_messages=100,
            overlap_hours=48,
            include_ai_observations=False,
            now=T0 + timedelta(minutes=10),
        )
        state1 = incremental_repo.get()
        snapshot1 = bootstrap_repo.get()
        check(
            first["new_message_count"] == 2
            and state1.total_new_message_count == 2
            and snapshot1.outbound_message_count == 36
            and snapshot1.inbound_message_count == 41
            and snapshot1.workflow_patterns.customer_quote_message_count == 1,
            "first incremental run uses bootstrap hashes to ignore seen context while learning late-indexed pre-cursor mail",
        )

        second = run_incremental_agency_learning(
            client=client,
            provider="outlook",
            mailbox_id=AGENCY,
            master_repository=masters,
            learning_repository=learning,
            bootstrap_repository=bootstrap_repo,
            incremental_repository=incremental_repo,
            max_messages=100,
            overlap_hours=48,
            include_ai_observations=False,
            now=T0 + timedelta(minutes=15),
        )
        snapshot2 = bootstrap_repo.get()
        check(
            second["new_message_count"] == 0
            and incremental_repo.get().total_new_message_count == 2
            and snapshot2.outbound_message_count == 36
            and snapshot2.workflow_patterns.customer_quote_message_count == 1,
            "overlap rescan is idempotent and does not count the same provider message twice",
        )

        client.messages.append(late_supplier)
        third = run_incremental_agency_learning(
            client=client,
            provider="outlook",
            mailbox_id=AGENCY,
            master_repository=masters,
            learning_repository=learning,
            bootstrap_repository=bootstrap_repo,
            incremental_repository=incremental_repo,
            max_messages=100,
            overlap_hours=48,
            include_ai_observations=False,
            now=T0 + timedelta(minutes=20),
        )
        snapshot3 = bootstrap_repo.get()
        check(
            third["new_message_count"] == 1
            and incremental_repo.get().total_new_message_count == 3
            and snapshot3.workflow_patterns.supplier_rfq_message_count == 1
            and snapshot3.outbound_message_count == 37,
            "late-indexed older mail inside overlap is learned once instead of being lost behind the cursor",
        )

        serialized = (
            bootstrap_repo.get().model_dump_json()
            + incremental_repo.get().model_dump_json()
        ).casefold()
        check(
            "2.500 eur all in" not in serialized
            and "navlun teklifinizi rica ederiz" not in serialized,
            "incremental state persists hashes counters and learned aggregates but no raw mail body",
        )
        check(
            incremental_repo.get().cursor_at == T0 + timedelta(minutes=20)
            and incremental_repo.get().status == "healthy"
            and incremental_repo.get().run_count == 3
            and incremental_repo.get().provider == "outlook"
            and incremental_repo.get().mailbox_id == AGENCY,
            "incremental cursor advances only after successful durable merge and stays mailbox-bound",
        )

        replacement_mailbox = "info@another-agency.test"
        bootstrap_repo.save(
            AgencyLearningBootstrapSnapshot(
                status="completed",
                provider="outlook",
                mailbox_id=replacement_mailbox,
                started_at=T0 + timedelta(minutes=21),
                completed_at=T0 + timedelta(minutes=22),
                history_start_at=T0 - timedelta(days=180),
                history_end_at=T0 + timedelta(minutes=22),
                scanned_message_count=12,
                inferred_agency_addresses=[replacement_mailbox],
            )
        )
        switched = run_incremental_agency_learning(
            client=_Client([]),
            provider="outlook",
            mailbox_id=replacement_mailbox,
            master_repository=masters,
            learning_repository=learning,
            bootstrap_repository=bootstrap_repo,
            incremental_repository=incremental_repo,
            max_messages=100,
            overlap_hours=48,
            include_ai_observations=False,
            now=T0 + timedelta(minutes=25),
        )
        switched_state = incremental_repo.get()
        check(
            switched["new_message_count"] == 0
            and switched_state.mailbox_id == replacement_mailbox
            and switched_state.provider == "outlook"
            and switched_state.total_new_message_count == 0
            and switched_state.run_count == 1,
            "mailbox identity change resets incremental cursor and deduplication state instead of leaking prior-tenant history",
        )

    pending_learning = InMemoryLearningFactRepository()
    history1 = [
        _mail(
            "h1", T0, AGENCY, [CUSTOMER],
            "Lane request", "Teklifimiz aşağıdaki gibidir."
        ),
        _mail(
            "h2", T0 + timedelta(minutes=20), CUSTOMER, [AGENCY],
            "Re: Lane request", "Teşekkürler, değerlendireceğiz."
        ),
    ]
    analyze_relationship_history(
        messages=history1,
        agency_addresses=[AGENCY],
        master_repository=masters,
        learning_repository=pending_learning,
        created_by="regression",
        occurred_at=T0 + timedelta(hours=1),
    )
    total_before = [
        item for item in pending_learning.list_all()
        if item.subject_id == customer.customer_id
        and item.fact_key == "history.email.total_count"
        and item.status == "proposed"
    ]
    analyze_relationship_history(
        messages=[
            *history1,
            _mail(
                "h3", T0 + timedelta(hours=2), AGENCY, [CUSTOMER],
                "Lane request 2", "Yeni teklifimiz."
            ),
        ],
        agency_addresses=[AGENCY],
        master_repository=masters,
        learning_repository=pending_learning,
        created_by="regression",
        occurred_at=T0 + timedelta(hours=3),
    )
    total_after = [
        item for item in pending_learning.list_all()
        if item.subject_id == customer.customer_id
        and item.fact_key == "history.email.total_count"
        and item.status == "proposed"
    ]
    check(
        len(total_before) == 1 and len(total_after) == 1,
        "new history does not pile up a second proposal for the same fact while human review is pending",
    )

    no_metric_learning = InMemoryLearningFactRepository()
    result = analyze_relationship_history(
        messages=history1,
        agency_addresses=[AGENCY],
        master_repository=masters,
        learning_repository=no_metric_learning,
        created_by="incremental",
        occurred_at=T0 + timedelta(hours=4),
        propose_deterministic_metrics=False,
    )
    check(
        result.proposed_fact_count == 0
        and not no_metric_learning.list_all(),
        "incremental rolling windows can suppress full-history deterministic metrics",
    )

    structured_learning = InMemoryLearningFactRepository()
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference="regression:pending",
        observed_at=T0,
        summary="Synthetic pending review gate.",
    )
    create_learning_fact(
        repository=structured_learning,
        entry_id="pending:supplier:response",
        subject_type="supplier",
        subject_id=supplier.supplier_id,
        subject_label=supplier.supplier_name,
        fact_key="response.median_minutes",
        value=30.0,
        value_unit="minutes",
        confidence=0.8,
        source_type="minai_inference",
        evidence=[evidence],
        created_by="regression",
        occurred_at=T0,
        master_repository=masters,
    )
    create_learning_fact(
        repository=structured_learning,
        entry_id="pending:customer:preference",
        subject_type="customer",
        subject_id=customer.customer_id,
        subject_label=customer.customer_name,
        fact_key="preference.default_commodity",
        value="Textile",
        value_unit="text",
        confidence=0.8,
        source_type="minai_inference",
        evidence=[evidence],
        created_by="regression",
        occurred_at=T0,
        master_repository=masters,
    )
    structured = derive_review_safe_structured_learning(
        master_repository=masters,
        learning_repository=structured_learning,
        mina_repository=InMemoryMinaJobRepository(),
        supplier_repository=InMemorySupplierRFQRepository(),
        supplier_price_repository=InMemorySupplierPriceRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        occurred_at=T0 + timedelta(hours=5),
    )
    check(
        structured["supplier_pending_skip_count"] == 1
        and structured["supplier_derivation_run_count"] == 0
        and structured["customer_pending_skip_count"] == 1
        and structured["customer_derivation_run_count"] == 2
        and len(structured_learning.list_all()) == 2
        and structured["authority_created"] is False,
        "continuous structured derivation reuses existing services but skips learning families already awaiting human review",
    )

    return {
        "name": "Incremental agency mailbox learning",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_agency_incremental_learning_regressions()
    for label in result["passed_checks"]:
        print("PASS", label)
    for label in result["failures"]:
        print("FAIL", label)
    print(
        "\nIncremental agency learning regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
