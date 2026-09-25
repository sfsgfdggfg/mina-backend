from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.agency_copy_receipt import (
    InMemoryAgencyCopyReceiptRepository,
    SQLiteAgencyCopyReceiptRepository,
)
from src.core.agency_learning_bootstrap import build_candidate_snapshot
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job, link_mina_job_workflow
from src.core.models import Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.relationship_history import HistoricalMailMessage
from src.core.supplier_rfq import SupplierRFQDraft
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.integrations.outlook_graph import normalize_graph_message
from src.workflow.agency_copy_ingestion import is_agency_copied_mail
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail


UTC = timezone.utc
NOW = datetime(2026, 9, 25, 8, 0, tzinfo=UTC)
MAILBOX = "info@agency.test"
AGENCY_USER = "nebi@agency.test"
OTHER_DOMAIN_AGENCY = "operator@agency-partner.test"
CUSTOMER = "ops@customer.test"
SUPPLIER = "pricing@supplier.test"


class _Parser:
    def __init__(self, shipment: ShipmentProposalSnapshot):
        self.shipment = shipment
        self.calls = 0

    def __call__(self, _safe_text):
        self.calls += 1
        return self.shipment.model_copy(deep=True)


def _masters():
    repository = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=repository,
        entry_id="customer",
        customer_name="Customer A",
        updated_by="regression",
        created_at=NOW,
        trusted_sender_addresses=[CUSTOMER],
    )
    supplier = create_supplier_master(
        repository=repository,
        entry_id="supplier",
        supplier_name="Supplier A",
        updated_by="regression",
        created_at=NOW,
        trusted_sender_addresses=[SUPPLIER],
    )
    return repository, customer, supplier


def _mail(
    *,
    message_id: str,
    sender: str,
    to: list[str],
    cc: list[str] | None = None,
    subject: str,
    body: str,
) -> InboundMailEnvelope:
    cc = cc or []
    recipients = list(dict.fromkeys([*to, *cc]))
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address=sender,
        recipient_addresses=recipients,
        to_addresses=to,
        cc_addresses=cc,
        subject=subject,
        body_text=body,
        received_at=NOW,
        has_attachments=False,
        source="email",
    )


def _route(
    *,
    mail,
    parser,
    masters,
    proposals,
    jobs=None,
    receipts=None,
    supplier_repository=None,
):
    return process_controlled_outlook_inbound_mail(
        mail=mail,
        shipment_parser=parser,
        supplier_parser=None,
        proposal_repository=proposals,
        supplier_repository=(
            supplier_repository or InMemorySupplierRFQRepository()
        ),
        operational_data_sources=None,
        master_data_repository=masters,
        mina_job_repository=jobs,
        agency_copy_receipt_repository=receipts,
        agency_addresses=[MAILBOX, AGENCY_USER],
    )


def evaluate_agency_copy_mailbox_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    raw = {
        "id": "graph-cc-1",
        "subject": "Transport request",
        "body": {"contentType": "text", "content": "Adana Munich 12 ton"},
        "from": {"emailAddress": {"address": CUSTOMER, "name": "Customer"}},
        "toRecipients": [
            {"emailAddress": {"address": AGENCY_USER, "name": "Nebi"}}
        ],
        "ccRecipients": [
            {"emailAddress": {"address": MAILBOX, "name": "MINAI"}}
        ],
        "bccRecipients": [],
        "receivedDateTime": NOW.isoformat(),
        "hasAttachments": False,
        "isDraft": False,
    }
    normalized = normalize_graph_message(raw, mailbox_id=MAILBOX)
    check(
        normalized.to_addresses == [AGENCY_USER]
        and normalized.cc_addresses == [MAILBOX]
        and normalized.bcc_addresses == []
        and normalized.recipient_addresses == [AGENCY_USER, MAILBOX],
        "Graph operational envelope preserves To and CC roles while keeping the provider-neutral recipient union",
    )

    masters, customer, supplier = _masters()
    proposals = InMemoryExtractionProposalRepository()
    customer_parser = _Parser(
        ShipmentProposalSnapshot(
            customer_name="ignored parser identity",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
            gross_weight_kg=12000,
        )
    )
    customer_copy = _mail(
        message_id="customer-cc",
        sender=CUSTOMER,
        to=[AGENCY_USER],
        cc=[MAILBOX],
        subject="Adana Munich taşıma talebi",
        body="Adana yükleme Münih teslim 12 ton tenteli.",
    )
    customer_result = _route(
        mail=customer_copy,
        parser=customer_parser,
        masters=masters,
        proposals=proposals,
    )
    customer_proposal = customer_result.get("extraction_proposal")
    check(
        customer_result.get("inbound_route") == "customer"
        and customer_proposal is not None
        and customer_proposal.evidence_origin == "customer_authored"
        and customer_proposal.trusted_customer_name == customer.customer_name,
        "customer mail sent to another agency address with MINAI in CC stays on the existing trusted-customer intake path",
    )

    proposals2 = InMemoryExtractionProposalRepository()
    receipts2 = InMemoryAgencyCopyReceiptRepository()
    agency_parser = _Parser(
        ShipmentProposalSnapshot(
            customer_name="Customer A",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
            gross_weight_kg=12500,
        )
    )
    agency_to_customer = _mail(
        message_id="agency-to-customer",
        sender=AGENCY_USER,
        to=[CUSTOMER],
        cc=[MAILBOX],
        subject="Adana Munich navlun",
        body="Adana yükleme, Munich delivery, 12.5 ton tenteli navlun çalışıyoruz.",
    )
    new_work = _route(
        mail=agency_to_customer,
        parser=agency_parser,
        masters=masters,
        proposals=proposals2,
        receipts=receipts2,
    )
    new_work_proposal = new_work.get("extraction_proposal")
    check(
        new_work.get("result_type") == "agency_copy_new_work_candidate"
        and new_work.get("inbound_route") == "agency_copy"
        and new_work_proposal is not None
        and new_work_proposal.evidence_origin == "agency_copied"
        and new_work_proposal.trusted_customer_name == customer.customer_name,
        "agency-authored mail to a known customer with MINAI copied creates a reviewable new-work candidate without pretending the customer authored it",
    )
    duplicate = _route(
        mail=agency_to_customer,
        parser=agency_parser,
        masters=masters,
        proposals=proposals2,
        receipts=receipts2,
    )
    check(
        duplicate.get("result_type") == "agency_copy_duplicate"
        and agency_parser.calls == 1
        and len(proposals2.list_all()) == 1,
        "agency-copy receipt prevents repeated polling from reparsing or duplicating the same copied message",
    )

    proposals3 = InMemoryExtractionProposalRepository()
    receipts3 = InMemoryAgencyCopyReceiptRepository()
    supplier_copy_parser = _Parser(
        ShipmentProposalSnapshot(
            customer_name="Customer A",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
            commodity="textile",
        )
    )
    agency_to_supplier = _mail(
        message_id="agency-to-supplier",
        sender=AGENCY_USER,
        to=[SUPPLIER],
        cc=[MAILBOX],
        subject="Customer A / Adana Munich navlun teklif",
        body="Customer A için Adana yükleme Munich delivery tenteli navlun teklifinizi rica ederiz.",
    )
    supplier_new_work = _route(
        mail=agency_to_supplier,
        parser=supplier_copy_parser,
        masters=masters,
        proposals=proposals3,
        receipts=receipts3,
    )
    check(
        supplier_new_work.get("result_type") == "agency_copy_new_work_candidate"
        and supplier_new_work.get("counterparty_type") == "supplier"
        and supplier_new_work.get("extraction_proposal") is not None
        and supplier_new_work["extraction_proposal"].evidence_origin == "agency_copied",
        "first visible agency-to-supplier copied mail can create a reviewable new-work candidate when customer identity and route resolve safely",
    )

    jobs = InMemoryMinaJobRepository()
    existing = create_manual_mina_job(
        repository=jobs,
        manual_intake_id="existing-job",
        intake_channel="email",
        job_kind="price_request",
        shipment=Shipment(
            customer_name="Customer A",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
            commodity="textile",
            gross_weight_kg=None,
            is_adr=False,
        ),
        opened_by="regression",
        opened_at=NOW,
    )
    update_parser = _Parser(
        ShipmentProposalSnapshot(
            customer_name="Customer A",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
            commodity="machinery",
            gross_weight_kg=15000,
            is_adr=True,
        )
    )
    update_mail = _mail(
        message_id="agency-update",
        sender=AGENCY_USER,
        to=[CUSTOMER],
        cc=[MAILBOX],
        subject="Adana Munich 15 ton",
        body="Adana yükleme Munich teslim 15 ton. MINA referansı yazılmadı.",
    )
    update_result = _route(
        mail=update_mail,
        parser=update_parser,
        masters=masters,
        proposals=InMemoryExtractionProposalRepository(),
        jobs=jobs,
        receipts=InMemoryAgencyCopyReceiptRepository(),
    )
    updated = jobs.get(existing.job_id)
    check(
        update_result.get("result_type") == "agency_copy_job_observation"
        and update_result.get("correlation_method") == "customer_route_unique_open_job"
        and updated is not None
        and updated.shipment.gross_weight_kg == 15000
        and updated.shipment.commodity == "textile"
        and updated.shipment.is_adr is False
        and set(update_result.get("changed_fields") or []) == {"gross_weight_kg"},
        "unique customer-plus-route correlation fills only missing non-safety fields and never overwrites existing or safety-sensitive shipment facts",
    )
    events = [
        event
        for event in jobs.list_events(existing.job_id)
        if event.event_type == "agency_copied_mail_observed"
    ]
    check(
        len(events) == 1
        and events[0].metadata.get("changed_fields") == ["gross_weight_kg"]
        and "body_text" not in repr(events[0].metadata),
        "existing-job agency-copy observation is durably audited without persisting raw mail content in the job event",
    )

    jobs_ambiguous = InMemoryMinaJobRepository()
    for index in (1, 2):
        create_manual_mina_job(
            repository=jobs_ambiguous,
            manual_intake_id=f"ambiguous-{index}",
            intake_channel="email",
            job_kind="price_request",
            shipment=Shipment(
                customer_name="Customer A",
                pickup_country="TR",
                pickup_city="Adana",
                delivery_country="DE",
                delivery_city="Munich",
            ),
            opened_by="regression",
            opened_at=NOW,
        )
    ambiguous = _route(
        mail=_mail(
            message_id="ambiguous-copy",
            sender=AGENCY_USER,
            to=[CUSTOMER],
            cc=[MAILBOX],
            subject="Adana Munich navlun",
            body="Adana yükleme Munich delivery 10 ton tenteli.",
        ),
        parser=_Parser(
            ShipmentProposalSnapshot(
                customer_name="Customer A",
                pickup_country="TR",
                pickup_city="Adana",
                delivery_country="DE",
                delivery_city="Munich",
                gross_weight_kg=10000,
            )
        ),
        masters=masters,
        proposals=InMemoryExtractionProposalRepository(),
        jobs=jobs_ambiguous,
        receipts=InMemoryAgencyCopyReceiptRepository(),
    )
    check(
        ambiguous.get("result_type") == "agency_copy_manual_review_required"
        and ambiguous.get("reason_code") == "ambiguous_customer_route"
        and all(job.shipment.gross_weight_kg is None for job in jobs_ambiguous.list_all()),
        "multiple open jobs on the same customer and route fail closed instead of receiving an arbitrary copied-mail update",
    )


    supplier_jobs = InMemoryMinaJobRepository()
    supplier_job = create_manual_mina_job(
        repository=supplier_jobs,
        manual_intake_id="supplier-rfq-job",
        intake_channel="email",
        job_kind="price_request",
        shipment=Shipment(
            customer_name="Customer A",
            pickup_country="TR",
            pickup_city="Adana",
            delivery_country="DE",
            delivery_city="Munich",
        ),
        opened_by="regression",
        opened_at=NOW,
    )
    workflow_id = "workflow-copy-rfq"
    supplier_job = link_mina_job_workflow(
        repository=supplier_jobs,
        job_id=supplier_job.job_id,
        workflow_id=workflow_id,
        result_type="supplier_rfq_workflow_created",
        occurred_at=NOW,
    )
    supplier_rfq_repository = InMemorySupplierRFQRepository()
    supplier_draft = SupplierRFQDraft(
        rfq_id="rfq-copy-observed",
        workflow_id=workflow_id,
        supplier_name=supplier.supplier_name,
        priority=1,
        recipient_email=SUPPLIER,
        supplier_role="primary",
        dispatch_tier="primary",
        subject=f"{supplier_job.mina_code} // ADANA MUNICH NAVLUN TLB",
        body="Navlun teklifinizi rica ederiz.",
        status="approved",
        approved_by="regression",
        approved_at=NOW,
    )
    supplier_rfq_repository.save_drafts([supplier_draft])
    supplier_send_mail = _mail(
        message_id="agency-supplier-manual-send",
        sender=AGENCY_USER,
        to=[SUPPLIER],
        cc=[MAILBOX],
        subject=f"{supplier_job.mina_code} // ADANA MUNICH NAVLUN TLB",
        body="Adana yükleme Munich delivery için navlun teklifinizi rica ederiz.",
    )
    supplier_send_result = _route(
        mail=supplier_send_mail,
        parser=_Parser(
            ShipmentProposalSnapshot(
                customer_name="Customer A",
                pickup_country="TR",
                pickup_city="Adana",
                delivery_country="DE",
                delivery_city="Munich",
            )
        ),
        masters=masters,
        proposals=InMemoryExtractionProposalRepository(),
        jobs=supplier_jobs,
        receipts=InMemoryAgencyCopyReceiptRepository(),
        supplier_repository=supplier_rfq_repository,
    )
    refreshed_draft = supplier_rfq_repository.get_draft(supplier_draft.rfq_id)
    check(
        supplier_send_result.get("result_type") == "agency_copy_job_observation"
        and supplier_send_result.get("rfq_id") == supplier_draft.rfq_id
        and refreshed_draft is not None
        and refreshed_draft.status == "awaiting_response"
        and len(
            supplier_rfq_repository.list_manual_sent_evidence(
                supplier_draft.rfq_id
            )
        ) == 1,
        "agency-to-supplier copied RFQ reuses existing approved manual-sent evidence lifecycle instead of creating parallel send state",
    )

    with TemporaryDirectory() as tmp:
        sqlite_path = Path(tmp) / "agency-copy.sqlite3"
        first_store = SQLitePilotStore(sqlite_path)
        persistent_receipts = SQLiteAgencyCopyReceiptRepository(first_store)
        persistent_proposals = InMemoryExtractionProposalRepository()
        persistent_parser = _Parser(
            ShipmentProposalSnapshot(
                customer_name="Customer A",
                pickup_country="TR",
                pickup_city="Adana",
                delivery_country="DE",
                delivery_city="Munich",
                gross_weight_kg=9000,
            )
        )
        persistent_mail = _mail(
            message_id="persistent-agency-copy",
            sender=AGENCY_USER,
            to=[CUSTOMER],
            cc=[MAILBOX],
            subject="Adana Munich navlun",
            body="Adana yükleme Munich delivery 9 ton tenteli.",
        )
        first_persistent = _route(
            mail=persistent_mail,
            parser=persistent_parser,
            masters=masters,
            proposals=persistent_proposals,
            receipts=persistent_receipts,
        )
        second_receipts = SQLiteAgencyCopyReceiptRepository(
            SQLitePilotStore(sqlite_path)
        )
        second_persistent = _route(
            mail=persistent_mail,
            parser=persistent_parser,
            masters=masters,
            proposals=persistent_proposals,
            receipts=second_receipts,
        )
        raw_receipts = first_store.list_all(
            namespace="agency_copy_mail_receipts"
        )
        persisted_text = json.dumps(raw_receipts, ensure_ascii=False).casefold()
        check(
            first_persistent.get("result_type") == "agency_copy_new_work_candidate"
            and second_persistent.get("result_type") == "agency_copy_duplicate"
            and persistent_parser.calls == 1
            and len(raw_receipts) == 1
            and persistent_mail.body_text.casefold() not in persisted_text
            and AGENCY_USER.casefold() not in persisted_text
            and CUSTOMER.casefold() not in persisted_text,
            "agency-copy receipt survives SQLite reconstruction while persisting hashes and safe references instead of raw mail body or addresses",
        )

    alias_mail = InboundMailEnvelope(
        external_message_id="external-alias",
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address=OTHER_DOMAIN_AGENCY,
        recipient_addresses=[CUSTOMER, MAILBOX],
        to_addresses=[CUSTOMER],
        cc_addresses=[MAILBOX],
        subject="Adana Munich",
        body_text="Adana pickup Munich delivery 10 ton",
        received_at=NOW,
        source="email",
    )
    check(
        not is_agency_copied_mail(alias_mail)
        and is_agency_copied_mail(
            alias_mail,
            configured_agency_addresses=[OTHER_DOMAIN_AGENCY],
        ),
        "different-domain agency identities are never inferred implicitly but can be explicitly authorized as agency aliases",
    )


    learning_messages = [
        HistoricalMailMessage(
            source_reference="alias-history-1",
            sent_at=NOW,
            sender_address=OTHER_DOMAIN_AGENCY,
            recipient_addresses=[CUSTOMER, MAILBOX],
            subject="Adana Munich",
            body_text="Adana pickup Munich delivery 10 ton tenteli.",
            source="authorized_mailbox",
        ),
        HistoricalMailMessage(
            source_reference="alias-history-2",
            sent_at=NOW,
            sender_address=CUSTOMER,
            recipient_addresses=[OTHER_DOMAIN_AGENCY, MAILBOX],
            subject="Re: Adana Munich",
            body_text="Teklifinizi bekliyoruz.",
            source="authorized_mailbox",
        ),
    ]
    learned_agency_addresses, learned_candidates, _ = build_candidate_snapshot(
        messages=learning_messages,
        mailbox_id=MAILBOX,
        master_repository=masters,
        agency_alias_addresses=[OTHER_DOMAIN_AGENCY],
    )
    check(
        OTHER_DOMAIN_AGENCY in learned_agency_addresses
        and all(
            item.email_address != OTHER_DOMAIN_AGENCY
            for item in learned_candidates
        ),
        "explicit different-domain agency aliases are excluded from continuous-learning counterparty discovery instead of becoming customer or supplier candidates",
    )

    import src.api as api

    poll_payload = {
        "provider": "microsoft_graph",
        "mailbox_id": MAILBOX,
        "fetched_message_count": 1,
        "handled_message_count": 1,
        "proposal_count": 1,
        "supplier_response_count": 0,
        "supplier_operational_count": 0,
        "manual_review_count": 0,
        "pull_status": "complete",
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "results": [
            {
                "inbound_route": "agency_copy",
                "result_type": "agency_copy_new_work_candidate",
            }
        ],
    }
    old_last_at = api._inbound_mailbox_poll_last_at
    old_last_error = api._inbound_mailbox_poll_last_error
    old_last_summary = api._inbound_mailbox_poll_last_summary
    try:
        with patch.object(api, "demo_mode_enabled", return_value=False), patch.object(
            api, "_mailbox_status", return_value={
                "configured": True,
                "provider": "outlook",
                "mailbox_id": MAILBOX,
            }
        ), patch.object(
            api, "pull_active_mailbox_inbound", return_value=poll_payload
        ), patch.dict(
            os.environ,
            {
                "MINAI_INBOUND_AUTO_POLL": "true",
                "MINAI_INBOUND_POLL_SECONDS": "60",
                "MINAI_OUTBOUND_MODE": "shadow",
            },
            clear=False,
        ):
            poll_result = api._run_inbound_mailbox_poll_once()
        check(
            poll_result.get("status") == "healthy"
            and poll_result.get("agency_copy_count") == 1
            and poll_result.get("agency_copy_new_work_count") == 1
            and poll_result.get("mailbox_write_performed") is False
            and poll_result.get("automated_send_performed") is False,
            "automatic inbound polling runs independently of shadow outbound mode and remains read-only on the mailbox",
        )
    finally:
        api._inbound_mailbox_poll_last_at = old_last_at
        api._inbound_mailbox_poll_last_error = old_last_error
        api._inbound_mailbox_poll_last_summary = old_last_summary

    return {
        "name": "Agency copied mailbox ingestion",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_agency_copy_mailbox_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print(
        "\nAgency copied mailbox regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
