from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from src.ai.supplier_response_parser import (
    OpenAISupplierResponseParser,
)
from src.core.mail import MailSendResult
from src.core.privacy import (
    PrivacyBoundaryError,
    PrivacySafeText,
    prepare_privacy_safe_text,
)
from src.core.supplier_response_ingestion import (
    SupplierResponseExtraction,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    build_supplier_rfq_reference,
)
from src.core.supplier_rfq_lifecycle import (
    approve_supplier_rfq,
    send_supplier_rfq,
)
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
)
from src.core.mail import InboundMailEnvelope
from src.workflow.supplier_response_ingestion import (
    ingest_supplier_reply,
)


SUPPLIER_EMAIL = "pricing@supplier.example"


def _repository():
    repository = InMemorySupplierRFQRepository()

    rfq_id = "rfq-p1-20a"
    reference = build_supplier_rfq_reference(
        rfq_id
    )

    draft = SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id="workflow-p1-20a",
        supplier_name="Regression Supplier",
        priority=1,
        recipient_email=SUPPLIER_EMAIL,
        subject=f"[{reference}] Freight RFQ",
        body=f"RFQ Reference: {reference}",
    )

    repository.save_drafts([draft])

    draft = approve_supplier_rfq(
        repository,
        rfq_id,
        approved_by="Regression Operator",
    )

    draft = send_supplier_rfq(
        repository,
        rfq_id,
        MailSendResult(
            operation_id=f"supplier-rfq:{rfq_id}",
            status="sent",
            reason="Regression provider confirmed delivery.",
            provider_name="regression-provider",
            provider_message_id="outbound-p1-20a",
            sent_at=datetime(
                2026,
                8,
                19,
                8,
                0,
                0,
            ),
        ),
    )

    return repository, draft


def _reply(
    rfq_id: str,
    *,
    sender: str = SUPPLIER_EMAIL,
    message_id: str = "inbound-p1-20a",
):
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id="pilot@example.invalid",
        sender_address=sender,
        sender_name="Supplier Person",
        subject=(
            f"Re: [{build_supplier_rfq_reference(rfq_id)}]"
        ),
        body_text=(
            "We quote EUR 2200 all in.\n"
            "Contact pricing@supplier.example\n"
            "Best regards\n"
            "Supplier Person\n"
            "+90 555 111 22 33"
        ),
        received_at=datetime(
            2026,
            8,
            19,
            9,
            0,
            0,
        ),
        explicit_rfq_reference=rfq_id,
        source="email",
    )


def evaluate_supplier_response_privacy_regressions():
    failures = []
    passes = []

    def check(condition, label):
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    class CapturingParser:
        def __init__(self):
            self.calls = []

        def parse(self, reply_text):
            self.calls.append(reply_text)
            return SupplierResponseExtraction(
                status="quoted",
                cost=2200.0,
                currency="EUR",
            )

    repository, draft = _repository()
    parser = CapturingParser()

    result = ingest_supplier_reply(
        reply=_reply(draft.rfq_id),
        repository=repository,
        parser=parser,
    )

    parsed_text = (
        parser.calls[0]
        if parser.calls
        else None
    )

    check(
        result.status == "response_attached"
        and len(parser.calls) == 1
        and isinstance(
            parsed_text,
            PrivacySafeText,
        ),
        "supplier parser receives PrivacySafeText only",
    )

    check(
        parsed_text is not None
        and "pricing@supplier.example"
        not in str(parsed_text)
        and "<EMAIL_REDACTED>"
        in str(parsed_text)
        and "Supplier Person"
        not in str(parsed_text)
        and "+90 555" not in str(parsed_text),
        "supplier raw contact data removed before parser",
    )

    mismatch_repository, mismatch_draft = (
        _repository()
    )
    mismatch_parser = CapturingParser()

    mismatch = ingest_supplier_reply(
        reply=_reply(
            mismatch_draft.rfq_id,
            sender="outsider@example.invalid",
            message_id="mismatch-p1-20a",
        ),
        repository=mismatch_repository,
        parser=mismatch_parser,
    )

    check(
        mismatch.status == "invalid_supplier"
        and not mismatch_parser.calls,
        "deterministic supplier identity blocks before parser",
    )

    fake_completions = SimpleNamespace()

    def fake_parse(**kwargs):
        fake_completions.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        parsed=SupplierResponseExtraction(
                            status="quoted",
                            cost=2300.0,
                            currency="EUR",
                            transit_time="5-7 days",
                        )
                    )
                )
            ]
        )

    fake_completions.parse = fake_parse

    fake_client = SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(
                completions=fake_completions
            )
        )
    )

    production_parser = (
        OpenAISupplierResponseParser(
            client=fake_client,
            model="regression-model",
        )
    )

    raw_rejected = False

    try:
        production_parser.parse(
            "raw supplier reply"
        )
    except PrivacyBoundaryError:
        raw_rejected = True

    check(
        raw_rejected
        and not hasattr(
            fake_completions,
            "kwargs",
        ),
        "production parser rejects raw text before provider",
    )

    safe_text = prepare_privacy_safe_text(
        "We quote EUR 2300 all in."
    ).safe_text

    parsed = production_parser.parse(
        safe_text
    )

    request = fake_completions.kwargs

    check(
        parsed.status == "quoted"
        and parsed.cost == 2300.0
        and parsed.currency == "EUR",
        "production parser returns structured commercial fields",
    )

    check(
        request["model"] == "regression-model"
        and request["response_format"]
        is SupplierResponseExtraction
        and request["messages"][1]["content"]
        is safe_text,
        "production parser uses strict structured response contract",
    )

    check(
        "supplier@example"
        not in str(
            request["messages"][1]["content"]
        )
        and "rfq-p1-20a"
        not in str(
            request["messages"][1]["content"]
        ),
        "production AI request carries no supplier or RFQ authority",
    )

    return {
        "name": (
            "Supplier response privacy boundary"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_supplier_response_privacy_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nSupplier response privacy "
            "regressions: PASS"
        )
        return 0

    print(
        "\nSupplier response privacy "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
