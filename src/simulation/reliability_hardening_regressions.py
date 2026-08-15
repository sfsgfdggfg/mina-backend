from __future__ import annotations

import os
import stat
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from src.ai.email_parser import (
    OPENAI_MAX_RETRIES,
    OPENAI_REQUEST_TIMEOUT_SECONDS,
    _build_openai_client,
)
from src.core.extraction_confirmation import (
    ShipmentProposalSnapshot,
)
from src.core.mail import (
    MAX_INBOUND_MAIL_BODY_BYTES,
    InboundMailEnvelope,
)
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
)
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
    process_customer_inquiry_mail,
)


def _proposal() -> ShipmentProposalSnapshot:
    return ShipmentProposalSnapshot(
        customer_name="Reliability Customer",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
    )


def evaluate_reliability_hardening_regressions() -> dict:
    failures: list[str] = []

    with (
        patch(
            "src.ai.email_parser.OpenAI"
        ) as client_factory,
        patch(
            "src.ai.email_parser.OPENAI_API_KEY",
            "regression-api-key",
        ),
    ):
        _build_openai_client()

    if client_factory.call_count != 1:
        failures.append(
            "OpenAI client factory was not called once"
        )
    else:
        kwargs = client_factory.call_args.kwargs

        if (
            kwargs.get("timeout")
            != OPENAI_REQUEST_TIMEOUT_SECONDS
        ):
            failures.append(
                "OpenAI request timeout is not explicit"
            )

        if (
            kwargs.get("max_retries")
            != OPENAI_MAX_RETRIES
        ):
            failures.append(
                "OpenAI retry policy is not explicit"
            )

    try:
        InboundMailEnvelope(
            body_text=(
                "x"
                * (
                    MAX_INBOUND_MAIL_BODY_BYTES
                    + 1
                )
            ),
            source="manual",
        )
    except ValidationError:
        pass
    else:
        failures.append(
            "oversized inbound mail body was accepted"
        )

    parser_calls: list[str] = []

    def parser(safe_text):
        parser_calls.append(str(safe_text))
        return _proposal()

    mail = InboundMailEnvelope(
        external_message_id="message-1",
        provider_name="reliability-provider",
        mailbox_id="operations@example.invalid",
        sender_address="customer@example.invalid",
        subject="Road freight inquiry",
        body_text=(
            "Adana to Hamburg FTL quotation request."
        ),
        source="email",
    )

    with TemporaryDirectory(
        prefix="minai-reliability-"
    ) as temp_dir:
        db_path = (
            Path(temp_dir)
            / "pilot.sqlite3"
        )

        store = SQLitePilotStore(
            db_path,
            run_id="reliability-a",
        )
        repository = (
            SQLiteExtractionProposalRepository(
                store
            )
        )

        if os.name == "posix":
            with store.transaction():
                active_storage_files = (
                    db_path,
                    Path(str(db_path) + "-wal"),
                    Path(str(db_path) + "-shm"),
                )

                for storage_file in active_storage_files:
                    if not storage_file.exists():
                        continue

                    actual_mode = stat.S_IMODE(
                        storage_file.stat().st_mode
                    )

                    if actual_mode != 0o600:
                        failures.append(
                            "active pilot SQLite storage "
                            "is not private: "
                            f"{storage_file.name}"
                        )

        first = process_customer_inquiry_mail(
            mail=mail,
            shipment_parser=parser,
            proposal_repository=repository,
        )

        restarted_store = SQLitePilotStore(
            db_path,
            run_id="reliability-b",
        )
        restarted_repository = (
            SQLiteExtractionProposalRepository(
                restarted_store
            )
        )

        second = process_customer_inquiry_mail(
            mail=mail,
            shipment_parser=parser,
            proposal_repository=(
                restarted_repository
            ),
        )

        first_proposal = first.get(
            "extraction_proposal"
        )
        second_proposal = second.get(
            "extraction_proposal"
        )

        if len(parser_calls) != 1:
            failures.append(
                "duplicate customer message reached "
                "AI/parser more than once"
            )

        if (
            first.get("ingestion_status")
            != "created"
            or second.get("ingestion_status")
            != "duplicate_existing_proposal"
        ):
            failures.append(
                "customer message idempotency status "
                "was not preserved"
            )

        if (
            first_proposal is None
            or second_proposal is None
            or first_proposal.proposal_id
            != second_proposal.proposal_id
        ):
            failures.append(
                "duplicate customer message created "
                "a second extraction proposal"
            )

        conflicting_mail = mail.model_copy(
            update={
                "body_text": (
                    "Changed body using the same "
                    "provider message ID."
                )
            }
        )

        try:
            process_customer_inquiry_mail(
                mail=conflicting_mail,
                shipment_parser=parser,
                proposal_repository=(
                    restarted_repository
                ),
            )
        except InboundMailIdempotencyConflictError:
            pass
        else:
            failures.append(
                "conflicting reuse of inbound message "
                "ID was accepted"
            )

        if len(parser_calls) != 1:
            failures.append(
                "idempotency conflict reached AI/parser"
            )

        if os.name == "posix":
            storage_files = (
                db_path,
                Path(str(db_path) + "-wal"),
                Path(str(db_path) + "-shm"),
            )

            for storage_file in storage_files:
                if not storage_file.exists():
                    continue

                actual_mode = stat.S_IMODE(
                    storage_file.stat().st_mode
                )

                if actual_mode != 0o600:
                    failures.append(
                        "pilot SQLite file is not "
                        f"private: {storage_file.name}"
                    )

    return {
        "name": "Runtime reliability hardening",
        "passed": len(failures) == 0,
        "failures": failures,
    }


if __name__ == "__main__":
    result = (
        evaluate_reliability_hardening_regressions()
    )
    print(result)
    raise SystemExit(
        0 if result["passed"] else 1
    )
