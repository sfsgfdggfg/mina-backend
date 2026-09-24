from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from src.core.pilot_store import SQLitePilotStore

from src.core.mail import InboundMailEnvelope
from src.core.master_data import SupplierMasterProfile
from src.core.master_data_repository import MasterDataRepository


TransportModeHint = Literal["road", "sea", "air", "rail", "multimodal", "unknown"]


class SupplierOperationalAssessment(BaseModel):
    operational: bool = False
    transport_mode: TransportModeHint = "unknown"
    event_types: list[str] = Field(default_factory=list)
    reference_tokens: list[str] = Field(default_factory=list)
    evidence_terms: list[str] = Field(default_factory=list)


def _fold_text(value: str) -> str:
    folded = value.casefold().replace("ı", "i")
    folded = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _normalized_text(mail: InboundMailEnvelope) -> str:
    return " ".join(_fold_text(f"{mail.subject or ''} {mail.body_text or ''}").split())

def supplier_sender_matches(
    profile: SupplierMasterProfile,
    sender_address: str | None,
) -> bool:
    sender = (sender_address or "").strip().casefold()
    if "@" not in sender or not profile.active:
        return False
    domain = sender.rsplit("@", 1)[1]
    trusted_addresses = set(profile.trusted_sender_addresses)
    trusted_addresses.update(
        contact.email.strip().casefold()
        for contact in profile.contacts
        if contact.active and contact.email
    )
    if sender in trusted_addresses:
        return True
    return domain in set(profile.trusted_sender_domains)


def matching_supplier_masters(
    repository: MasterDataRepository | None,
    sender_address: str | None,
) -> list[SupplierMasterProfile]:
    if repository is None:
        return []
    return [
        profile
        for profile in repository.list_suppliers()
        if supplier_sender_matches(profile, sender_address)
    ]

_EVENT_TERMS = {
    "booking_confirmation": (
        "rezervasyon onayı", "booking confirmation", "booking confirmed",
    ),
    "departure_notice": (
        "çıkış ihbar", "cikis ihbar", "departure notice", "departed", "atd ",
    ),
    "arrival_notice": (
        "varış ihbar", "varis ihbar", "arrival notice", "arrived", "ata ",
    ),
    "loading_update": (
        "yükleme bilg", "yukleme bilg", "yükleme tamam", "yukleme tamam",
        "araç yüklendi", "arac yuklendi", "loaded at", "loading completed",
    ),
    "vehicle_assignment": (
        "plaka", "sürücü", "surucu", "araç bilg", "arac bilg",
        "vehicle plate", "driver name", "truck assigned",
    ),
    "tracking_update": (
        "gps", "güncel konum", "guncel konum", "current location",
        "sınır kap", "sinir kap", "border crossing", "transit update",
    ),

    "delivery_update": (
        "teslim edildi", "teslimat tamam", "delivery completed",
        "proof of delivery", " pod ", "cmr teslim",
    ),
    "delay_or_exception": (
        "gecik", "arıza", "ariza", "bekleme", "delay", "breakdown",
        "customs hold", "gümrükte bek", "gumrukte bek",
    ),
    "document_notice": (
        "konşimento", "konsimento", "bill of lading", "waybill",
        "awb", "cmr", "ordino",
    ),
}

_MODE_TERMS = {
    "sea": (
        "fcl", "lcl", "konteyner", "container", "gemi", "vessel",
        "konşimento", "bill of lading", " pol/", " pod)", "etd", "eta",
    ),
    "road": (
        "plaka", "sürücü", "surucu", "çekici", "cekici", "dorse",
        "tenteli", "tır", "tir ", "truck", "cmr", "sınır kap", "border",
    ),
    "air": ("awb", "mawb", "hawb", "flight", "uçuş", "ucus", "air cargo"),
    "rail": ("vagon", "wagon", "rail", "tren", "demiryolu"),
}

_REF_RE = re.compile(
    r"\b(?:MINA\d{4}/[1-9]\d*|[A-Z]{2,8}[0-9]{5,})\b",
    flags=re.IGNORECASE,
)


def assess_supplier_operational_mail(
    mail: InboundMailEnvelope,
) -> SupplierOperationalAssessment:
    text = _normalized_text(mail)
    event_types: list[str] = []
    evidence_terms: list[str] = []
    for event_type, terms in _EVENT_TERMS.items():
        matched = next((term for term in terms if _fold_text(term) in text), None)
        if matched:
            event_types.append(event_type)
            evidence_terms.append(matched)

    mode_scores = {
        mode: sum(1 for term in terms if _fold_text(term) in text)
        for mode, terms in _MODE_TERMS.items()
    }
    best_score = max(mode_scores.values(), default=0)
    best_modes = [mode for mode, score in mode_scores.items() if score == best_score and score > 0]
    transport_mode: TransportModeHint = best_modes[0] if len(best_modes) == 1 else (
        "multimodal" if len(best_modes) > 1 else "unknown"
    )
    references = list(dict.fromkeys(match.upper() for match in _REF_RE.findall(text)))
    return SupplierOperationalAssessment(
        operational=bool(event_types),
        transport_mode=transport_mode,
        event_types=event_types,
        reference_tokens=references[:20],
        evidence_terms=evidence_terms[:20],
    )


class SupplierOperationalNotification(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=1000)
    external_message_id: str = Field(min_length=1, max_length=800)
    provider_name: str = Field(min_length=1, max_length=80)
    mailbox_id: str = Field(min_length=1, max_length=320)
    supplier_id: str = Field(min_length=1, max_length=100)
    supplier_name: str = Field(min_length=1, max_length=240)
    sender_address: str = Field(min_length=3, max_length=320)
    received_at: datetime
    subject: str = Field(default="", max_length=1000)
    transport_mode: TransportModeHint = "unknown"
    event_types: list[str] = Field(default_factory=list)
    reference_tokens: list[str] = Field(default_factory=list)
    status: Literal["review_required", "linked", "dismissed"] = "review_required"
    job_id: str | None = Field(default=None, max_length=100)
    mina_code: str | None = Field(default=None, max_length=40)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("received_at", "created_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Supplier operational notification timestamps must be timezone-aware.")
        return value


class InMemorySupplierOperationalNotificationRepository:
    def __init__(self) -> None:
        self._items: dict[str, SupplierOperationalNotification] = {}
        self._lock = Lock()

    def upsert_detected(
        self, item: SupplierOperationalNotification
    ) -> tuple[SupplierOperationalNotification, bool]:
        with self._lock:
            existing = self._items.get(item.entry_id)
            if existing is not None:
                return existing, False
            self._items[item.entry_id] = item
            return item, True

    def list_all(self) -> list[SupplierOperationalNotification]:
        return sorted(
            self._items.values(),
            key=lambda item: (item.received_at, item.notification_id),
            reverse=True,
        )


class SQLiteSupplierOperationalNotificationRepository:
    NAMESPACE = "supplier_operational_notifications"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def upsert_detected(
        self, item: SupplierOperationalNotification
    ) -> tuple[SupplierOperationalNotification, bool]:
        existing = self.store.get(namespace=self.NAMESPACE, record_key=item.entry_id)
        if existing is not None:
            return SupplierOperationalNotification.model_validate(existing), False
        created = self.store.insert_once(
            namespace=self.NAMESPACE,
            record_key=item.entry_id,
            payload=item.model_dump(mode="json"),
            event_type="supplier_operational_notification_detected",
            entity_type="supplier_operational_notification",
        )
        if not created:
            existing = self.store.get(namespace=self.NAMESPACE, record_key=item.entry_id)
            return SupplierOperationalNotification.model_validate(existing), False
        return item, True

    def list_all(self) -> list[SupplierOperationalNotification]:
        items = [
            SupplierOperationalNotification.model_validate(payload)
            for payload in self.store.list_all(namespace=self.NAMESPACE)
        ]
        return sorted(
            items,
            key=lambda item: (item.received_at, item.notification_id),
            reverse=True,
        )


def persist_supplier_operational_notification(
    *,
    repository,
    mail: InboundMailEnvelope,
    supplier_profile: SupplierMasterProfile,
    assessment: SupplierOperationalAssessment,
    mina_job_repository=None,
) -> SupplierOperationalNotification | None:
    if repository is None:
        return None
    matched_job = None
    mina_references = [
        token for token in assessment.reference_tokens
        if token.startswith("MINA")
    ]
    if mina_job_repository is not None and len(mina_references) == 1:
        matched_job = mina_job_repository.get_by_code(mina_references[0])
    entry_id = (
        f"{mail.provider_name}:{mail.mailbox_id}:{mail.external_message_id}"
    )
    item = SupplierOperationalNotification(
        entry_id=entry_id,
        external_message_id=mail.external_message_id,
        provider_name=mail.provider_name,
        mailbox_id=mail.mailbox_id,
        supplier_id=supplier_profile.supplier_id,
        supplier_name=supplier_profile.supplier_name,
        sender_address=mail.sender_address,
        received_at=mail.received_at,
        subject=mail.subject or "",
        transport_mode=assessment.transport_mode,
        event_types=assessment.event_types,
        reference_tokens=assessment.reference_tokens,
        status=("linked" if matched_job is not None else "review_required"),
        job_id=(matched_job.job_id if matched_job is not None else None),
        mina_code=(matched_job.mina_code if matched_job is not None else None),
    )
    saved, _ = repository.upsert_detected(item)
    return saved
