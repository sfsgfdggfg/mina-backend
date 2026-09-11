from datetime import datetime, timedelta, timezone

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.relationship_history import HistoricalMailMessage, analyze_relationship_history
from src.core.supplier_history_backfill import propose_supplier_operational_backfill
from src.core.supplier_intelligence_policy import build_supplier_operational_learning_policy
from src.integrations.microsoft_auth import MicrosoftAuthConfig
from src.workflow.relationship_onboarding import run_outlook_relationship_onboarding

NOW = datetime(2026, 9, 11, 8, 0, tzinfo=timezone.utc)
AGENCY = "ops@agency.invalid"
SUPPLIER = "pricing@supplier.invalid"


def _masters():
    repo = InMemoryMasterDataRepository()
    supplier = create_supplier_master(
        repository=repo, entry_id="supplier:history-backfill",
        supplier_name="History Backfill Trans",
        contacts=[{"contact_name":"Pricing", "email":SUPPLIER, "roles":["pricing"], "is_primary":True}],
        updated_by="Regression Operator", created_at=NOW - timedelta(days=400),
    )
    return repo, supplier


def _history(pair_count=6, *, supplier_email=SUPPLIER):
    messages = []
    delays = [60, 90, 120, 30, 45, 75, 105, 55]
    for index in range(pair_count):
        sent = NOW - timedelta(days=(pair_count-index)*30)
        subject = f"RFQ historical {index+1}"
        messages.append(HistoricalMailMessage(
            source_reference=f"out-{index}", sent_at=sent,
            sender_address=AGENCY, recipient_addresses=[supplier_email],
            subject=subject, body_text="Please quote this shipment.", source="synthetic",
        ))
        messages.append(HistoricalMailMessage(
            source_reference=f"in-{index}", sent_at=sent + timedelta(minutes=delays[index]),
            sender_address=supplier_email, recipient_addresses=[AGENCY],
            subject=f"Re: {subject}", body_text="Quote response.", source="synthetic",
        ))
    return messages


def evaluate_supplier_history_backfill_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters, supplier = _masters(); learning = InMemoryLearningFactRepository()
    analysis = analyze_relationship_history(
        messages=_history(), agency_addresses=[AGENCY], master_repository=masters,
        learning_repository=learning, created_by="Regression Operator",
        occurred_at=NOW,
    )
    subject = next(item for item in analysis.subjects if item.subject_id == supplier.supplier_id)
    historical_response_fact = next(
        item for item in learning.list_all()
        if item.subject_id == supplier.supplier_id
        and item.fact_key == "history.email.counterparty_response_median_minutes"
    )
    check(
        subject.counterparty_response_sample_count == 6
        and subject.counterparty_response_median_minutes == 67.5
        and subject.counterparty_response_confidence == 0.71
        and subject.latest_observed_at < NOW
        and historical_response_fact.evidence[0].observed_at == subject.latest_observed_at,
        "historical supplier response metrics preserve source recency instead of analysis-time freshness",
    )

    backfill = propose_supplier_operational_backfill(
        analysis=analysis, learning_repository=learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW + timedelta(minutes=1),
    )
    canonical = next(
        item for item in learning.list_all()
        if item.subject_id == supplier.supplier_id and item.fact_key == "response.median_minutes"
    )
    check(
        backfill["proposed_fact_count"] == 1
        and canonical.status == "proposed" and canonical.value == 67.5
        and canonical.value_unit == "minutes" and canonical.confidence == 0.71
        and canonical.evidence[0].observed_at == subject.latest_observed_at
        and backfill["runtime_authority_created"] is False,
        "Outlook supplier history creates a canonical response-time proposal without runtime authority",
    )
    confirmed = confirm_learning_fact(
        repository=learning, fact_id=canonical.fact_id,
        reviewed_by="Regression Reviewer", review_note="Confirmed historical supplier response baseline.",
        occurred_at=NOW + timedelta(minutes=2),
    )
    policy = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=learning,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120,
        as_of=NOW + timedelta(minutes=3),
    )
    check(
        confirmed.runtime_authoritative and policy.ranking_adjustment > 0
        and policy.first_reminder_source == "dispatch_default",
        "human confirmation may activate only the existing bounded supplier policy behavior",
    )

    analysis_rerun = analyze_relationship_history(
        messages=_history(), agency_addresses=[AGENCY], master_repository=masters,
        learning_repository=learning, created_by="Regression Operator",
        occurred_at=NOW + timedelta(days=1),
    )
    rerun = propose_supplier_operational_backfill(
        analysis=analysis_rerun, learning_repository=learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW + timedelta(days=1),
    )
    check(
        rerun["proposed_fact_count"] == 0
        and rerun["skipped_existing_authority_count"] == 1
        and len([item for item in learning.list_all() if item.fact_key == "response.median_minutes"]) == 1,
        "rerunning the same history never duplicates or replaces confirmed supplier authority",
    )
    repeat_learning = InMemoryLearningFactRepository()
    repeat_analysis = analyze_relationship_history(
        messages=_history(), agency_addresses=[AGENCY], master_repository=masters,
        learning_repository=repeat_learning, created_by="Regression Operator", occurred_at=NOW,
    )
    first_repeat = propose_supplier_operational_backfill(
        analysis=repeat_analysis, learning_repository=repeat_learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW,
    )
    second_repeat = propose_supplier_operational_backfill(
        analysis=repeat_analysis, learning_repository=repeat_learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW + timedelta(minutes=1),
    )
    check(
        first_repeat["proposed_fact_count"] == 1
        and second_repeat["proposed_fact_count"] == 0
        and second_repeat["reused_fact_count"] == 1,
        "supplier operational backfill is idempotent for the same historical evidence digest",
    )

    thin_learning = InMemoryLearningFactRepository()
    thin_analysis = analyze_relationship_history(
        messages=_history(2), agency_addresses=[AGENCY], master_repository=masters,
        learning_repository=thin_learning, created_by="Regression Operator", occurred_at=NOW,
    )
    thin = propose_supplier_operational_backfill(
        analysis=thin_analysis, learning_repository=thin_learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW,
    )
    check(
        thin["proposed_fact_count"] == 0
        and thin["skipped_insufficient_samples_count"] == 1
        and not any(item.fact_key == "response.median_minutes" for item in thin_learning.list_all()),
        "thin Outlook history stays descriptive and does not create canonical supplier response authority candidates",
    )
    workflow_learning = InMemoryLearningFactRepository()
    workflow_messages = _history()
    class _HistoryClient:
        last_message_rejections = []
        def list_relationship_history(self, *, start_at, end_at, max_messages):
            return workflow_messages
    workflow_payload = run_outlook_relationship_onboarding(
        config=MicrosoftAuthConfig(
            tenant_id="consumers", client_id="00000000-0000-0000-0000-000000000099",
            mailbox_id=AGENCY, token_cache_path="/tmp/minai-history-backfill-token.json",
        ),
        start_at=NOW - timedelta(days=200), end_at=NOW + timedelta(days=1), max_messages=100,
        authorization_confirmed=True, master_repository=masters,
        learning_repository=workflow_learning, created_by="Regression Operator",
        token_provider=lambda config: "synthetic-token",
        graph_client_factory=lambda **kwargs: _HistoryClient(),
    )
    check(
        workflow_payload["supplier_operational_backfill"]["proposed_fact_count"] == 1
        and workflow_payload["raw_messages_persisted"] is False
        and workflow_messages == [],
        "authorized Outlook onboarding returns supplier backfill summary while clearing transient raw history",
    )

    stale_learning = InMemoryLearningFactRepository()
    stale_messages = [
        item.model_copy(update={"sent_at": item.sent_at - timedelta(days=400)})
        for item in _history()
    ]
    stale_analysis = analyze_relationship_history(
        messages=stale_messages, agency_addresses=[AGENCY], master_repository=masters,
        learning_repository=stale_learning, created_by="Regression Operator", occurred_at=NOW,
    )
    stale_backfill = propose_supplier_operational_backfill(
        analysis=stale_analysis, learning_repository=stale_learning, master_repository=masters,
        created_by="Regression Operator", occurred_at=NOW,
    )
    stale_fact = next(item for item in stale_learning.list_all() if item.fact_key == "response.median_minutes")
    confirm_learning_fact(
        repository=stale_learning, fact_id=stale_fact.fact_id, reviewed_by="Regression Reviewer",
        review_note="Confirm stale history to verify runtime recency guard.", occurred_at=NOW,
    )
    stale_policy = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=stale_learning,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        stale_backfill["proposed_fact_count"] == 1 and stale_policy.ranking_adjustment == 0,
        "stale Outlook history may be reviewed but cannot become current runtime supplier behavior",
    )

    check(
        analysis.raw_body_persisted is False
        and canonical.evidence[0].source_reference.startswith("outlook-supplier-history:")
        and canonical.evidence[0].source_sha256 == subject.history_digest,
        "supplier backfill persists provenance digests and metrics but never raw historical message bodies",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier history backfill regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_history_backfill_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
