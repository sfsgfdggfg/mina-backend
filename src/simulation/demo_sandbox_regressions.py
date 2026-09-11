from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

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
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalShiftOpenAcceptanceReceiptRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.master_data_repository import SQLiteMasterDataRepository
from src.core.supplier_price_repository import SQLiteSupplierPriceRepository
from src.core.mail import InboundMailEnvelope
from src.core.models import EquipmentDecision, Package, Shipment
from src.core.supplier_rfq import SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_lifecycle import approve_supplier_rfq_follow_up, attach_supplier_rfq_response
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_selection import select_suppliers_for_shipment
from src.ai.supplier_rfq_generator import generate_supplier_rfq_drafts
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.missing_info import check_missing_information
from src.core.road_rfq_readiness import apply_road_rfq_readiness
from src.core.learning_fact_repository import SQLiteLearningFactRepository
from src.core.customer_memory import CustomerMemoryProfile, apply_customer_memory_import, load_customer_memory, save_customer_profile
from src.core.customer_memory_validator import validate_customer_memory_file
from src.paths import data_path
from src.core.operational_shift_continuity_ledger import build_operational_shift_continuity_ledger
from src.core.operational_shift_open_reconciliation import build_operational_shift_open_reconciliation
from src.demo_launcher import _configure_environment
from src.core.web_session import list_active_web_operators
from src.demo_seed import seed_demo_customer_memory, seed_demo_database
from src.workflow.demo_relationship_onboarding import run_demo_relationship_onboarding
from src.workflow.demo_inbound import parse_demo_customer_email
from src.workflow.demo_reset import DemoResetUnavailableError, reset_demo_sandbox
from src.workflow.demo_outlook_pull import run_demo_outlook_pull
from src.workflow.extraction_confirmation import confirm_extraction_proposal
from src.workflow.mail_ingestion import process_customer_inquiry_mail
from src.workflow.supplier_response_ingestion import ingest_supplier_reply
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow
from src.workflow.mail_delivery import send_supplier_rfq_follow_up_via_mail


def _isolated_follow_up_fixture():
    shipment = Shipment(
        customer_name="Demo Follow-up Customer", pickup_country="Türkiye", pickup_city="Adana",
        delivery_country="Almanya", delivery_city="Hamburg", delivery_postcode="20095",
        commodity="Tekstil", gross_weight_kg=20000, transport_mode="road", service_type="FTL",
        equipment_type="Tenteli / Curtainsider", cargo_ready_date="2026-09-10",
        is_adr=False, is_temperature_controlled=False, is_high_value=False,
        packages=[Package(package_type="pallet", quantity=20, length_cm=120, width_cm=80, height_cm=150)],
    )
    equipment = EquipmentDecision(selected_equipment="Tenteli / Curtainsider", reason="Demo regression", confidence=1.0)
    selection = select_suppliers_for_shipment(shipment=shipment, equipment_decision=equipment)
    first = selection["selected_suppliers"][0]
    workflow = SupplierRFQWorkflow(shipment=shipment)
    draft = generate_supplier_rfq_drafts(
        workflow_id=workflow.workflow_id, shipment=shipment, equipment_decision=equipment,
        supplier_selection={**selection, "selected_suppliers": [first]},
    )[0].model_copy(update={"status":"awaiting_response", "sent_at":datetime(2026,9,10,8,0,0)})
    repository = InMemorySupplierRFQRepository()
    repository.save_drafts([draft])
    repository.save_workflow(workflow.model_copy(update={"rfq_ids":[draft.rfq_id]}))
    return repository, workflow, draft


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
        demo_prices = SQLiteSupplierPriceRepository(store)
        fixed_rates = demo_prices.list_fixed_rates()
        check(seeded.get("fixed_rate_count") == 3 and len(fixed_rates) == 3 and all(rate.active for rate in fixed_rates), "demo seed exposes active synthetic supplier fixed rates")
        negotiations = demo_prices.list_negotiations()
        check(
            len(negotiations) == 1
            and negotiations[0].supplier_name == "EuroHaul"
            and negotiations[0].before_cost == 2620
            and negotiations[0].after_cost == 2490
            and negotiations[0].channel == "phone",
            "demo negotiation job carries explicit before-after supplier price evidence",
        )

        shift_closes = SQLiteOperationalShiftCloseReceiptRepository(store)
        shift_opens = SQLiteOperationalShiftOpenAcceptanceReceiptRepository(store)
        shift_approvals = SQLiteQuoteApprovalRepository(store)
        shift_cases = SQLiteQuoteCaseRepository(store)
        shift_args = dict(
            assignment_repository=assignment_repo, attachment_repository=SQLiteAttachmentInterpretationReviewRepository(store),
            proposal_repository=SQLiteExtractionProposalRepository(store), supplier_repository=SQLiteSupplierRFQRepository(store),
            approval_repository=shift_approvals, quote_case_repository=shift_cases,
        )
        shift_ledger = build_operational_shift_continuity_ledger(
            receipt_repository=shift_closes, acceptance_repository=shift_opens, **shift_args
        )
        shift_opening = build_operational_shift_open_reconciliation(
            operator_name="Demo Operator", receipt_repository=shift_closes, **shift_args
        )
        check(
            seeded.get("shift_continuity_evidence_count") == 2
            and shift_ledger["counts"]["listed_complete_cycle_count"] == 1
            and shift_ledger["items"][0]["completion_status"] == "complete"
            and shift_opening["prior_shift_close"]["status"] == "available"
            and shift_opening["reconciliation_status"] == "review_required",
            "demo seed includes historical close-open continuity evidence without authorizing the current shift",
        )

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

        pull_db = root / "demo-outlook.sqlite3"
        seed_demo_database(pull_db, reset=True)
        pull_store = SQLitePilotStore(pull_db, run_id="demo-outlook-regression", retention_days=365)
        pull_proposals = SQLiteExtractionProposalRepository(pull_store)
        pull_suppliers = SQLiteSupplierRFQRepository(pull_store)
        pull_reviews = SQLiteAttachmentInterpretationReviewRepository(pull_store)
        pull_masters = SQLiteMasterDataRepository(pull_store)
        with patch.dict(os.environ, {"MINAI_DEMO_STATE_DIR": str(root / "outlook-state")}, clear=False):
            first_pull = run_demo_outlook_pull(
                limit=10, proposal_repository=pull_proposals, operational_data_sources=None,
                master_data_repository=pull_masters, supplier_repository=pull_suppliers,
                attachment_review_repository=pull_reviews, interpret_attachments=False,
            )
            response_count_after_first = sum(
                len(pull_suppliers.list_responses(item.rfq_id)) for item in pull_suppliers.list_drafts()
            )
            second_pull = run_demo_outlook_pull(
                limit=10, proposal_repository=pull_proposals, operational_data_sources=None,
                master_data_repository=pull_masters, supplier_repository=pull_suppliers,
                attachment_review_repository=pull_reviews, interpret_attachments=False,
            )
            response_count_after_second = sum(
                len(pull_suppliers.list_responses(item.rfq_id)) for item in pull_suppliers.list_drafts()
            )
        check(
            first_pull["synthetic_mailbox"] is True
            and first_pull["proposal_count"] == 1
            and first_pull["supplier_response_count"] == 1
            and first_pull["manual_review_count"] == 1
            and second_pull["supplier_response_count"] == 0
            and response_count_after_first == response_count_after_second
            and any(item.get("ingestion_status") == "duplicate_response" for item in second_pull["results"]),
            "demo Outlook pull uses production routing while preserving sender authority and replay idempotency",
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

        follow_repo, follow_workflow, follow_draft = _isolated_follow_up_fixture()
        attach_supplier_rfq_response(follow_repo, SupplierRFQResponse(
            rfq_id=follow_draft.rfq_id, supplier_name=follow_draft.supplier_name,
            rfq_priority=follow_draft.priority, status="quoted", cost=2450.0, currency="EUR",
            equipment_type="Tenteli / Curtainsider", pricing_basis="all_in", source="manual",
            received_at=datetime(2026, 9, 10, 9, 0, 0),
        ))
        with patch.dict(os.environ, {"MINAI_PILOT_MODE":"0"}, clear=False):
            follow_result = resume_supplier_rfq_workflow(
                workflow_id=follow_workflow.workflow_id, rfq_repository=follow_repo,
                approval_repository=InMemoryQuoteApprovalRepository(), quote_case_repository=InMemoryQuoteCaseRepository(),
            )
        follow_record = follow_result.get("supplier_follow_up_record")
        follow_sent = None; follow_reply = None; follow_closed = None
        if follow_record is not None:
            approved = approve_supplier_rfq_follow_up(follow_repo, follow_record.follow_up_id, approved_by="Demo Operator")
            with patch.dict(os.environ, {"MINAI_DEMO_MODE":"true", "MINAI_OUTBOUND_MODE":"shadow"}, clear=False):
                follow_sent = send_supplier_rfq_follow_up_via_mail(
                    repository=follow_repo, follow_up_id=approved.follow_up_id,
                    sender=DemoOutboundMailSender(root / "follow_up_outbox.jsonl"), enforce_business_hours=False, triggered_by="Demo Operator",
                )
            sent_record = follow_repo.get_follow_up_draft(approved.follow_up_id)
            follow_reply = ingest_supplier_reply(
                reply=InboundMailEnvelope(
                    external_message_id="demo-follow-up-transit", sender_address=follow_draft.recipient_email,
                    subject=f"Re: [{follow_draft.reference_token}] Demo RFQ", body_text="4 gün",
                    explicit_rfq_reference=follow_draft.rfq_id, source="email",
                    received_at=(sent_record.sent_at + timedelta(seconds=2)),
                ), repository=follow_repo,
            )
            follow_closed = follow_repo.get_follow_up_draft(approved.follow_up_id)
        check(
            follow_result.get("result_type") == "supplier_response_required"
            and follow_record is not None and follow_record.status == "draft"
            and "supplier_transit_missing_or_unparseable" in follow_record.rejection_reasons
            and follow_sent is not None and follow_sent.delivery.status == "sent"
            and follow_reply is not None and follow_reply.status == "response_attached"
            and follow_reply.response is not None and follow_reply.response.cost == 2450.0
            and follow_reply.response.transit_time == "4 gün" and follow_reply.response.is_consolidated_follow_up
            and follow_closed is not None and follow_closed.status == "responded",
            "demo supplier clarification follow-up preserves approval send and consolidated response lifecycle",
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


    default_memory_path = data_path("customer_memory.json")
    default_memory_before = default_memory_path.read_bytes() if default_memory_path.exists() else b""
    with tempfile.TemporaryDirectory(prefix="minai-demo-memory-") as memory_dir:
        memory_root = Path(memory_dir)
        memory_path = memory_root / "customer_memory.json"
        backup_dir = memory_root / "backups"
        old_memory_path = os.environ.get("MINAI_CUSTOMER_MEMORY_PATH")
        old_backup_dir = os.environ.get("MINAI_CUSTOMER_MEMORY_BACKUP_DIR")
        try:
            os.environ["MINAI_CUSTOMER_MEMORY_PATH"] = str(memory_path)
            os.environ["MINAI_CUSTOMER_MEMORY_BACKUP_DIR"] = str(backup_dir)
            seeded_memory = seed_demo_customer_memory(memory_path, reset=True)
            save_customer_profile(CustomerMemoryProfile(
                customer_name="Sandbox Yeni Müşteri",
                aliases=["sandbox yeni"],
                trusted_sender_addresses=["ops@sandbox-new.customer.invalid"],
                trusted_sender_domains=["sandbox-new.customer.invalid"],
                default_commodity="Tekstil",
                default_equipment_type="Tenteli / Curtainsider",
                last_updated_by="Demo Operator",
            ))
            export_profiles = [item.model_dump(mode="json") for item in load_customer_memory()]
            imported = apply_customer_memory_import(
                {"profiles": export_profiles}, updated_by="demo-regression"
            )
            check(
                seeded_memory.get("profile_count") == 4
                and len(load_customer_memory()) == 5
                and validate_customer_memory_file().get("valid") is True
                and imported.get("total_profile_count") == 5
                and backup_dir.exists()
                and any(backup_dir.glob("customer_memory_backup_*.json"))
                and (default_memory_path.read_bytes() if default_memory_path.exists() else b"") == default_memory_before,
                "demo customer memory stays file-isolated from repository operational data",
            )
        finally:
            if old_memory_path is None: os.environ.pop("MINAI_CUSTOMER_MEMORY_PATH", None)
            else: os.environ["MINAI_CUSTOMER_MEMORY_PATH"] = old_memory_path
            if old_backup_dir is None: os.environ.pop("MINAI_CUSTOMER_MEMORY_BACKUP_DIR", None)
            else: os.environ["MINAI_CUSTOMER_MEMORY_BACKUP_DIR"] = old_backup_dir

    with tempfile.TemporaryDirectory(prefix="minai-demo-reset-") as reset_dir:
        reset_root = Path(reset_dir)
        state = reset_root / "state"
        state.mkdir()
        db = state / "minai_demo.sqlite3"
        outbox = state / "demo_outbox.jsonl"
        memory = state / "customer_memory.json"
        backups = state / "customer_memory_backups"
        target = state / "demo_outlook_supplier_target.txt"
        reset_env = {
            "MINAI_DEMO_MODE":"true", "MINAI_DEMO_STATE_DIR":str(state),
            "MINAI_PILOT_MODE":"false", "MINAI_OUTBOUND_MODE":"shadow", "MINAI_WEB_SHELL_ENABLED":"true",
            "MINAI_PILOT_DB_PATH":str(db), "MINAI_DEMO_OUTBOX_PATH":str(outbox),
            "MINAI_CUSTOMER_MEMORY_PATH":str(memory), "MINAI_CUSTOMER_MEMORY_BACKUP_DIR":str(backups),
        }
        with patch.dict(os.environ, reset_env, clear=False):
            seed_demo_database(db, reset=True); seed_demo_customer_memory(memory, reset=True)
            probe_store = SQLitePilotStore(db, run_id="demo-reset-probe", retention_days=365)
            jobs_before_reset = SQLiteMinaJobRepository(probe_store)
            probe_store.upsert(namespace="demo_reset_probe", record_key="dirty", payload={"dirty":True}, event_type="demo_reset_probe_written", entity_type="demo_reset_probe")
            outbox.write_text("synthetic dirty outbox\n", encoding="utf-8")
            target.write_text("dirty-rfq", encoding="utf-8")
            memory.write_text("[]", encoding="utf-8")
            backups.mkdir(exist_ok=True); (backups / "dirty.json").write_text("{}", encoding="utf-8")
            reset_result = reset_demo_sandbox()
            reset_profiles = json.loads(memory.read_text(encoding="utf-8"))
            check(
                reset_result.get("reset_status") == "complete" and reset_result.get("job_count") == 11
                and len(jobs_before_reset.list_all()) == 11 and probe_store.get(namespace="demo_reset_probe", record_key="dirty") is None
                and len(reset_profiles) == 4 and not outbox.exists() and not target.exists()
                and backups.exists() and not any(backups.iterdir()),
                "demo reset restores isolated baseline and existing repositories reconnect to reseeded state",
            )
            outside = reset_root / "outside-memory.json"; outside.write_text("do-not-touch", encoding="utf-8")
            os.environ["MINAI_CUSTOMER_MEMORY_PATH"] = str(outside)
            try:
                reset_demo_sandbox()
            except DemoResetUnavailableError:
                reset_blocked = outside.read_text(encoding="utf-8") == "do-not-touch"
            else:
                reset_blocked = False
            check(reset_blocked, "demo reset rejects state paths outside the isolated demo directory before mutation")

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
        and "Demo tedarikçi yanıtı" in app_js and "Eksik fiyat ver" in app_js
        and "Tedarikçi açıklama takibi" in app_js
        and "/supplier-rfq-follow-ups/${encodeURIComponent(activeFollowUp.follow_up_id)}/approve" in app_js
        and "/supplier-rfq-follow-ups/${encodeURIComponent(activeFollowUp.follow_up_id)}/send" in app_js
        and "RFQ'yu Onayla" in app_js and "RFQ'yu Gönder" in app_js
        and "Telefon / WhatsApp temas sonucu" in app_js and "Telefon · Ulaşılamadı" in app_js
        and "/supplier-rfqs/${encodeURIComponent(supplier.rfq_id)}/contact-attempts" in app_js
        and "Pahalı primary fiyatları sonrası secondary grubu aç" in app_js
        and route_allowed("POST", "/supplier-rfqs/demo-rfq/approve")
        and route_allowed("POST", "/supplier-rfqs/demo-rfq/send")
        and route_allowed("POST", "/supplier-rfqs/demo-rfq/record-manually-sent")
        and route_allowed("POST", "/supplier-rfqs/demo-rfq/acknowledge-seen")
        and route_allowed("POST", "/supplier-rfqs/demo-rfq/contact-attempts")
        and route_allowed("GET", "/supplier-rfq-workflows/demo-workflow/dispatch-status")
        and route_allowed("POST", "/supplier-rfq-workflows/demo-workflow/authorize-secondary-after-negotiation")
        and "primary_price_negotiation_exhausted" not in app_js
        and "Manuel MINA işi oluştur" in app_js and "/mina-jobs/manual" in app_js
        and "Sabit Fiyatlar" in app_js and "/supplier-fixed-rates" in app_js
        and "Sistem Sağlığı" in app_js and "/data-health/summary" in app_js
        and route_allowed("GET", "/data-health/summary") and route_allowed("GET", "/commodity-dictionary/validation")
        and route_allowed("POST", "/mina-jobs/manual")
        and "Vardiya Sürekliliği" in app_js and "Vardiyaya Devret" in app_js
        and "/operational-work-shift-close-readiness" in app_js
        and "/operational-work-shift-open-reconciliation" in app_js
        and "/operational-work-shift-continuity" in app_js
        and route_allowed("GET", "/operational-work-shift-summary")
        and route_allowed("POST", "/operational-work-shift-open-accept")
        and route_allowed("POST", "/operational-work-shift-close-attest")
        and route_allowed("POST", "/operational-work-items/demo-work/handoff")
        and "demo_supplier_response_unavailable" in api_text
        and not route_allowed("POST", "/demo/supplier-rfqs/demo-rfq/simulate-response")
        and "Demo mailbox" in app_js and "Sentetik Outlook Analizini Başlat" in app_js
        and "Sentetik Outlook Gelen Kutusu" in app_js and "/inbound/outlook/pull" in app_js
        and "Ham mail gövdesi bu özet yüzeyine taşınmaz" in app_js
        and "run_demo_outlook_pull" in api_text
        and "Demo'yu Sıfırla ve Yeniden Doldur" in app_js and '/demo/reset' in app_js
        and 'confirmation:"RESET_DEMO"' in app_js and 'reset_demo_sandbox' in api_text
        and 'demo_web_session_required' in api_text and not route_allowed("POST", "/demo/reset")
        and "Master Veri" in app_js and "Müşteri Oluştur" in app_js and "Tedarikçi Oluştur" in app_js
        and route_allowed("POST", "/master-data/customers") and route_allowed("POST", "/master-data/suppliers")
        and "Müşteri Hafızası · Demo" in app_js and "/customer-memory/import/dry-run" in app_js
        and not route_allowed("POST", "/customer-memory") and not route_allowed("PUT", "/customer-memory"),
        "browser shell exposes synthetic inbound and relationship workflows without hiding demo mode",
    )

    return {"name": "Synthetic demo sandbox", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_demo_sandbox_regressions()
    print("\nDemo sandbox regressions:", "PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)
