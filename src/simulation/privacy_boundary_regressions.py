from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ai.email_parser import parse_email_with_ai
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import (
    InMemoryExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.pilot_store import SQLitePilotStore
from src.core.privacy import (
    PrivacyBoundaryError,
    PrivacySafeText,
    fingerprint_text,
    prepare_privacy_safe_text,
)
from src.workflow.mail_ingestion import process_customer_inquiry_mail


def evaluate_privacy_boundary_regressions() -> dict:
    failures: list[str] = []

    raw_body = (
        "Merhaba,\n\n"
        "Adana'dan Hamburg'a 20000 kg tekstil için FTL fiyat rica ederiz.\n"
        "Yük ADR değil. Hazır tarih 2026-08-20.\n"
        "Detay için ali.veli@example.com veya 0532 123 45 67.\n"
        "Almanya ofis telefonu: +49 40 1234 5678.\n"
        "Banka bilgisi: DE89 3704 0044 0532 0130 00.\n\n"
        "Saygılarımla\n"
        "Ali Veli\n"
        "Satış Müdürü\n"
        "ali.veli@example.com\n"
        "0532 123 45 67\n"
    )

    captured: dict[str, object] = {}

    def parser(text: PrivacySafeText) -> ShipmentProposalSnapshot:
        captured["text"] = text
        return ShipmentProposalSnapshot(
            customer_name="Synthetic Customer",
            pickup_city="Adana",
            delivery_city="Hamburg",
            gross_weight_kg=20000,
            is_adr=False,
            is_temperature_controlled=False,
            is_high_value=False,
        )

    repository = InMemoryExtractionProposalRepository()
    result = process_customer_inquiry_mail(
        mail=InboundMailEnvelope(
            body_text=raw_body,
            sender_address="trusted.sender@example.com",
            sender_name="Ali Veli",
            subject="FTL teklif - ali.veli@example.com - 0532 123 45 67",
            external_message_id="privacy-test-1",
            source="manual",
        ),
        shipment_parser=parser,
        proposal_repository=repository,
    )

    safe_text = captured.get("text")
    if not isinstance(safe_text, PrivacySafeText):
        failures.append("parser did not receive PrivacySafeText")
    else:
        safe_value = str(safe_text)
        if "ali.veli@example.com" in safe_value:
            failures.append("personal email survived privacy transform")
        if "0532 123 45 67" in safe_value:
            failures.append("phone number survived privacy transform")
        if "+49 40 1234 5678" in safe_value:
            failures.append(
                "international phone survived privacy transform"
            )
        if "DE89 3704 0044 0532 0130 00" in safe_value:
            failures.append(
                "international IBAN survived privacy transform"
            )
        if "Satış Müdürü" in safe_value:
            failures.append("signature block survived privacy transform")
        for operational_value in (
            "Adana",
            "Hamburg",
            "20000 kg",
            "ADR değil",
            "2026-08-20",
        ):
            if operational_value not in safe_value:
                failures.append(
                    "operational value lost during privacy transform: "
                    + operational_value
                )

    proposal = result["extraction_proposal"]
    persisted_mail = proposal.inbound_mail

    if persisted_mail.body_text == raw_body:
        failures.append("raw inbound body was persisted")
    if not persisted_mail.privacy_transformed:
        failures.append("persisted inbound mail lacks privacy marker")
    if persisted_mail.raw_body_sha256 != fingerprint_text(raw_body):
        failures.append("raw body fingerprint is missing or incorrect")
    if persisted_mail.sender_name is not None:
        failures.append("sender display name was unnecessarily persisted")
    if persisted_mail.sender_address != "trusted.sender@example.com":
        failures.append(
            "trusted sender address needed for identity was not retained"
        )
    if persisted_mail.subject and "0532 123 45 67" in persisted_mail.subject:
        failures.append("phone number survived subject minimization")

    quoted_thread = prepare_privacy_safe_text(
        "Yeni talep: Adana-Hamburg FTL.\n"
        "-----Original Message-----\n"
        "From: old.contact@example.com\n"
        "Sent: Friday\n"
        "To: ops@example.com\n"
        "Subject: Old request\n"
        "Eski ve gereksiz müşteri yazışması."
    )

    if (
        "Eski ve gereksiz müşteri yazışması"
        in str(quoted_thread.safe_text)
        or "old.contact@example.com"
        in str(quoted_thread.safe_text)
    ):
        failures.append(
            "quoted historical mail survived privacy minimization"
        )

    if (
        "Adana-Hamburg FTL"
        not in str(quoted_thread.safe_text)
    ):
        failures.append(
            "current operational text was lost while stripping quoted mail"
        )

    try:
        PrivacySafeText(
            raw_body,
            raw_body_sha256=fingerprint_text(raw_body),
            transform_version="p0.1-v1",
        )
    except PrivacyBoundaryError:
        pass
    else:
        failures.append(
            "PrivacySafeText could be forged without privacy transform"
        )

    try:
        parse_email_with_ai(raw_body)  # type: ignore[arg-type]
    except PrivacyBoundaryError:
        pass
    except Exception as exc:
        failures.append(
            "raw AI parser call failed for the wrong reason: "
            + type(exc).__name__
        )
    else:
        failures.append("raw string was accepted by AI parser")

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "privacy.sqlite3"
        store = SQLitePilotStore(
            db_path,
            run_id="privacy-run",
            retention_days=30,
        )
        store.upsert(
            namespace="privacy_test",
            record_key="old-record",
            payload={"safe": True},
            event_type="privacy_test_saved",
            entity_type="privacy_test",
        )

        old_time = (
            datetime.now(timezone.utc) - timedelta(days=31)
        ).isoformat()
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE state_records SET updated_at = ? "
                "WHERE namespace = ? AND record_key = ?",
                (old_time, "privacy_test", "old-record"),
            )
            connection.execute(
                "UPDATE pilot_events SET created_at = ? "
                "WHERE entity_type = ? AND entity_id = ?",
                (old_time, "privacy_test", "old-record"),
            )

        purge_result = store.purge_expired()
        if purge_result["state_records_deleted"] != 1:
            failures.append("expired durable state was not purged")
        if purge_result["pilot_events_deleted"] != 1:
            failures.append("expired pilot evidence was not purged")
        if store.get(
            namespace="privacy_test",
            record_key="old-record",
        ) is not None:
            failures.append("expired state remained readable after purge")

    return {
        "name": "Pilot privacy boundary",
        "passed": len(failures) == 0,
        "failures": failures,
    }
