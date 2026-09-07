from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.privacy import PrivacySafeText, prepare_privacy_safe_source_bundle


RelationshipSubjectType = Literal["customer", "supplier"]
RelationshipDirection = Literal["inbound", "outbound"]
MAX_HISTORY_MESSAGE_BODY_CHARS = 50_000
MAX_AI_SAMPLE_MESSAGES = 36
MAX_RESPONSE_WINDOW = timedelta(days=7)
_REPLY_PREFIX = re.compile(r"^(?:(?:re|fw|fwd|yanıt|yanit|cevap)\s*:\s*)+", re.I)


def _address(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
        raise ValueError("Historical mail address must be a valid email address.")
    return normalized


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Historical mail timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


class HistoricalMailMessage(BaseModel):
    """Transient provider-neutral history item; raw body is never persisted by this model."""

    model_config = ConfigDict(extra="forbid")
    source_reference: str = Field(min_length=1, max_length=500)
    sent_at: datetime
    sender_address: str
    recipient_addresses: list[str] = Field(min_length=1, max_length=50)
    subject: str = Field(default="", max_length=500)
    body_text: str = Field(default="", max_length=MAX_HISTORY_MESSAGE_BODY_CHARS)
    in_reply_to_reference: str | None = Field(default=None, max_length=500)
    source: Literal["sanitized_export", "authorized_mailbox", "synthetic"] = "sanitized_export"

    @field_validator("sent_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        return _aware(value)

    @field_validator("sender_address")
    @classmethod
    def normalize_sender(cls, value: str) -> str:
        return _address(value)

    @field_validator("recipient_addresses")
    @classmethod
    def normalize_recipients(cls, value: list[str]) -> list[str]:
        normalized = [_address(item) for item in value]
        return list(dict.fromkeys(normalized))

    @field_validator("source_reference", "subject", "body_text", "in_reply_to_reference", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        return str(value).strip()


class RelationshipAIObservation(BaseModel):
    category: Literal[
        "communication_style", "timing_pattern", "negotiation_behavior", "commercial_behavior",
        "operational_behavior", "relationship_pattern", "vehicle_information_behavior",
        "urgency_pattern", "quote_preference",
    ]
    observation: str = Field(min_length=1, max_length=700)
    confidence: float = Field(ge=0, le=1)


class RelationshipAIObservationSet(BaseModel):
    observations: list[RelationshipAIObservation] = Field(default_factory=list, max_length=9)

    @model_validator(mode="after")
    def unique_categories(self):
        categories = [item.category for item in self.observations]
        if len(categories) != len(set(categories)):
            raise ValueError("AI relationship observation categories must be unique.")
        return self


class RelationshipHistoryAIAnalyzer(Protocol):
    def analyze(self, *, subject_type: RelationshipSubjectType, history_text: PrivacySafeText) -> RelationshipAIObservationSet: ...


class _MatchedMessage(BaseModel):
    source_reference: str
    sent_at: datetime
    direction: RelationshipDirection
    subject_key: str
    subject_type: RelationshipSubjectType
    subject_id: str
    subject_label: str
    body_text: str = Field(exclude=True)
    subject_text: str = Field(exclude=True)


class RelationshipHistorySubjectSummary(BaseModel):
    subject_type: RelationshipSubjectType
    subject_id: str
    subject_label: str
    message_count: int
    inbound_count: int
    outbound_count: int
    thread_count: int
    counterparty_response_sample_count: int
    agency_response_sample_count: int
    proposed_fact_ids: list[str] = Field(default_factory=list)


class RelationshipHistoryAnalysisResult(BaseModel):
    input_message_count: int
    unique_message_count: int
    duplicate_message_count: int
    matched_message_count: int
    unmatched_message_count: int
    ambiguous_message_count: int
    subjects: list[RelationshipHistorySubjectSummary]
    unmatched_addresses: list[str] = Field(default_factory=list)
    ambiguous_addresses: list[str] = Field(default_factory=list)
    proposed_fact_count: int
    ai_observation_count: int
    raw_body_persisted: bool = False
    note: str = "Historical observations remain proposed until a human confirms them."


def _subject_key(subject: str) -> str:
    value = " ".join((subject or "").casefold().split())
    previous = None
    while previous != value:
        previous = value
        value = _REPLY_PREFIX.sub("", value).strip()
    return value or "(no-subject)"


def _master_indexes(
    repository: MasterDataRepository,
) -> tuple[
    dict[str, tuple[str, str, str]], set[str],
    dict[str, tuple[str, str, str]], set[str],
]:
    owners: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    domain_owners: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    for customer in repository.list_customers():
        owner = ("customer", customer.customer_id, customer.customer_name)
        addresses = set(customer.trusted_sender_addresses)
        addresses.update(contact.email for contact in customer.contacts if contact.active and contact.email)
        for address in addresses:
            owners[_address(address)].add(owner)
        for domain in customer.trusted_sender_domains:
            normalized = str(domain).strip().casefold().lstrip("@")
            if normalized and "." in normalized and not any(ch.isspace() for ch in normalized):
                domain_owners[normalized].add(owner)
    for supplier in repository.list_suppliers():
        owner = ("supplier", supplier.supplier_id, supplier.supplier_name)
        for contact in supplier.contacts:
            if contact.active and contact.email:
                owners[_address(contact.email)].add(owner)

    def collapse(source):
        index, ambiguous = {}, set()
        for key, entries in source.items():
            if len(entries) == 1:
                index[key] = next(iter(entries))
            else:
                ambiguous.add(key)
        return index, ambiguous

    address_index, ambiguous_addresses = collapse(owners)
    domain_index, ambiguous_domains = collapse(domain_owners)
    return address_index, ambiguous_addresses, domain_index, ambiguous_domains


def _owner_for_address(
    address: str, *, address_index: dict[str, tuple[str, str, str]],
    domain_index: dict[str, tuple[str, str, str]],
) -> tuple[str, str, str] | None:
    direct = address_index.get(address)
    if direct is not None:
        return direct
    domain = address.rsplit("@", 1)[-1]
    return domain_index.get(domain)


def _match_message(
    message: HistoricalMailMessage, *, agency_addresses: set[str],
    address_index: dict[str, tuple[str, str, str]], ambiguous_addresses: set[str],
    domain_index: dict[str, tuple[str, str, str]], ambiguous_domains: set[str],
) -> tuple[_MatchedMessage | None, set[str], set[str]]:
    participant_addresses = {message.sender_address, *message.recipient_addresses} - agency_addresses
    ambiguous = {
        address for address in participant_addresses
        if address in ambiguous_addresses or address.rsplit("@", 1)[-1] in ambiguous_domains
    }
    matched_owners = {
        owner for address in participant_addresses
        if (owner := _owner_for_address(address, address_index=address_index, domain_index=domain_index)) is not None
    }
    unmatched = {
        address for address in participant_addresses
        if _owner_for_address(address, address_index=address_index, domain_index=domain_index) is None
        and address not in ambiguous
    }
    if ambiguous or len(matched_owners) != 1:
        return None, unmatched, ambiguous
    subject_type, subject_id, label = next(iter(matched_owners))
    if message.sender_address in agency_addresses:
        direction: RelationshipDirection = "outbound"
    elif _owner_for_address(
        message.sender_address, address_index=address_index, domain_index=domain_index
    ) == (subject_type, subject_id, label):
        direction = "inbound"
    else:
        return None, unmatched, ambiguous
    return _MatchedMessage(
        source_reference=message.source_reference, sent_at=message.sent_at, direction=direction,
        subject_key=_subject_key(message.subject), subject_type=subject_type, subject_id=subject_id,
        subject_label=label, body_text=message.body_text, subject_text=message.subject,
    ), unmatched, ambiguous


def _response_minutes(items: list[_MatchedMessage], source_direction: RelationshipDirection) -> list[float]:
    result: list[float] = []
    grouped: dict[str, list[_MatchedMessage]] = defaultdict(list)
    for item in items:
        grouped[item.subject_key].append(item)
    target_direction = "inbound" if source_direction == "outbound" else "outbound"
    for thread in grouped.values():
        ordered = sorted(thread, key=lambda item: (item.sent_at, item.source_reference))
        for index, item in enumerate(ordered):
            if item.direction != source_direction:
                continue
            for later in ordered[index + 1:]:
                elapsed = later.sent_at - item.sent_at
                if elapsed > MAX_RESPONSE_WINDOW:
                    break
                if later.direction == target_direction:
                    result.append(round(elapsed.total_seconds() / 60, 2))
                    break
                if later.direction == source_direction:
                    break
    return result


def _confidence(sample_count: int, *, base: float = 0.50, cap: float = 0.95) -> float:
    return round(min(cap, base + min(sample_count, 12) * 0.035), 3)


def _digest(items: list[_MatchedMessage]) -> str:
    payload = [
        {"ref": item.source_reference, "at": item.sent_at.isoformat(), "dir": item.direction, "thread": item.subject_key}
        for item in sorted(items, key=lambda x: (x.sent_at, x.source_reference))
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _active_weekdays(items: list[_MatchedMessage]) -> list[str]:
    names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    counts = Counter(item.sent_at.weekday() for item in items if item.direction == "inbound")
    return [names[index] for index, _ in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))]


def _propose_fact(
    *, learning_repository: LearningFactRepository, master_repository: MasterDataRepository,
    subject_type: RelationshipSubjectType, subject_id: str, subject_label: str,
    fact_key: str, value: Any, confidence: float, evidence: LearningEvidence,
    digest: str, created_by: str, occurred_at: datetime, source_type: str = "email",
    value_unit: str | None = None,
) -> LearningFact | None:
    entry_id = f"email-history:{subject_type}:{subject_id}:{fact_key}:{digest[:20]}"
    # The same historical evidence may be intentionally re-analyzed in phases
    # (deterministic first, AI observations later). One evidence digest + fact key
    # is one immutable proposal identity; reruns must neither duplicate nor drift it.
    if learning_repository.find_by_entry_id(entry_id) is not None:
        return None
    confirmed = [
        item for item in learning_repository.list_all()
        if item.status == "confirmed" and item.subject_type == subject_type
        and item.subject_id == subject_id and item.fact_key == fact_key
    ]
    active = max(confirmed, key=lambda item: item.updated_at) if confirmed else None
    if active is not None and active.value == value and active.value_unit == value_unit:
        return None
    return create_learning_fact(
        repository=learning_repository,
        entry_id=entry_id,
        subject_type=subject_type, subject_id=subject_id, subject_label=subject_label,
        fact_key=fact_key, value=value, value_unit=value_unit, confidence=confidence,
        source_type=source_type, evidence=[evidence], created_by=created_by,
        supersedes_fact_id=None if active is None else active.fact_id,
        occurred_at=occurred_at, master_repository=master_repository,
    )


def _ai_sample(items: list[_MatchedMessage]) -> list[_MatchedMessage]:
    ordered = sorted(items, key=lambda item: (item.sent_at, item.source_reference))
    if len(ordered) <= MAX_AI_SAMPLE_MESSAGES:
        return ordered
    # Even sampling preserves history span instead of over-weighting only the newest emails.
    indexes = [round(i * (len(ordered) - 1) / (MAX_AI_SAMPLE_MESSAGES - 1)) for i in range(MAX_AI_SAMPLE_MESSAGES)]
    return [ordered[index] for index in dict.fromkeys(indexes)]


def _ai_bundle(items: list[_MatchedMessage]) -> PrivacySafeText:
    sample = _ai_sample(items)
    sections = []
    for index, item in enumerate(sample, 1):
        sections.append((
            f"MESSAGE_{index:03d}",
            f"DIRECTION: {item.direction}\nDATE_UTC: {item.sent_at.isoformat()}\nSUBJECT: {item.subject_text}\nBODY:\n{item.body_text}",
        ))
    return prepare_privacy_safe_source_bundle(sections).safe_text


def analyze_relationship_history(
    *, messages: Iterable[HistoricalMailMessage], agency_addresses: Iterable[str],
    master_repository: MasterDataRepository, learning_repository: LearningFactRepository,
    created_by: str, ai_analyzer: RelationshipHistoryAIAnalyzer | None = None,
    occurred_at: datetime | None = None,
) -> RelationshipHistoryAnalysisResult:
    timestamp = occurred_at or datetime.now(timezone.utc)
    timestamp = _aware(timestamp)
    agency = {_address(item) for item in agency_addresses}
    if not agency:
        raise ValueError("At least one agency email address is required for relationship onboarding.")

    original = list(messages)
    unique: dict[str, HistoricalMailMessage] = {}
    for message in original:
        existing = unique.get(message.source_reference)
        if existing is not None and existing.model_dump() != message.model_dump():
            raise ValueError("Historical source_reference was reused with different message evidence.")
        unique[message.source_reference] = message

    (
        address_index, ambiguous_master_addresses, domain_index, ambiguous_master_domains,
    ) = _master_indexes(master_repository)
    matched: list[_MatchedMessage] = []
    unmatched_addresses: set[str] = set()
    ambiguous_addresses: set[str] = set()
    ambiguous_count = 0
    unmatched_count = 0
    for message in unique.values():
        item, unmatched, ambiguous = _match_message(
            message, agency_addresses=agency, address_index=address_index,
            ambiguous_addresses=ambiguous_master_addresses, domain_index=domain_index,
            ambiguous_domains=ambiguous_master_domains,
        )
        unmatched_addresses.update(unmatched)
        ambiguous_addresses.update(ambiguous)
        if item is None:
            if ambiguous:
                ambiguous_count += 1
            else:
                unmatched_count += 1
            continue
        matched.append(item)

    groups: dict[tuple[str, str, str], list[_MatchedMessage]] = defaultdict(list)
    for item in matched:
        groups[(item.subject_type, item.subject_id, item.subject_label)].append(item)

    summaries: list[RelationshipHistorySubjectSummary] = []
    ai_observation_count = 0
    proposed_total = 0
    ai_category_map = {
        "communication_style": "relationship.communication_style",
        "timing_pattern": "relationship.timing_pattern",
        "negotiation_behavior": "relationship.negotiation_behavior",
        "commercial_behavior": "relationship.commercial_behavior",
        "operational_behavior": "relationship.operational_behavior",
        "relationship_pattern": "relationship.pattern",
        "vehicle_information_behavior": "relationship.vehicle_information_behavior",
        "urgency_pattern": "relationship.urgency_pattern",
        "quote_preference": "relationship.quote_preference",
    }

    for (subject_type, subject_id, label), items in sorted(groups.items(), key=lambda pair: (pair[0][0], pair[0][2].casefold())):
        digest = _digest(items)
        inbound = [item for item in items if item.direction == "inbound"]
        outbound = [item for item in items if item.direction == "outbound"]
        counterparty_response = _response_minutes(items, "outbound")
        agency_response = _response_minutes(items, "inbound")
        evidence = LearningEvidence(
            source_type="email", source_reference=f"relationship-history:{subject_type}:{subject_id}:{digest[:24]}",
            observed_at=timestamp,
            summary=(
                f"Aggregated {len(items)} historical email events across "
                f"{len(set(item.subject_key for item in items))} normalized threads; raw message bodies are not persisted."
            ),
            source_sha256=digest,
        )
        metrics: list[tuple[str, Any, str | None, float]] = [
            ("history.email.total_count", len(items), "messages", _confidence(len(items))),
            ("history.email.inbound_count", len(inbound), "messages", _confidence(len(inbound))),
            ("history.email.outbound_count", len(outbound), "messages", _confidence(len(outbound))),
            ("history.email.thread_count", len(set(item.subject_key for item in items)), "threads", _confidence(len(items))),
        ]
        weekdays = _active_weekdays(items)
        if weekdays:
            metrics.append(("history.email.active_weekdays", weekdays, None, _confidence(len(inbound), base=0.45, cap=0.90)))
        if counterparty_response:
            metrics.extend([
                ("history.email.counterparty_response_median_minutes", round(float(median(counterparty_response)), 2), "minutes", _confidence(len(counterparty_response))),
                ("history.email.counterparty_response_average_minutes", round(sum(counterparty_response)/len(counterparty_response), 2), "minutes", _confidence(len(counterparty_response), base=0.45, cap=0.90)),
            ])
        if agency_response:
            metrics.append(("history.email.agency_response_median_minutes", round(float(median(agency_response)), 2), "minutes", _confidence(len(agency_response))))
        if items:
            metrics.append(("history.email.last_observed_at", max(item.sent_at for item in items).isoformat(), None, 0.99))

        proposed_ids: list[str] = []
        for fact_key, value, unit, confidence in metrics:
            fact = _propose_fact(
                learning_repository=learning_repository, master_repository=master_repository,
                subject_type=subject_type, subject_id=subject_id, subject_label=label,
                fact_key=fact_key, value=value, value_unit=unit, confidence=confidence,
                evidence=evidence, digest=digest, created_by=created_by, occurred_at=timestamp,
            )
            if fact is not None:
                proposed_ids.append(fact.fact_id); proposed_total += 1

        if ai_analyzer is not None and items:
            observations = ai_analyzer.analyze(subject_type=subject_type, history_text=_ai_bundle(items))
            for observation in observations.observations:
                if subject_type == "customer" and observation.category == "vehicle_information_behavior":
                    continue
                fact_key = ai_category_map[observation.category]
                fact = _propose_fact(
                    learning_repository=learning_repository, master_repository=master_repository,
                    subject_type=subject_type, subject_id=subject_id, subject_label=label,
                    fact_key=fact_key, value=observation.observation, confidence=observation.confidence,
                    evidence=LearningEvidence(
                        source_type="email", source_reference=evidence.source_reference,
                        observed_at=timestamp,
                        summary=f"AI relationship observation from {min(len(items), MAX_AI_SAMPLE_MESSAGES)} privacy-transformed historical emails.",
                        source_sha256=digest,
                    ),
                    digest=digest, created_by=created_by, occurred_at=timestamp,
                    source_type="minai_inference",
                )
                if fact is not None:
                    proposed_ids.append(fact.fact_id); proposed_total += 1; ai_observation_count += 1

        summaries.append(RelationshipHistorySubjectSummary(
            subject_type=subject_type, subject_id=subject_id, subject_label=label,
            message_count=len(items), inbound_count=len(inbound), outbound_count=len(outbound),
            thread_count=len(set(item.subject_key for item in items)),
            counterparty_response_sample_count=len(counterparty_response), agency_response_sample_count=len(agency_response),
            proposed_fact_ids=proposed_ids,
        ))

    return RelationshipHistoryAnalysisResult(
        input_message_count=len(original), unique_message_count=len(unique),
        duplicate_message_count=len(original)-len(unique), matched_message_count=len(matched),
        unmatched_message_count=unmatched_count, ambiguous_message_count=ambiguous_count,
        subjects=summaries, unmatched_addresses=sorted(unmatched_addresses),
        ambiguous_addresses=sorted(ambiguous_addresses), proposed_fact_count=proposed_total,
        ai_observation_count=ai_observation_count,
    )
