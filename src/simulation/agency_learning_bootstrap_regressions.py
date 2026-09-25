from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.agency_learning_bootstrap import (
    SQLiteAgencyLearningBootstrapRepository,
    build_candidate_snapshot,
)
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.pilot_store import SQLitePilotStore
from src.core.relationship_history import HistoricalMailMessage
from src.workflow.agency_learning_bootstrap import _run_bootstrap


UTC = timezone.utc
AGENCY = "info@agency.test"
INTERNAL = "operator@agency.test"
SUPPLIER = "pricing@carrier.example"
CUSTOMER = "logistics@shipper.example"


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


def _messages():
    base = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    return [
        _mail(
            "s1", base, INTERNAL, [SUPPLIER],
            "LV1001 // ADANA MUNICH NAVLUN TLB",
            "Merhabalar, aşağıdaki bilgilere istinaden navlun teklifinizi rica ederiz.",
        ),
        _mail(
            "s2", base + timedelta(days=2), AGENCY, [SUPPLIER],
            "LV1002 // ADANA PARIS NAVLUN TLB",
            "All-in navlun teklifinizi rica ederiz. Gemi programı ile birlikte iletebilir misiniz?",
        ),
        _mail(
            "c1", base + timedelta(hours=1), CUSTOMER, [AGENCY],
            "Adana Münih taşıma talebi",
            "20 ton tenteli araç talebi, fiyat rica ederiz.",
        ),
        _mail(
            "c2", base + timedelta(hours=2), AGENCY, [CUSTOMER],
            "Ynt: Adana Münih taşıma talebi",
            "Talebinize istinaden navlun teklifimiz aşağıdaki gibidir. 2.500 EUR all in.",
        ),
        _mail(
            "c3", base + timedelta(days=3), AGENCY, [CUSTOMER],
            "Ynt: Yeni teklif",
            "Teklifimizi değerlendirebildiniz mi? Olumlu veya olumsuz geri dönüşlerinizi bekleriz.",
        ),
    ]


class _Client:
    def __init__(self, messages):
        self.messages = list(messages)
        self.last_message_rejections = []

    def list_relationship_history(self, *, start_at, end_at, max_messages):
        return list(self.messages)[:max_messages]


def evaluate_agency_learning_bootstrap_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    messages = _messages()
    empty = InMemoryMasterDataRepository()
    aliases, candidates, discovery = build_candidate_snapshot(
        messages=messages,
        mailbox_id=AGENCY,
        master_repository=empty,
    )
    by_address = {item.email_address: item for item in candidates}
    check(
        AGENCY in aliases and INTERNAL in aliases
        and INTERNAL not in by_address,
        "same-domain agency aliases are inferred and excluded from counterparties",
    )
    check(
        by_address[SUPPLIER].inferred_role == "supplier"
        and by_address[SUPPLIER].confidence >= 0.90,
        "repeated agency RFQs infer a high-confidence supplier candidate",
    )
    check(
        by_address[CUSTOMER].inferred_role == "customer"
        and by_address[CUSTOMER].confidence >= 0.90,
        "two-way request and quote traffic infers a high-confidence customer candidate",
    )
    check(
        discovery.candidate_count == 2,
        "bootstrap discovery excludes internal agency mail from external candidate count",
    )

    masters = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=masters,
        entry_id="customer",
        customer_name="Shipper Example",
        updated_by="regression",
        trusted_sender_addresses=[CUSTOMER],
    )
    supplier = create_supplier_master(
        repository=masters,
        entry_id="supplier",
        supplier_name="Carrier Example",
        updated_by="regression",
        trusted_sender_addresses=[SUPPLIER],
    )
    learning = InMemoryLearningFactRepository()
    with TemporaryDirectory() as tmp:
        store = SQLitePilotStore(Path(tmp) / "state.sqlite3")
        states = SQLiteAgencyLearningBootstrapRepository(store)
        result = _run_bootstrap(
            client=_Client(messages),
            provider="outlook",
            mailbox_id=AGENCY,
            master_repository=masters,
            learning_repository=learning,
            state_repository=states,
            created_by="MINAI Agency Learning Bootstrap",
            history_days=180,
            max_messages=100,
            include_ai_observations=False,
            now=datetime(2026, 9, 25, 8, 0, tzinfo=UTC),
        )
        snapshot = states.get()
        serialized = snapshot.model_dump_json()
        check(
            snapshot.status == "completed"
            and snapshot.scanned_message_count == len(messages)
            and snapshot.inbound_message_count == 1
            and snapshot.outbound_message_count == 4
            and snapshot.matched_subject_count == 2
            and snapshot.workflow_patterns.supplier_rfq_message_count == 2
            and snapshot.workflow_patterns.customer_quote_message_count == 2
            and result["raw_messages_persisted"] is False,
            "automatic bootstrap persists bounded two-way workflow learning and completes known-master analysis",
        )
        check(
            "2.500 EUR all in" not in serialized
            and "navlun teklifinizi rica ederiz" not in serialized,
            "raw historical message bodies are not persisted in bootstrap state",
        )
        facts = learning.list_all()
        check(
            any(item.subject_id == customer.customer_id for item in facts)
            and any(item.subject_id == supplier.supplier_id for item in facts),
            "known customers and suppliers receive provenance-backed relationship learning facts",
        )

    return {
        "name": "Automatic agency learning bootstrap",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_agency_learning_bootstrap_regressions()
    for label in result["passed_checks"]:
        print("PASS", label)
    for label in result["failures"]:
        print("FAIL", label)
    print("\nAgency learning bootstrap regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
