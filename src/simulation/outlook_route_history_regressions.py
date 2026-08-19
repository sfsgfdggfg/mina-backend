from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from src.core.mail import InboundMailEnvelope
from src.core.privacy import fingerprint_text
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
)
import src.workflow.outlook_inbound_router as router


MESSAGE_ID = "immutable-route-history-message"
MAILBOX = "pilot-mailbox@example.invalid"
SENDER = "customer@example.invalid"


def _mail(
    *,
    body="Need road freight quote",
    sender=SENDER,
):
    return InboundMailEnvelope(
        external_message_id=MESSAGE_ID,
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address=sender,
        recipient_addresses=[MAILBOX],
        subject="Freight request",
        body_text=body,
        received_at=datetime(
            2026,
            8,
            19,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        has_attachments=False,
        source="email",
    )


class _ProposalRepository:
    def __init__(
        self,
        mail,
    ):
        self.proposal = SimpleNamespace(
            proposal_id="proposal-route-history",
            inbound_mail=SimpleNamespace(
                raw_body_sha256=(
                    fingerprint_text(
                        mail.body_text
                    )
                ),
                sender_address=(
                    mail.sender_address
                ),
            ),
        )

    def find_by_message_key(
        self,
        message_key,
    ):
        return self.proposal


class _SupplierRepository:
    def __init__(
        self,
        evidence=None,
    ):
        self.evidence = evidence

    def get_ingested_message_evidence(
        self,
        message_key,
    ):
        if self.evidence is None:
            return None
        return dict(self.evidence)

    def has_ingested_message(
        self,
        message_key,
    ):
        return self.evidence is not None


def evaluate_outlook_route_history_regressions():
    failures = []
    passes = []

    def check(condition, label):
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    original = _mail()

    proposal_repository = (
        _ProposalRepository(
            original
        )
    )

    supplier_repository = (
        _SupplierRepository()
    )

    shipment_calls = []
    supplier_calls = []

    def shipment_parser(_):
        shipment_calls.append(True)
        raise AssertionError(
            "customer parser must not run"
        )

    def supplier_parser(_):
        supplier_calls.append(True)
        raise AssertionError(
            "supplier parser must not run"
        )

    # Current supplier state may have evolved since
    # the original customer ingestion. Route history
    # must win before current-state correlation.
    with patch.object(
        router,
        "correlate_supplier_reply",
    ) as correlation:
        result = (
            router
            .process_controlled_outlook_inbound_mail(
                mail=original,
                shipment_parser=shipment_parser,
                supplier_parser=supplier_parser,
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    supplier_repository
                ),
                operational_data_sources=None,
            )
        )

    check(
        result.get("inbound_route")
        == "customer"
        and result.get(
            "ingestion_status"
        )
        == "duplicate_existing_proposal"
        and result.get(
            "extraction_proposal"
        )
        is proposal_repository.proposal
        and correlation.call_count == 0
        and not shipment_calls
        and not supplier_calls,
        (
            "customer route history wins before "
            "new supplier correlation"
        ),
    )

    try:
        router.process_controlled_outlook_inbound_mail(
            mail=_mail(
                body="Changed commercial content"
            ),
            shipment_parser=shipment_parser,
            supplier_parser=supplier_parser,
            proposal_repository=(
                proposal_repository
            ),
            supplier_repository=(
                supplier_repository
            ),
            operational_data_sources=None,
        )
    except InboundMailIdempotencyConflictError:
        changed_body_blocked = True
    else:
        changed_body_blocked = False

    check(
        changed_body_blocked
        and not shipment_calls
        and not supplier_calls,
        (
            "customer route history rejects "
            "changed body under immutable ID"
        ),
    )

    try:
        router.process_controlled_outlook_inbound_mail(
            mail=_mail(
                sender="other@example.invalid"
            ),
            shipment_parser=shipment_parser,
            supplier_parser=supplier_parser,
            proposal_repository=(
                proposal_repository
            ),
            supplier_repository=(
                supplier_repository
            ),
            operational_data_sources=None,
        )
    except InboundMailIdempotencyConflictError:
        changed_sender_blocked = True
    else:
        changed_sender_blocked = False

    check(
        changed_sender_blocked
        and not shipment_calls
        and not supplier_calls,
        (
            "customer route history rejects "
            "changed sender under immutable ID"
        ),
    )

    evidence = {
        "message_key": (
            original.message_deduplication_key
        ),
        "body_sha256": fingerprint_text(
            original.body_text
        ),
        "sender_address": (
            original.sender_address
        ),
    }

    dual_repository = (
        _SupplierRepository(
            evidence=evidence
        )
    )

    with patch.object(
        router,
        "correlate_supplier_reply",
    ) as correlation:
        try:
            (
                router
                .process_controlled_outlook_inbound_mail(
                    mail=original,
                    shipment_parser=shipment_parser,
                    supplier_parser=supplier_parser,
                    proposal_repository=(
                        proposal_repository
                    ),
                    supplier_repository=(
                        dual_repository
                    ),
                    operational_data_sources=None,
                )
            )
        except InboundMailIdempotencyConflictError:
            dual_history_blocked = True
        else:
            dual_history_blocked = False

    check(
        dual_history_blocked
        and correlation.call_count == 0
        and not shipment_calls
        and not supplier_calls,
        (
            "conflicting customer and supplier "
            "route history fails closed"
        ),
    )

    return {
        "name": (
            "Global Outlook route history "
            "idempotency"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_outlook_route_history_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for label in result["failures"]:
        print(f"FAIL {label}")

    print(
        "\nGlobal Outlook route history "
        + (
            "regressions: PASS"
            if result["passed"]
            else "regressions: FAIL"
        )
    )

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
