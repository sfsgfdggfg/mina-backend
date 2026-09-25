from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.counterparty_discovery import (
    CounterpartyDiscoveryResult,
    discover_historical_counterparties,
)
from src.core.master_data_repository import MasterDataRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.relationship_history import HistoricalMailMessage


AgencyCandidateRole = Literal["customer", "supplier", "unknown", "other"]
BootstrapStatus = Literal["not_started", "running", "completed", "failed"]

_GENERIC_DOMAINS = {
    "gmail.com", "hotmail.com", "outlook.com", "icloud.com", "yahoo.com",
    "live.com", "msn.com", "proton.me", "protonmail.com",
}
_REPLY_MARKERS = (
    "________________________________",
    "-----original message-----",
    "gönderen:",
    "kimden:",
    "from:",
)
_SIGNATURE_MARKERS = (
    "iyi çalışmalar dilerim",
    "saygılarımla/ best regards",
    "saygılarımla / best regards",
    "best regards",
)

_SUPPLIER_OUTBOUND_PATTERNS = (
    "navlun teklifinizi rica",
    "all-in navlun teklifinizi rica",
    "all in navlun teklifinizi rica",
    "fiyatınızı rica",
    "fiyat verebilir misiniz",
    "teklifinizi rica ederiz",
    "gemi programı ile birlikte",
    "rezervasyon için destek",
    "navlun onaylıdır",
    "teklifinizi kabul ediyoruz",
    "biraz indirim yapabilir misiniz",
)
_CUSTOMER_OUTBOUND_PATTERNS = (
    "navlun teklifimiz",
    "teklifimiz aşağıdaki gibidir",
    "talebinize istinaden navlun teklifimiz",
    "teklifimizi değerlendirebildiniz mi",
    "bookinginiz",
    "rezervasyon geçilmiş olup",
    "gemi ve kullanım detayları",
    "gelişmeleri tarafınıza",
    "araç bilgileri geldiğinde ileteceğim",
    "arac bilgileri geldiginde iletecegim",
)
_CUSTOMER_INBOUND_PATTERNS = (
    "fiyat rica",
    "navlun teklif",
    "teklif rica",
    "taşıma talebi",
    "tasima talebi",
    "araç talebi",
    "arac talebi",
)
_SUPPLIER_INBOUND_PATTERNS = (
    "booking confirmation",
    "rezervasyon onayı",
    "rezervasyon onayi",
    "çıkış ihbarı",
    "cikis ihbari",
    "varış ihbarı",
    "varis ihbari",
    "planlanan yükleme bilgileri",
    "planlanan yukleme bilgileri",
    "ordino ihbarı",
    "ordino ihbari",
)


def _fold(value: str) -> str:
    return " ".join(str(value or "").casefold().replace("ı", "i").split())


def _current_authored_text(message: HistoricalMailMessage) -> str:
    raw = f"{message.subject or ''}\n{message.body_text or ''}"
    folded = raw.casefold()
    cuts = [folded.find(marker) for marker in _REPLY_MARKERS if folded.find(marker) > 0]
    if cuts:
        raw = raw[: min(cuts)]
        folded = raw.casefold()
    cuts = [folded.find(marker) for marker in _SIGNATURE_MARKERS if folded.find(marker) > 0]
    if cuts:
        raw = raw[: min(cuts)]
    return _fold(raw)


def infer_agency_addresses(
    messages: list[HistoricalMailMessage],
    mailbox_id: str,
) -> list[str]:
    mailbox = mailbox_id.strip().casefold()
    domain = mailbox.rsplit("@", 1)[-1]
    addresses = {mailbox}
    for message in messages:
        candidates = [message.sender_address, *message.recipient_addresses]
        for address in candidates:
            normalized = address.strip().casefold()
            if normalized.rsplit("@", 1)[-1] == domain:
                addresses.add(normalized)
    return sorted(addresses)


class AgencyCounterpartyLearningCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_address: str
    domain: str
    message_count: int = Field(ge=1)
    inbound_count: int = Field(ge=0)
    outbound_count: int = Field(ge=0)
    thread_count: int = Field(ge=1)
    master_match_status: str
    inferred_role: AgencyCandidateRole
    confidence: float = Field(ge=0, le=1)
    customer_signal_count: int = Field(ge=0)
    supplier_signal_count: int = Field(ge=0)
    subject_type: str | None = None
    subject_id: str | None = None
    subject_label: str | None = None
    first_observed_at: datetime
    last_observed_at: datetime


class AgencyWorkflowPatternSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_rfq_message_count: int = Field(default=0, ge=0)
    customer_quote_message_count: int = Field(default=0, ge=0)
    customer_quote_followup_count: int = Field(default=0, ge=0)
    supplier_negotiation_message_count: int = Field(default=0, ge=0)
    operational_update_message_count: int = Field(default=0, ge=0)
    finance_message_count: int = Field(default=0, ge=0)
    rfq_field_frequencies: dict[str, int] = Field(default_factory=dict)
    quote_term_frequencies: dict[str, int] = Field(default_factory=dict)


class AgencyLearningBootstrapSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: BootstrapStatus = "not_started"
    provider: str | None = None
    mailbox_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    history_start_at: datetime | None = None
    history_end_at: datetime | None = None
    scanned_message_count: int = Field(default=0, ge=0)
    inbound_message_count: int = Field(default=0, ge=0)
    outbound_message_count: int = Field(default=0, ge=0)
    rejected_message_count: int = Field(default=0, ge=0)
    inferred_agency_addresses: list[str] = Field(default_factory=list, max_length=200)
    workflow_patterns: AgencyWorkflowPatternSummary = Field(
        default_factory=AgencyWorkflowPatternSummary
    )
    candidate_count: int = Field(default=0, ge=0)
    known_candidate_count: int = Field(default=0, ge=0)
    high_confidence_candidate_count: int = Field(default=0, ge=0)
    proposed_fact_count: int = Field(default=0, ge=0)
    matched_subject_count: int = Field(default=0, ge=0)
    candidates: list[AgencyCounterpartyLearningCandidate] = Field(
        default_factory=list, max_length=300
    )
    raw_messages_persisted: bool = False
    error_code: str | None = Field(default=None, max_length=300)

    @field_validator(
        "started_at", "completed_at", "history_start_at", "history_end_at"
    )
    @classmethod
    def require_aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Agency learning timestamps must be timezone-aware.")
        return value


class SQLiteAgencyLearningBootstrapRepository:
    NAMESPACE = "agency_learning_bootstrap"
    RECORD_KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> AgencyLearningBootstrapSnapshot:
        raw = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        if raw is None:
            return AgencyLearningBootstrapSnapshot()
        return AgencyLearningBootstrapSnapshot.model_validate(raw)

    def save(
        self, snapshot: AgencyLearningBootstrapSnapshot
    ) -> AgencyLearningBootstrapSnapshot:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=self.RECORD_KEY,
            payload=snapshot.model_dump(mode="json"),
            event_type="agency_learning_bootstrap_state_changed",
            entity_type="agency_learning_bootstrap",
        )
        return snapshot


def _signal_counts(
    messages: list[HistoricalMailMessage],
    agency_addresses: set[str],
) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for message in messages:
        sender = message.sender_address.strip().casefold()
        recipients = {item.strip().casefold() for item in message.recipient_addresses}
        text = _current_authored_text(message)
        if sender in agency_addresses:
            external = recipients - agency_addresses
            supplier_hit = any(_fold(pattern) in text for pattern in _SUPPLIER_OUTBOUND_PATTERNS)
            customer_hit = any(_fold(pattern) in text for pattern in _CUSTOMER_OUTBOUND_PATTERNS)
            for address in external:
                if customer_hit:
                    counts[address][0] += 2
                if supplier_hit:
                    counts[address][1] += 2
        elif recipients.intersection(agency_addresses):
            customer_hit = any(_fold(pattern) in text for pattern in _CUSTOMER_INBOUND_PATTERNS)
            supplier_hit = any(_fold(pattern) in text for pattern in _SUPPLIER_INBOUND_PATTERNS)
            if customer_hit:
                counts[sender][0] += 1
            if supplier_hit:
                counts[sender][1] += 1
    return {key: (value[0], value[1]) for key, value in counts.items()}


def classify_counterparties(
    *,
    messages: list[HistoricalMailMessage],
    agency_addresses: list[str],
    discovery: CounterpartyDiscoveryResult,
) -> list[AgencyCounterpartyLearningCandidate]:
    agency = {item.strip().casefold() for item in agency_addresses}
    signals = _signal_counts(messages, agency)
    results: list[AgencyCounterpartyLearningCandidate] = []
    for candidate in discovery.candidates:
        customer_score, supplier_score = signals.get(candidate.email_address, (0, 0))
        if candidate.subject_type in {"customer", "supplier"}:
            role: AgencyCandidateRole = candidate.subject_type
            confidence = 0.99
        else:
            margin = abs(customer_score - supplier_score)
            strongest = max(customer_score, supplier_score)
            if candidate.domain in _GENERIC_DOMAINS and strongest < 4:
                role = "unknown"
                confidence = 0.45
            elif strongest >= 4 and margin >= 3 and candidate.thread_count >= 2:
                role = "customer" if customer_score > supplier_score else "supplier"
                confidence = 0.92
            elif strongest >= 2 and margin >= 2:
                role = "customer" if customer_score > supplier_score else "supplier"
                confidence = 0.78
            else:
                role = "unknown"
                confidence = 0.50 if strongest else 0.35
        results.append(
            AgencyCounterpartyLearningCandidate(
                email_address=candidate.email_address,
                domain=candidate.domain,
                message_count=candidate.message_count,
                inbound_count=candidate.inbound_count,
                outbound_count=candidate.outbound_count,
                thread_count=candidate.thread_count,
                master_match_status=candidate.master_match_status,
                inferred_role=role,
                confidence=confidence,
                customer_signal_count=customer_score,
                supplier_signal_count=supplier_score,
                subject_type=candidate.subject_type,
                subject_id=candidate.subject_id,
                subject_label=candidate.subject_label,
                first_observed_at=candidate.first_observed_at,
                last_observed_at=candidate.last_observed_at,
            )
        )
    return sorted(
        results,
        key=lambda item: (-item.confidence, -item.message_count, item.email_address),
    )[:300]



_RFP_FIELD_PATTERNS = {
    "quote_reference": ("teklif no", "referans no", "ref no"),
    "loading_address": ("yükleme adres", "yukleme adres", "loading address"),
    "delivery_address": ("teslim adres", "delivery address"),
    "commodity": ("malzeme", "commodity", "mal cinsi"),
    "equipment": ("ekipman", "equipment"),
    "weight_dimensions": ("tonaj", "ölçü", "olcu", "ebat", "weight", "dimensions"),
    "vessel_schedule": ("gemi program", "vessel", "etd", "eta"),
    "free_time": ("free time", "freetime"),
    "scope_split": ("iç nakliye", "ic nakliye", "door to port", "port to port", "all-in", "all in"),
}
_QUOTE_TERM_PATTERNS = {
    "included_costs": ("dahildir", "dahil", "all-in", "all in"),
    "excluded_costs": ("hariç", "haric", "aittir"),
    "transit_time": ("transit", "tt:", "tt "),
    "free_time": ("free time", "freetime"),
    "validity": ("geçerl", "gecerl", "validity", "valid until"),
    "availability_condition": ("subject to space", "equipment availability", "yer ve ekipman"),
}
_FOLLOWUP_PATTERNS = (
    "teklifimizi değerlendirebildiniz mi",
    "teklifimizi degerlendirebildiniz mi",
    "olumlu veya olumsuz geri dönüş",
    "olumlu veya olumsuz geri donus",
)
_NEGOTIATION_PATTERNS = (
    "biraz indirim",
    "indirim yapabilir",
    "teklifinizi kabul ediyoruz",
    "navlun onaylıdır",
    "navlun onaylidir",
    "fiyatta bir değişiklik",
    "fiyatta bi değişiklik",
)
_OPERATION_PATTERNS = (
    "booking", "rezervasyon", "gemi", "etd", "eta", "cut off", "cut-off",
    "vgm", "cmr", "plaka", "sürücü", "surucu", "yükleme", "yukleme",
    "teslim", "gümrük", "gumruk", "ordino", "konşimento", "konsimento",
)
_FINANCE_PATTERNS = (
    "fatura", "ödeme", "odeme", "vade", "dekont", "cari", "mutabakat",
)


def summarize_agency_workflow_patterns(
    *,
    messages: list[HistoricalMailMessage],
    agency_addresses: list[str],
) -> AgencyWorkflowPatternSummary:
    agency = {item.strip().casefold() for item in agency_addresses}
    rfq_count = 0
    quote_count = 0
    followup_count = 0
    negotiation_count = 0
    operation_count = 0
    finance_count = 0
    rfq_fields: dict[str, int] = defaultdict(int)
    quote_terms: dict[str, int] = defaultdict(int)
    for message in messages:
        if message.sender_address.strip().casefold() not in agency:
            continue
        text = _current_authored_text(message)
        is_rfq = any(_fold(pattern) in text for pattern in _SUPPLIER_OUTBOUND_PATTERNS)
        is_quote = any(_fold(pattern) in text for pattern in _CUSTOMER_OUTBOUND_PATTERNS)
        if is_rfq:
            rfq_count += 1
            for key, patterns in _RFP_FIELD_PATTERNS.items():
                if any(_fold(pattern) in text for pattern in patterns):
                    rfq_fields[key] += 1
        if is_quote:
            quote_count += 1
            for key, patterns in _QUOTE_TERM_PATTERNS.items():
                if any(_fold(pattern) in text for pattern in patterns):
                    quote_terms[key] += 1
        if any(_fold(pattern) in text for pattern in _FOLLOWUP_PATTERNS):
            followup_count += 1
        if any(_fold(pattern) in text for pattern in _NEGOTIATION_PATTERNS):
            negotiation_count += 1
        if any(_fold(pattern) in text for pattern in _OPERATION_PATTERNS):
            operation_count += 1
        if any(_fold(pattern) in text for pattern in _FINANCE_PATTERNS):
            finance_count += 1
    return AgencyWorkflowPatternSummary(
        supplier_rfq_message_count=rfq_count,
        customer_quote_message_count=quote_count,
        customer_quote_followup_count=followup_count,
        supplier_negotiation_message_count=negotiation_count,
        operational_update_message_count=operation_count,
        finance_message_count=finance_count,
        rfq_field_frequencies=dict(sorted(rfq_fields.items())),
        quote_term_frequencies=dict(sorted(quote_terms.items())),
    )


def count_mail_directions(
    *,
    messages: list[HistoricalMailMessage],
    agency_addresses: list[str],
) -> tuple[int, int]:
    agency = {item.strip().casefold() for item in agency_addresses}
    inbound = 0
    outbound = 0
    for message in messages:
        sender = message.sender_address.strip().casefold()
        recipients = {item.strip().casefold() for item in message.recipient_addresses}
        if sender in agency:
            outbound += 1
        elif recipients.intersection(agency):
            inbound += 1
    return inbound, outbound


def build_candidate_snapshot(
    *,
    messages: list[HistoricalMailMessage],
    mailbox_id: str,
    master_repository: MasterDataRepository,
) -> tuple[list[str], list[AgencyCounterpartyLearningCandidate], CounterpartyDiscoveryResult]:
    agency_addresses = infer_agency_addresses(messages, mailbox_id)
    discovery = discover_historical_counterparties(
        messages=messages,
        agency_addresses=agency_addresses,
        master_repository=master_repository,
    )
    candidates = classify_counterparties(
        messages=messages,
        agency_addresses=agency_addresses,
        discovery=discovery,
    )
    return agency_addresses, candidates, discovery
