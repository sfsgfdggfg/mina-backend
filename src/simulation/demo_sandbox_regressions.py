from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.demo_runtime import DemoOutboundMailSender, validate_demo_runtime
from src.core.attachment_interpretation_review_service import (
    apply_attachment_interpretation_review,
    build_attachment_review_preview,
)
from src.core.mail import OutboundMailRequest
from src.core.pilot_store import SQLitePilotStore
from src.core.pilot_access import route_allowed
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteMinaJobRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.master_data_repository import SQLiteMasterDataRepository
from src.core.mail import InboundMailEnvelope
from src.core.missing_info import check_missing_information
from src.core.road_rfq_readiness import apply_road_rfq_readiness
from src.core.learning_fact_repository import SQLiteLearningFactRepository
from src.demo_launcher import _configure_environment
from src.core.web_session import list_active_web_operators
from src.demo_seed import seed_demo_database
from src.workflow.demo_relationship_onboarding import run_demo_relationship_onboarding
from src.workflow.demo_inbound import parse_demo_customer_email
from src.workflow.extraction_confirmation import confirm_extraction_proposal
from src.workflow.mail_ingestion import process_customer_inquiry_mail
from src.workflow.supplier_response_ingestion import ingest_supplier_reply


def evaluate_demo_sandbox_regressions() -> dict:
    failures: list[str] = []

    def check(condition: bool, label: str):
        if condition:
            print(f"PASS {label}")
        else:
            print(f"FAIL {label}")
            failures.append(label)

    with tempfile.TemporaryDirectory(prefix="minai-demo-regression-") as directory:
        root = Path(directory)
        db = root / "demo.sqlite3"
        outbox = root / "outbox.jsonl"
        seeded = seed_demo_database(db, reset=True)
        repeated = seed_demo_database(db, reset=False)
        store = SQLitePilotStore(db, run_id="demo-regression", retention_days=365)
        jobs = SQLiteMinaJobRepository(store).list_all()
        masters = SQLiteMasterDataRepository(store)
        check(
            seeded.get("job_count") == 11 and len(jobs) == 11
            and seeded.get("assignment_count") == 4
            and seeded.get("attachment_review_count") == 2,
            "demo seed creates a populated synthetic MINA workload and work assignments",
        )
        assignment_repo = SQLiteOperationalWorkAssignmentRepository(store)
        assignment_history = assignment_repo.list_history()
        current_assignments = assignment_repo.list_all()
        check(
            len(current_assignments) == 4 and len(assignment_history) == 10
            and any(item.generation == 2 and item.assigned_to == "Demo Operator" for item in current_assignments)
            and any(item.status == "released" and item.release_reason == "shift_handoff" for item in assignment_history),
            "demo seed preserves multi-operator acknowledgement handoff and reassignment evidence",
        )
        check(repeated.get("reason") == "already_seeded" and len(jobs) == 11, "demo seed is idempotent without reset")
        check(len(masters.list_customers()) == 12 and len(masters.list_suppliers()) == 6, "demo seed includes synthetic customer and supplier master data")

        proposals = SQLiteExtractionProposalRepository(store)
        inbound_results = {}
        for marker in ("DEMO:FTL", "DEMO:MACHINE", "DEMO:REEFER"):
            result = process_customer_inquiry_mail(
                mail=InboundMailEnvelope(
                    body_text=marker, sender_address="demo@synthetic.customer.invalid",
                    external_message_id=f"demo-regression-{marker.casefold()}", source="manual",
                ),
                shipment_parser=parse_demo_customer_email, proposal_repository=proposals,
            )
            proposal = result["extraction_proposal"]
            confirmed = confirm_extraction_proposal(
                repository=proposals, proposal_id=proposal.proposal_id,
                operator_identity="Demo Operator", mina_job_repository=SQLiteMinaJobRepository(store),
            )
            base = check_missing_information(confirmed.confirmed_shipment)
            inbound_results[marker] = apply_road_rfq_readiness(confirmed.confirmed_shipment, base)
        check(
            inbound_results["DEMO:FTL"].can_continue_to_quote
            and not inbound_results["DEMO:REEFER"].missing_fields
            and not inbound_results["DEMO:MACHINE"].can_continue_to_quote
            and "package count and dimensions" in inbound_results["DEMO:MACHINE"].missing_fields,
            "demo inbound scenarios preserve extraction confirmation and road quote-readiness boundaries",
        )

        review_repo = SQLiteAttachmentInterpretationReviewRepository(store)
        supplier_repo = SQLiteSupplierRFQRepository(store)
        customer_review = review_repo.get("demo-attachment-review-customer")
        supplier_review = review_repo.get("demo-attachment-review-supplier")
        customer_preview = build_attachment_review_preview(customer_review, {})
        supplier_preview = build_attachment_review_preview(supplier_review, {})
        applied_customer = apply_attachment_interpretation_review(
            repository=review_repo, review_id=customer_review.review_id,
            operator_identity="Demo Operator", corrections={}, proposal_repository=proposals,
            supplier_repository=supplier_repo,
        )
        customer_proposal = proposals.get(applied_customer.applied_proposal_id)
        responses_before = len(supplier_repo.list_responses(supplier_review.rfq_id))
        applied_supplier = apply_attachment_interpretation_review(
            repository=review_repo, review_id=supplier_review.review_id,
            operator_identity="Demo Operator", corrections={}, proposal_repository=proposals,
            supplier_repository=supplier_repo,
        )
        supplier_responses = supplier_repo.list_responses(applied_supplier.applied_rfq_id)
        check(
            customer_preview["apply_ready"] and "safety_value_unknown:is_high_value" in customer_preview["warnings"]
            and customer_proposal.source_attachment_review_id == customer_review.review_id
            and supplier_preview["apply_ready"] and "parser_marked_uncertain:transit_time" in supplier_preview["warnings"]
            and responses_before == 0 and len(supplier_responses) == 1
            and supplier_responses[0].source_attachment_review_id == supplier_review.review_id
            and supplier_responses[0].cost == 2470.0 and supplier_responses[0].currency == "EUR",
            "demo attachment review applies customer extraction and supplier quote through real review services",
        )

        reply_candidates = [
            item for item in supplier_repo.list_drafts()
            if item.status == "awaiting_response"
            and not supplier_repo.list_responses(item.rfq_id)
            and not supplier_repo.list_acknowledgements(item.rfq_id)
        ]
        ack_target, no_capacity_target = reply_candidates[:2]
        ack_result = ingest_supplier_reply(
            reply=InboundMailEnvelope(
                external_message_id="demo-regression-ack", sender_address=ack_target.recipient_email,
                subject=f"Re: {ack_target.subject}", body_text="Talebinizi aldık, çalışıyoruz.",
                explicit_rfq_reference=ack_target.rfq_id, source="email",
            ), repository=supplier_repo,
        )
        responses_after_ack = supplier_repo.list_responses(ack_target.rfq_id)
        quote_result = ingest_supplier_reply(
            reply=InboundMailEnvelope(
                external_message_id="demo-regression-quote", sender_address=ack_target.recipient_email,
                subject=f"Re: {ack_target.subject}", body_text="2440 EUR",
                explicit_rfq_reference=ack_target.rfq_id, source="email",
            ), repository=supplier_repo,
            extracted_response={"status":"quoted","cost":2440.0,"currency":"EUR","transit_time":"5 gün","pricing_basis":"all_in"},
        )
        no_capacity_result = ingest_supplier_reply(
            reply=InboundMailEnvelope(
                external_message_id="demo-regression-no-capacity", sender_address=no_capacity_target.recipient_email,
                subject=f"Re: {no_capacity_target.subject}", body_text="Maalesef araç veremiyoruz.",
                explicit_rfq_reference=no_capacity_target.rfq_id, source="email",
            ), repository=supplier_repo, extracted_response={"status":"no_capacity"},
        )
        check(
            ack_result.status == "acknowledgement_recorded" and not responses_after_ack
            and len(supplier_repo.list_acknowledgements(ack_target.rfq_id)) == 1
            and quote_result.status == "response_attached"
            and supplier_repo.list_responses(ack_target.rfq_id)[0].cost == 2440.0
            and no_capacity_result.status == "response_attached"
            and supplier_repo.list_responses(no_capacity_target.rfq_id)[0].status == "no_capacity",
            "demo supplier reply scenarios use real correlation acknowledgement and commercial-response ingestion",
        )

        learning = SQLiteLearningFactRepository(store)
        history_end = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)
        history_start = history_end - timedelta(days=180)
        first_history = run_demo_relationship_onboarding(
            start_at=history_start, end_at=history_end, max_messages=5000,
            authorization_confirmed=True, master_repository=masters,
            learning_repository=learning, created_by="Demo Operator",
            include_ai_observations=True,
        )
        fact_count_after_first = len(learning.list_all())
        second_history = run_demo_relationship_onboarding(
            start_at=history_start, end_at=history_end, max_messages=5000,
            authorization_confirmed=True, master_repository=masters,
            learning_repository=learning, created_by="Demo Operator",
            include_ai_observations=True,
        )
        check(
            first_history["source"] == "synthetic_demo_history"
            and first_history["synthetic_mailbox"] is True
            and first_history["unique_message_count"] == 88
            and first_history["matched_message_count"] == 88
            and len(first_history["subjects"]) == 11
            and first_history["proposed_fact_count"] > 0
            and first_history["ai_observation_count"] == 11
            and first_history["raw_messages_persisted"] is False,
            "demo relationship onboarding exercises deterministic mailbox and learning-fact flow",
        )
        check(
            second_history["proposed_fact_count"] == 0
            and len(learning.list_all()) == fact_count_after_first,
            "demo relationship history rerun is idempotent for the same evidence window",
        )
        check(all(
            (contact.email or "").endswith(".invalid")
            for profile in [*masters.list_customers(), *masters.list_suppliers()]
            for contact in profile.contacts if contact.email
        ), "all demo master-data email contacts use reserved invalid domains")

        sender = DemoOutboundMailSender(outbox)
        safe = sender.send(OutboundMailRequest(
            operation_id="demo-safe", recipients=["pricing@rhein.supplier.invalid"],
            subject="Synthetic", body_text="Synthetic demo message", purpose="supplier_rfq",
        ))
        unsafe = sender.send(OutboundMailRequest(
            operation_id="demo-unsafe", recipients=["real@example.com"],
            subject="Synthetic", body_text="Synthetic demo message", purpose="supplier_rfq",
        ))
        check(safe.status == "sent" and outbox.exists(), "demo sender records synthetic sent evidence locally")
        check(unsafe.status == "rejected_before_provider", "demo sender rejects non-invalid recipients before provider delivery")
        receipts = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        check(len(receipts) == 1 and receipts[0]["request"]["operation_id"] == "demo-safe", "rejected demo delivery never enters synthetic outbox")

        env = {
            "MINAI_DEMO_MODE": "true",
            "MINAI_PILOT_MODE": "false",
            "MINAI_OUTBOUND_MODE": "shadow",
            "MINAI_WEB_SHELL_ENABLED": "true",
            "MINAI_PILOT_DB_PATH": str(db),
            "MINAI_DEMO_OUTBOX_PATH": str(outbox),
        }
        try:
            validate_demo_runtime(env)
            valid_isolation = True
        except RuntimeError:
            valid_isolation = False
        check(valid_isolation, "demo runtime accepts only isolated shadow-mode configuration")
        for mutation in (
            {**env, "MINAI_PILOT_MODE": "true"},
            {**env, "MINAI_OUTBOUND_MODE": "controlled_send"},
            {**env, "MINAI_PILOT_DB_PATH": str(Path(__file__).resolve().parents[2] / "data" / "demo.sqlite3")},
            {**env, "MINAI_DEMO_OUTBOX_PATH": "relative-outbox.jsonl"},
        ):
            try:
                validate_demo_runtime(mutation)
            except RuntimeError:
                pass
            else:
                failures.append("demo runtime isolation validation failed closed")
                print("FAIL demo runtime isolation validation failed closed")
                break
        else:
            print("PASS demo runtime isolation validation fails closed")

        old = dict(os.environ)
        try:
            os.environ["MINAI_DEMO_STATE_DIR"] = str(root / "launcher-state")
            db_path, outbox_path = _configure_environment(root)
            operators = list_active_web_operators()
            check(
                os.environ.get("MINAI_DEMO_MODE") == "true"
                and os.environ.get("MINAI_PILOT_MODE") == "false"
                and os.environ.get("MINAI_OUTBOUND_MODE") == "shadow"
                and Path(db_path).parent == root / "launcher-state"
                and Path(outbox_path).parent == root / "launcher-state"
                and {item["operator_name"] for item in operators} == {"Demo Operator", "Ayşe Demo", "Mehmet Demo"},
                "demo launcher forces isolated local runtime boundaries and multi-operator directory",
            )
        finally:
            os.environ.clear(); os.environ.update(old)

    root = Path(__file__).resolve().parents[2]
    shell = (root / "src" / "web_shell.py").read_text(encoding="utf-8")
    api_text = (root / "src" / "api.py").read_text(encoding="utf-8")
    css = (root / "ui" / "web_shell" / "app.css").read_text(encoding="utf-8")
    app_js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "DEMO · SENTETİK VERİ" in shell and ".demo-banner" in css
        and "Gelen Talepler" in shell and "DEMO_INBOUND_TEMPLATES" in app_js
        and "Doğrula ve MINA işi oluştur" in app_js and "Ek İnceleme" in app_js
        and "İncelemeyi uygula" in app_js and "preview_token" in app_js
        and "Demo tedarikçi yanıtı" in app_js
        and "demo_supplier_response_unavailable" in api_text
        and route_allowed("POST", "/demo/supplier-rfqs/demo-rfq/simulate-response")
        and "Demo mailbox" in app_js and "Sentetik Outlook Analizini Başlat" in app_js,
        "browser shell exposes synthetic inbound and relationship workflows without hiding demo mode",
    )

    return {"name": "Synthetic demo sandbox", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_demo_sandbox_regressions()
    print("\nDemo sandbox regressions:", "PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)
