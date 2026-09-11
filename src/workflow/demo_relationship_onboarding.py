from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable

from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.supplier_history_backfill import propose_supplier_operational_backfill
from src.core.privacy import PrivacySafeText
from src.core.relationship_history import (
    HistoricalMailMessage,
    RelationshipAIObservation,
    RelationshipAIObservationSet,
    RelationshipHistoryAIAnalyzer,
    analyze_relationship_history,
)

DEMO_AGENCY_ADDRESS = "demo@minai.invalid"
_DEMO_CUSTOMER_LIMIT = 5


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Demo relationship history timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _primary_customer_email(profile) -> str | None:
    for contact in profile.contacts:
        if contact.active and contact.email and contact.is_primary:
            return contact.email
    for contact in profile.contacts:
        if contact.active and contact.email:
            return contact.email
    return profile.trusted_sender_addresses[0] if profile.trusted_sender_addresses else None


def _primary_supplier_email(profile) -> str | None:
    for contact in profile.contacts:
        if contact.active and contact.email and contact.is_primary:
            return contact.email
    for contact in profile.contacts:
        if contact.active and contact.email:
            return contact.email
    return None


def _message(
    *, ref: str, sent_at: datetime, sender: str, recipient: str,
    subject: str, body: str,
) -> HistoricalMailMessage:
    return HistoricalMailMessage(
        source_reference=ref,
        sent_at=sent_at,
        sender_address=sender,
        recipient_addresses=[recipient],
        subject=subject,
        body_text=body,
        source="synthetic",
    )


def _customer_thread(subject_id: str, email: str, *, base: datetime, thread: int) -> list[HistoricalMailMessage]:
    subject = f"Demo taşıma talebi {thread}"
    return [
        _message(
            ref=f"demo-history:customer:{subject_id}:{thread}:1",
            sent_at=base,
            sender=email,
            recipient=DEMO_AGENCY_ADDRESS,
            subject=subject,
            body="Merhaba, bu hafta Almanya hattı için hızlı ve net bir all-in fiyat rica ederiz.",
        ),
        _message(
            ref=f"demo-history:customer:{subject_id}:{thread}:2",
            sent_at=base + timedelta(minutes=12),
            sender=DEMO_AGENCY_ADDRESS,
            recipient=email,
            subject=f"Re: {subject}",
            body="Talebinizi aldık, tedarikçi fiyatlarını kontrol ediyoruz.",
        ),
        _message(
            ref=f"demo-history:customer:{subject_id}:{thread}:3",
            sent_at=base + timedelta(minutes=34),
            sender=email,
            recipient=DEMO_AGENCY_ADDRESS,
            subject=f"Re: {subject}",
            body="Teşekkürler. Mümkünse tek satırda toplam fiyat ve transit süreyi de paylaşın.",
        ),
        _message(
            ref=f"demo-history:customer:{subject_id}:{thread}:4",
            sent_at=base + timedelta(minutes=52),
            sender=DEMO_AGENCY_ADDRESS,
            recipient=email,
            subject=f"Re: {subject}",
            body="All-in fiyat ve transit süre ile teklifimizi iletiyoruz.",
        ),
    ]


def _supplier_thread(subject_id: str, email: str, *, base: datetime, thread: int) -> list[HistoricalMailMessage]:
    subject = f"Demo RFQ DE {thread}"
    return [
        _message(
            ref=f"demo-history:supplier:{subject_id}:{thread}:1",
            sent_at=base,
            sender=DEMO_AGENCY_ADDRESS,
            recipient=email,
            subject=subject,
            body="Adana - Almanya FTL tenteli için araç ve fiyat çalışabilir misiniz?",
        ),
        _message(
            ref=f"demo-history:supplier:{subject_id}:{thread}:2",
            sent_at=base + timedelta(minutes=24),
            sender=email,
            recipient=DEMO_AGENCY_ADDRESS,
            subject=f"Re: {subject}",
            body="Aldık, çalışıyoruz. Kısa süre içinde fiyatla döneceğiz.",
        ),
        _message(
            ref=f"demo-history:supplier:{subject_id}:{thread}:3",
            sent_at=base + timedelta(minutes=128),
            sender=DEMO_AGENCY_ADDRESS,
            recipient=email,
            subject=f"Re: {subject}",
            body="Müşteri dönüş bekliyor; çalışmanızın durumunu paylaşabilir misiniz?",
        ),
        _message(
            ref=f"demo-history:supplier:{subject_id}:{thread}:4",
            sent_at=base + timedelta(minutes=176),
            sender=email,
            recipient=DEMO_AGENCY_ADDRESS,
            subject=f"Re: {subject}",
            body="Araç uygundur. All-in 2.450 EUR, transit 5 gün.",
        ),
    ]


def build_demo_relationship_history(
    *, start_at: datetime, end_at: datetime, max_messages: int,
    master_repository: MasterDataRepository,
) -> list[HistoricalMailMessage]:
    start = _aware_utc(start_at)
    end = _aware_utc(end_at)
    if end <= start:
        raise ValueError("Demo relationship history end_at must be after start_at.")
    if max_messages < 1:
        raise ValueError("Demo relationship history max_messages must be positive.")

    # Round to the requested end date so repeated analyses during the same day produce
    # identical synthetic evidence fingerprints and remain idempotent.
    anchor = end.replace(hour=12, minute=0, second=0, microsecond=0)
    messages: list[HistoricalMailMessage] = []

    customers = [
        profile for profile in master_repository.list_customers()
        if profile.entry_id.startswith("demo-customer-")
    ]
    for index, profile in enumerate(sorted(customers, key=lambda item: item.customer_name.casefold())[:_DEMO_CUSTOMER_LIMIT]):
        email = _primary_customer_email(profile)
        if not email:
            continue
        first = anchor - timedelta(days=12 + index * 3)
        second = first + timedelta(days=5)
        messages.extend(_customer_thread(profile.customer_id, email, base=first, thread=1))
        messages.extend(_customer_thread(profile.customer_id, email, base=second, thread=2))

    suppliers = [
        profile for profile in master_repository.list_suppliers()
        if profile.entry_id.startswith("demo-supplier-")
    ]
    for index, profile in enumerate(sorted(suppliers, key=lambda item: item.supplier_name.casefold())):
        email = _primary_supplier_email(profile)
        if not email:
            continue
        first = anchor - timedelta(days=14 + index * 3)
        second = first + timedelta(days=6)
        messages.extend(_supplier_thread(profile.supplier_id, email, base=first, thread=1))
        messages.extend(_supplier_thread(profile.supplier_id, email, base=second, thread=2))

    bounded = [item for item in messages if start <= item.sent_at <= end]
    # Mimic a newest-first mailbox cap, then restore chronological order for readable
    # deterministic analysis input.
    bounded = sorted(bounded, key=lambda item: (item.sent_at, item.source_reference), reverse=True)[:max_messages]
    return sorted(bounded, key=lambda item: (item.sent_at, item.source_reference))


def _counterparty_indexes(history_text: PrivacySafeText) -> list[int]:
    indexes: list[int] = []
    current_index: int | None = None
    for raw_line in str(history_text).splitlines():
        line = raw_line.strip()
        match = re.fullmatch(r"--- MESSAGE_(\d{3}) ---", line)
        if match:
            current_index = int(match.group(1))
            continue
        if line == "AUTHOR: COUNTERPARTY" and current_index is not None:
            indexes.append(current_index)
    return indexes


class DemoRelationshipHistoryAnalyzer(RelationshipHistoryAIAnalyzer):
    """Deterministic local AI stand-in for the synthetic demo mailbox."""

    def analyze(
        self, *, subject_type: str, history_text: PrivacySafeText,
    ) -> RelationshipAIObservationSet:
        indexes = _counterparty_indexes(history_text)
        if not indexes:
            return RelationshipAIObservationSet()
        support = indexes[: min(2, len(indexes))]
        if subject_type == "supplier":
            return RelationshipAIObservationSet(observations=[RelationshipAIObservation(
                category="negotiation_behavior",
                observation=(
                    "Sentetik demo örneğinde tedarikçi RFQ'yu önce teyit edip ardından "
                    "ticari fiyatla dönme eğilimi gösteriyor."
                ),
                confidence=0.82,
                scope="sample_only",
                supporting_counterparty_message_indexes=support,
            )])
        return RelationshipAIObservationSet(observations=[RelationshipAIObservation(
            category="communication_style",
            observation=(
                "Sentetik demo örneğinde müşteri kısa, all-in fiyat ve transit süre içeren "
                "net teklif iletişimini tercih ediyor."
            ),
            confidence=0.80,
            scope="sample_only",
            supporting_counterparty_message_indexes=support,
        )])


def run_demo_relationship_onboarding(
    *, start_at: datetime, end_at: datetime, max_messages: int,
    authorization_confirmed: bool, master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository, created_by: str,
    include_ai_observations: bool = False,
    agency_addresses: Iterable[str] | None = None,
) -> dict:
    if authorization_confirmed is not True:
        raise PermissionError("Synthetic mailbox history analysis requires explicit operator authorization.")
    messages = build_demo_relationship_history(
        start_at=start_at,
        end_at=end_at,
        max_messages=max_messages,
        master_repository=master_repository,
    )
    analyzer = DemoRelationshipHistoryAnalyzer() if include_ai_observations else None
    try:
        result = analyze_relationship_history(
            messages=messages,
            agency_addresses=list(dict.fromkeys([DEMO_AGENCY_ADDRESS, *(agency_addresses or [])])),
            master_repository=master_repository,
            learning_repository=learning_repository,
            created_by=created_by,
            ai_analyzer=analyzer,
        )
        supplier_backfill = propose_supplier_operational_backfill(
            analysis=result, learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by,
        )
        payload = result.model_dump()
        payload.update({
            "supplier_operational_backfill": supplier_backfill,
            "source": "synthetic_demo_history",
            "history_start_at": _aware_utc(start_at),
            "history_end_at": _aware_utc(end_at),
            "max_messages": max_messages,
            "ai_analysis_requested": include_ai_observations,
            "raw_messages_persisted": False,
            "synthetic_mailbox": True,
        })
        return payload
    finally:
        messages.clear()
