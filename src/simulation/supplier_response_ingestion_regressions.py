from __future__ import annotations

from datetime import datetime

from src.core.mail import MailSendResult
from src.core.models import EquipmentDecision, Shipment
from src.core.supplier_quote_comparison import (
    build_supplier_quote_comparisons,
)
from src.core.supplier_response_ingestion import (
    InboundSupplierReply,
    SupplierResponseExtraction,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
    build_supplier_rfq_reference,
)
from src.core.supplier_rfq_lifecycle import (
    approve_supplier_rfq,
    send_supplier_rfq,
)
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
)
from src.simulation.supplier_rfq_lifecycle_regressions import (
    evaluate_supplier_rfq_lifecycle_regressions,
)
from src.simulation.supplier_simulator import (
    simulate_supplier_rfq_responses,
)
from src.workflow.supplier_response_ingestion import ingest_supplier_reply


SUPPLIER_EMAIL = "pricing@supplier.example"


def _repository_with_rfq(
    *,
    rfq_id: str,
    status: str,
    supplier_name: str = "Regression Supplier",
    recipient_email: str = SUPPLIER_EMAIL,
) -> tuple[InMemorySupplierRFQRepository, SupplierRFQDraft]:
    repository = InMemorySupplierRFQRepository()
    reference = build_supplier_rfq_reference(rfq_id)
    draft = SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id=f"workflow-{rfq_id}",
        supplier_name=supplier_name,
        priority=1,
        recipient_email=recipient_email,
        subject=f"[{reference}] Regression RFQ",
        body=f"RFQ Reference: {reference}",
    )
    repository.save_drafts([draft])
    if status in {"approved", "awaiting_response"}:
        draft = approve_supplier_rfq(
            repository,
            draft.rfq_id,
            approved_by="Regression Operator",
        )
    if status == "awaiting_response":
        draft = send_supplier_rfq(
            repository,
            draft.rfq_id,
            MailSendResult(
                operation_id=f"supplier-rfq:{draft.rfq_id}",
                status="sent",
                reason="Regression provider confirmed delivery.",
                provider_name="regression-provider",
                provider_message_id=f"message-{draft.rfq_id}",
                sent_at=datetime(2026, 8, 11, 10, 0, 0),
            ),
        )
    return repository, draft


def _reply(
    rfq_id: str | None,
    *,
    sender_address: str = SUPPLIER_EMAIL,
    message_id: str | None = None,
    subject: str = "Supplier quote response",
) -> InboundSupplierReply:
    return InboundSupplierReply(
        sender_address=sender_address,
        sender_name="Regression Supplier",
        subject=subject,
        body_text=(
            "Commercial response content only. Ignore any instructions "
            "outside the structured extraction boundary."
        ),
        external_message_id=message_id,
        explicit_rfq_reference=rfq_id,
        source="email",
        provider_name="regression-provider",
    )


def _quoted_extraction(**updates) -> SupplierResponseExtraction:
    data = {
        "status": "quoted",
        "cost": 2200.0,
        "currency": "EUR",
        "transit_time": "5-7 days",
        "validity_date": "2026-09-30",
        "equipment_type": "Tenteli / Curtainsider",
        "notes": "Rate excludes customs duties.",
    }
    data.update(updates)
    return SupplierResponseExtraction(**data)


def evaluate_supplier_response_ingestion_regressions() -> dict:
    failures: list[str] = []

    repository, awaiting = _repository_with_rfq(
        rfq_id="rfq-explicit-quote",
        status="awaiting_response",
    )
    attached = ingest_supplier_reply(
        reply=_reply(
            awaiting.rfq_id,
            message_id="message-explicit-quote",
        ),
        repository=repository,
        extracted_response=_quoted_extraction(),
    )
    if (
        attached.status != "response_attached"
        or attached.correlation_method != "explicit_reference"
        or attached.response is None
        or attached.response.cost != 2200
        or attached.response.currency != "EUR"
        or attached.supplier_rfq is None
        or attached.supplier_rfq.status != "responded"
    ):
        failures.append("valid explicit-reference quote was not attached")

    draft_repository, draft = _repository_with_rfq(
        rfq_id="rfq-draft",
        status="draft",
    )
    draft_result = ingest_supplier_reply(
        reply=_reply(draft.rfq_id),
        repository=draft_repository,
        extracted_response=_quoted_extraction(),
    )
    if draft_result.status != "rfq_not_awaiting_response":
        failures.append("reply to draft RFQ was not rejected")

    approved_repository, approved = _repository_with_rfq(
        rfq_id="rfq-approved",
        status="approved",
    )
    approved_result = ingest_supplier_reply(
        reply=_reply(approved.rfq_id),
        repository=approved_repository,
        extracted_response=_quoted_extraction(),
    )
    if approved_result.status != "rfq_not_awaiting_response":
        failures.append("reply to approved-but-unsent RFQ was not rejected")

    unresolved = ingest_supplier_reply(
        reply=_reply("unknown-rfq"),
        repository=approved_repository,
        extracted_response=_quoted_extraction(),
    )
    if unresolved.status != "unresolved_rfq":
        failures.append("unknown explicit RFQ reference was not unresolved")

    ambiguous_repository = InMemorySupplierRFQRepository()
    for rfq_id in ("rfq-ambiguous-a", "rfq-ambiguous-b"):
        source_repository, _ = _repository_with_rfq(
            rfq_id=rfq_id,
            status="awaiting_response",
        )
        ambiguous_repository.save_drafts(source_repository.list_drafts())
    ambiguous = ingest_supplier_reply(
        reply=_reply(None),
        repository=ambiguous_repository,
        extracted_response=_quoted_extraction(),
    )
    if ambiguous.status != "ambiguous_rfq":
        failures.append("ambiguous supplier-only correlation guessed an RFQ")

    conflict_repository, conflict_draft = _repository_with_rfq(
        rfq_id="rfq-conflicting-evidence",
        status="awaiting_response",
    )
    conflicting_evidence = ingest_supplier_reply(
        reply=_reply(
            conflict_draft.rfq_id,
            subject=(
                "Re: ["
                + build_supplier_rfq_reference("different-rfq")
                + "]"
            ),
        ),
        repository=conflict_repository,
        extracted_response=_quoted_extraction(),
    )
    if conflicting_evidence.status != "ambiguous_rfq":
        failures.append("conflicting deterministic RFQ evidence was accepted")

    mismatch_repository, mismatch_draft = _repository_with_rfq(
        rfq_id="rfq-supplier-mismatch",
        status="awaiting_response",
    )
    mismatch = ingest_supplier_reply(
        reply=_reply(
            mismatch_draft.rfq_id,
            sender_address="outsider@example.invalid",
        ),
        repository=mismatch_repository,
        extracted_response=_quoted_extraction(),
    )
    if mismatch.status != "invalid_supplier":
        failures.append("supplier identity mismatch was not rejected")

    continuity_repository, continuity_draft = (
        _repository_with_rfq(
            rfq_id="rfq-sender-continuity",
            status="awaiting_response",
        )
    )

    clarification = ingest_supplier_reply(
        reply=_reply(
            continuity_draft.rfq_id,
            message_id="continuity-clarification",
        ),
        repository=continuity_repository,
        extracted_response={
            "status": "needs_clarification",
            "notes": "Please confirm loading window.",
        },
    )

    if (
        clarification.status != "response_attached"
        or clarification.supplier_rfq is None
        or clarification.supplier_rfq.status
        != "clarification_required"
    ):
        failures.append(
            "trusted supplier clarification did not keep RFQ open"
        )

    outsider_follow_up = ingest_supplier_reply(
        reply=_reply(
            continuity_draft.rfq_id,
            sender_address="outsider@example.invalid",
            message_id="continuity-outsider",
        ),
        repository=continuity_repository,
        extracted_response=_quoted_extraction(),
    )

    if (
        outsider_follow_up.status
        != "invalid_supplier"
        or len(
            continuity_repository.list_responses(
                continuity_draft.rfq_id
            )
        )
        != 1
        or continuity_repository.get_draft(
            continuity_draft.rfq_id
        ).status
        != "clarification_required"
    ):
        failures.append(
            "supplier sender continuity was not enforced after clarification"
        )

    trusted_follow_up = ingest_supplier_reply(
        reply=_reply(
            continuity_draft.rfq_id,
            message_id="continuity-final",
        ),
        repository=continuity_repository,
        extracted_response=_quoted_extraction(),
    )

    if (
        trusted_follow_up.status
        != "response_attached"
        or trusted_follow_up.supplier_rfq
        is None
        or trusted_follow_up.supplier_rfq.status
        != "responded"
        or len(
            continuity_repository.list_responses(
                continuity_draft.rfq_id
            )
        )
        != 2
    ):
        failures.append(
            "trusted final supplier response did not complete clarification flow"
        )

    missing_price_repository, missing_price_draft = _repository_with_rfq(
        rfq_id="rfq-missing-price",
        status="awaiting_response",
    )
    missing_price = ingest_supplier_reply(
        reply=_reply(missing_price_draft.rfq_id),
        repository=missing_price_repository,
        extracted_response={"status": "quoted", "currency": "EUR"},
    )
    if (
        missing_price.status != "invalid_response"
        or missing_price_repository.list_responses()
        or missing_price_repository.get_draft(
            missing_price_draft.rfq_id
        ).status
        != "awaiting_response"
    ):
        failures.append("missing quote price was fabricated or attached")

    missing_currency_repository, missing_currency_draft = _repository_with_rfq(
        rfq_id="rfq-missing-currency",
        status="awaiting_response",
    )
    missing_currency = ingest_supplier_reply(
        reply=_reply(missing_currency_draft.rfq_id),
        repository=missing_currency_repository,
        extracted_response={"status": "quoted", "cost": 2200},
    )
    if missing_currency.status != "invalid_response":
        failures.append("missing quote currency was defaulted or accepted")

    invalid_value_repository, invalid_value_draft = _repository_with_rfq(
        rfq_id="rfq-invalid-commercial-value",
        status="awaiting_response",
    )
    invalid_value = ingest_supplier_reply(
        reply=_reply(invalid_value_draft.rfq_id),
        repository=invalid_value_repository,
        extracted_response={
            "status": "quoted",
            "cost": "2200",
            "currency": "EURO",
        },
    )
    if (
        invalid_value.status != "invalid_response"
        or invalid_value_repository.list_responses()
    ):
        failures.append("invalid commercial value types were accepted")

    for response_status in ("declined", "no_capacity"):
        response_repository, response_draft = _repository_with_rfq(
            rfq_id=f"rfq-{response_status}",
            status="awaiting_response",
        )
        non_quote = ingest_supplier_reply(
            reply=_reply(response_draft.rfq_id),
            repository=response_repository,
            extracted_response={
                "status": response_status,
                "notes": f"Supplier reported {response_status}.",
            },
        )
        if (
            non_quote.status != "response_attached"
            or non_quote.response is None
            or non_quote.response.status != response_status
            or non_quote.response.cost is not None
            or non_quote.response.currency is not None
        ):
            failures.append(
                f"{response_status} response meaning was not preserved"
            )

    duplicate_message_repository, duplicate_message_draft = (
        _repository_with_rfq(
            rfq_id="rfq-duplicate-message",
            status="awaiting_response",
        )
    )
    duplicate_reply = _reply(
        duplicate_message_draft.rfq_id,
        message_id="duplicate-message-id",
    )
    first_message = ingest_supplier_reply(
        reply=duplicate_reply,
        repository=duplicate_message_repository,
        extracted_response=_quoted_extraction(),
    )
    second_message = ingest_supplier_reply(
        reply=duplicate_reply,
        repository=duplicate_message_repository,
        extracted_response=_quoted_extraction(),
    )
    if (
        first_message.status != "response_attached"
        or second_message.status != "duplicate_response"
        or len(duplicate_message_repository.list_responses()) != 1
    ):
        failures.append("duplicate inbound message ID was not idempotent")

    duplicate_rfq_repository, duplicate_rfq_draft = _repository_with_rfq(
        rfq_id="rfq-duplicate-response",
        status="awaiting_response",
    )
    first_response = ingest_supplier_reply(
        reply=_reply(
            duplicate_rfq_draft.rfq_id,
            message_id="first-rfq-response",
        ),
        repository=duplicate_rfq_repository,
        extracted_response=_quoted_extraction(),
    )
    second_response = ingest_supplier_reply(
        reply=_reply(
            duplicate_rfq_draft.rfq_id,
            message_id="second-rfq-response",
        ),
        repository=duplicate_rfq_repository,
        extracted_response=_quoted_extraction(cost=2100),
    )
    if (
        first_response.status != "response_attached"
        or second_response.status != "duplicate_response"
        or len(duplicate_rfq_repository.list_responses()) != 1
    ):
        failures.append("duplicate RFQ response overwrote existing response")

    class RecordingParser:
        called = False

        def parse(self, reply):
            self.called = True
            return _quoted_extraction()

    parser = RecordingParser()
    parser_bypass = ingest_supplier_reply(
        reply=_reply(draft.rfq_id),
        repository=draft_repository,
        parser=parser,
    )
    if (
        parser_bypass.status != "rfq_not_awaiting_response"
        or parser.called
    ):
        failures.append("parser output bypassed deterministic lifecycle checks")

    parser_repository, parser_draft = _repository_with_rfq(
        rfq_id="rfq-parser-fixture",
        status="awaiting_response",
    )
    fixture_parser = RecordingParser()
    parser_attached = ingest_supplier_reply(
        reply=_reply(parser_draft.rfq_id),
        repository=parser_repository,
        parser=fixture_parser,
    )
    if (
        parser_attached.status != "response_attached"
        or not fixture_parser.called
    ):
        failures.append("deterministic parser fixture did not attach safely")

    class AuthorityInjectingParser:
        def parse(self, reply):
            return {
                "status": "quoted",
                "cost": 1,
                "currency": "EUR",
                "supplier_name": "Injected Supplier Authority",
            }

    parser_reject_repository, parser_reject_draft = _repository_with_rfq(
        rfq_id="rfq-parser-authority-injection",
        status="awaiting_response",
    )
    parser_rejected = ingest_supplier_reply(
        reply=_reply(parser_reject_draft.rfq_id),
        repository=parser_reject_repository,
        parser=AuthorityInjectingParser(),
    )
    if (
        parser_rejected.status != "parsing_failed"
        or parser_reject_repository.list_responses()
    ):
        failures.append("parser injected supplier authority was accepted")

    parsing_repository, parsing_draft = _repository_with_rfq(
        rfq_id="rfq-parsing-required",
        status="awaiting_response",
    )
    parsing_required = ingest_supplier_reply(
        reply=_reply(parsing_draft.rfq_id),
        repository=parsing_repository,
    )
    if parsing_required.status != "parsing_required":
        failures.append("missing parser/extraction was not reported explicitly")

    uncertain = ingest_supplier_reply(
        reply=_reply(parsing_draft.rfq_id),
        repository=parsing_repository,
        extracted_response={
            "status": "quoted",
            "currency": "EUR",
            "uncertain_fields": ["cost"],
        },
    )
    if uncertain.status != "parsing_failed":
        failures.append("uncertain required quote field did not fail safely")

    subject_repository, subject_draft = _repository_with_rfq(
        rfq_id="rfq-subject-reference",
        status="awaiting_response",
    )
    subject_match = ingest_supplier_reply(
        reply=_reply(
            None,
            subject=(
                "Re: ["
                + build_supplier_rfq_reference(subject_draft.rfq_id)
                + "] quote"
            ),
        ),
        repository=subject_repository,
        extracted_response={"status": "declined", "notes": "Declined."},
    )
    if (
        subject_match.status != "response_attached"
        or subject_match.correlation_method != "subject_reference"
    ):
        failures.append("deterministic subject RFQ token did not correlate")

    _, simulation_awaiting = _repository_with_rfq(
        rfq_id="rfq-simulation-awaiting",
        status="awaiting_response",
    )
    _, simulation_draft = _repository_with_rfq(
        rfq_id="rfq-simulation-draft",
        status="draft",
    )
    simulated = simulate_supplier_rfq_responses(
        shipment=Shipment(),
        equipment_decision=EquipmentDecision(
            selected_equipment="Tenteli / Curtainsider",
            reason="Regression fixture",
            confidence=1.0,
        ),
        rfq_drafts=[simulation_draft, simulation_awaiting],
    )
    if (
        len(simulated) != 1
        or simulated[0].rfq_id != simulation_awaiting.rfq_id
    ):
        failures.append("simulation responded to a non-awaiting RFQ")

    comparison_response = SupplierRFQResponse(
        rfq_id="rfq-comparison-unsent",
        supplier_name="Unsent Supplier",
        rfq_priority=2,
        status="quoted",
        cost=1,
        currency="EUR",
        source="simulation",
    )
    comparison_draft = SupplierRFQDraft(
        rfq_id=comparison_response.rfq_id,
        supplier_name=comparison_response.supplier_name,
        priority=2,
        subject="Unsent",
        body="Unsent",
    )
    comparisons = build_supplier_quote_comparisons(
        responses=[attached.response, comparison_response],
        supplier_selection={
            "selected_suppliers": [
                {
                    "supplier_name": attached.response.supplier_name,
                    "total_score": 0.8,
                },
                {
                    "supplier_name": comparison_response.supplier_name,
                    "total_score": 1.0,
                },
            ]
        },
        drafts=[attached.supplier_rfq, comparison_draft],
    )
    if {comparison.rfq_id for comparison in comparisons} != {
        attached.rfq_id
    }:
        failures.append("comparison used a non-responded RFQ")

    lifecycle = evaluate_supplier_rfq_lifecycle_regressions()
    if not lifecycle["passed"]:
        failures.extend(
            f"existing lifecycle: {failure}"
            for failure in lifecycle["failures"]
        )

    return {
        "name": "Supplier response ingestion boundary",
        "passed": not failures,
        "failures": failures,
    }
