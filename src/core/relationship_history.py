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
AI_SAMPLE_ONLY_CONFIDENCE_CAP = 0.70
AI_RECURRING_MIN_EVIDENCE = {
    "communication_style": (2, 2),
    "timing_pattern": (5, 3),
    "negotiation_behavior": (3, 2),
    "commercial_behavior": (2, 2),
    "operational_behavior": (2, 2),
    "relationship_pattern": (5, 3),
    "vehicle_information_behavior": (2, 2),
    "urgency_pattern": (5, 3),
    "quote_preference": (5, 3),
}
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
    scope: Literal["sample_only", "recurring_pattern"]
    supporting_counterparty_message_indexes: list[int] = Field(min_length=1, max_length=MAX_AI_SAMPLE_MESSAGES)

    @model_validator(mode="after")
    def validate_support_indexes(self):
        if len(self.supporting_counterparty_message_indexes) != len(set(self.supporting_counterparty_message_indexes)):
            raise ValueError("AI observation support message indexes must be unique.")
        if any(index < 1 or index > MAX_AI_SAMPLE_MESSAGES for index in self.supporting_counterparty_message_indexes):
            raise ValueError("AI observation support message index is outside the bounded AI sample.")
        return self


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
    counterparty_response_median_minutes: float | None = None
    counterparty_response_confidence: float | None = Field(default=None, ge=0, le=1)
    latest_observed_at: datetime | None = None
    history_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
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
    ai_observation_sample_only_count: int = 0
    ai_observation_recurring_count: int = 0
    ai_observation_hard_rejected_count: int = 0
    ai_observation_skipped_count: int = 0
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
    # AI receives two-way conversation context. AGENCY messages may explain what the
    # counterparty is responding to, but they are never valid behavioral support.
    ordered = sorted(items, key=lambda item: (item.sent_at, item.source_reference))
    if len(ordered) <= MAX_AI_SAMPLE_MESSAGES:
        return ordered
    indexes = [round(i * (len(ordered) - 1) / (MAX_AI_SAMPLE_MESSAGES - 1)) for i in range(MAX_AI_SAMPLE_MESSAGES)]
    return [ordered[index] for index in dict.fromkeys(indexes)]


def _ai_bundle_from_sample(sample: list[_MatchedMessage]) -> PrivacySafeText:
    counterpart_count = sum(item.direction == "inbound" for item in sample)
    sections = [(
        "EVIDENCE_SCOPE",
        f"TWO_WAY_CONTEXT_MESSAGES: {len(sample)}\n"
        f"COUNTERPARTY_AUTHORED_MESSAGES: {counterpart_count}\n"
        "AGENCY messages are context only. Behavioral support indexes must point only to COUNTERPARTY messages.",
    )]
    for index, item in enumerate(sample, 1):
        author = "COUNTERPARTY" if item.direction == "inbound" else "AGENCY"
        sections.append((
            f"MESSAGE_{index:03d}",
            f"AUTHOR: {author}\nDATE_UTC: {item.sent_at.isoformat()}\nSUBJECT: {item.subject_text}\nBODY:\n{item.body_text}",
        ))
    return prepare_privacy_safe_source_bundle(sections).safe_text


def _ai_observation_confidence_cap(*, effective_scope: str, support_message_count: int) -> float:
    if effective_scope == "sample_only":
        return AI_SAMPLE_ONLY_CONFIDENCE_CAP
    if support_message_count < 5:
        return 0.75
    if support_message_count < 8:
        return 0.85
    return 0.95


def _grade_ai_observation(
    observation: RelationshipAIObservation, *, subject_type: RelationshipSubjectType,
    sample: list[_MatchedMessage],
) -> tuple[bool, str | None, int, int]:
    if subject_type == "customer" and observation.category == "vehicle_information_behavior":
        return False, None, 0, 0

    support_indexes = observation.supporting_counterparty_message_indexes
    if any(index > len(sample) for index in support_indexes):
        return False, None, 0, 0
    supported = [sample[index - 1] for index in support_indexes]
    # This is the central attribution hard guard: agency-authored context can never
    # become evidence about the counterparty's behavior.
    if any(item.direction != "inbound" for item in supported):
        return False, None, 0, 0

    support_message_count = len(supported)
    support_thread_count = len({item.subject_key for item in supported})
    effective_scope = observation.scope
    if observation.scope == "recurring_pattern":
        min_messages, min_threads = AI_RECURRING_MIN_EVIDENCE[observation.category]
        if support_message_count < min_messages or support_thread_count < min_threads:
            # Thin evidence is not discarded. It is transparently downgraded to a
            # sample-limited proposal and remains subject to human review.
            effective_scope = "sample_only"

    if observation.category == "relationship_pattern":
        normalized = observation.observation.casefold()
        unsupported_internal_state = (
            "strong relationship", "reliance", "relies on", "trust",
            "güçlü ilişki", "bağımlı", "güveniyor", "güven ilişkisi",
        )
        if any(claim in normalized for claim in unsupported_internal_state):
            return False, None, 0, 0

    return True, effective_scope, support_message_count, support_thread_count


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
    ai_observation_sample_only_count = 0
    ai_observation_recurring_count = 0
    ai_observation_hard_rejected_count = 0
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
        latest_observed_at = max(item.sent_at for item in items)
        evidence = LearningEvidence(
            source_type="email", source_reference=f"relationship-history:{subject_type}:{subject_id}:{digest[:24]}",
            observed_at=latest_observed_at,
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

        ai_sample = _ai_sample(items)
        if ai_analyzer is not None and any(item.direction == "inbound" for item in ai_sample):
            ai_text = _ai_bundle_from_sample(ai_sample)
            observations = ai_analyzer.analyze(subject_type=subject_type, history_text=ai_text)
            ai_digest = hashlib.sha256(str(ai_text).encode("utf-8")).hexdigest()
            for observation in observations.observations:
                accepted, effective_scope, support_message_count, support_thread_count = _grade_ai_observation(
                    observation, subject_type=subject_type, sample=ai_sample,
                )
                if not accepted or effective_scope is None:
                    ai_observation_hard_rejected_count += 1
                    continue
                fact_key = ai_category_map[observation.category]
                confidence = min(
                    observation.confidence,
                    _ai_observation_confidence_cap(
                        effective_scope=effective_scope, support_message_count=support_message_count,
                    ),
                )
                fact = _propose_fact(
                    learning_repository=learning_repository, master_repository=master_repository,
                    subject_type=subject_type, subject_id=subject_id, subject_label=label,
                    fact_key=fact_key, value=observation.observation, confidence=confidence,
                    evidence=LearningEvidence(
                        source_type="email",
                        source_reference=f"relationship-history-ai:{subject_type}:{subject_id}:{ai_digest[:24]}",
                        observed_at=max(
                            ai_sample[index - 1].sent_at
                            for index in observation.supporting_counterparty_message_indexes
                        ),
                        summary=(
                            f"AI relationship observation from {len(ai_sample)} two-way privacy-transformed "
                            f"historical emails; model_scope={observation.scope}; effective_scope={effective_scope}; "
                            f"counterparty_support={support_message_count} messages/{support_thread_count} threads. "
                            "Agency-authored messages were context only and were not counted as behavioral support."
                        ),
                        source_sha256=ai_digest,
                    ),
                    digest=ai_digest, created_by=created_by, occurred_at=timestamp,
                    source_type="minai_inference",
                )
                if fact is not None:
                    proposed_ids.append(fact.fact_id); proposed_total += 1; ai_observation_count += 1
                    if effective_scope == "sample_only":
                        ai_observation_sample_only_count += 1
                    else:
                        ai_observation_recurring_count += 1

        summaries.append(RelationshipHistorySubjectSummary(
            subject_type=subject_type, subject_id=subject_id, subject_label=label,
            message_count=len(items), inbound_count=len(inbound), outbound_count=len(outbound),
            thread_count=len(set(item.subject_key for item in items)),
            counterparty_response_sample_count=len(counterparty_response),
            agency_response_sample_count=len(agency_response),
            counterparty_response_median_minutes=(
                round(float(median(counterparty_response)), 2) if counterparty_response else None
            ),
            counterparty_response_confidence=(
                _confidence(len(counterparty_response)) if counterparty_response else None
            ),
            latest_observed_at=latest_observed_at, history_digest=digest,
            proposed_fact_ids=proposed_ids,
        ))

    return RelationshipHistoryAnalysisResult(
        input_message_count=len(original), unique_message_count=len(unique),
        duplicate_message_count=len(original)-len(unique), matched_message_count=len(matched),
        unmatched_message_count=unmatched_count, ambiguous_message_count=ambiguous_count,
        subjects=summaries, unmatched_addresses=sorted(unmatched_addresses),
        ambiguous_addresses=sorted(ambiguous_addresses), proposed_fact_count=proposed_total,
        ai_observation_count=ai_observation_count,
        ai_observation_sample_only_count=ai_observation_sample_only_count,
        ai_observation_recurring_count=ai_observation_recurring_count,
        ai_observation_hard_rejected_count=ai_observation_hard_rejected_count,
        ai_observation_skipped_count=ai_observation_hard_rejected_count,
    )
