from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.master_data_repository import MasterDataRepository
from src.core.relationship_history import HistoricalMailMessage


CounterpartyMatchStatus = Literal[
    "unmatched",
    "known_customer",
    "known_customer_domain",
    "known_supplier",
    "ambiguous_master",
]
CounterpartySubjectType = Literal["customer", "supplier"]

_REPLY_PREFIX = re.compile(
    r"^(?:(?:re|fw|fwd|yanıt|yanit|cevap)\s*:\s*)+",
    re.I,
)


def _address(value: str) -> str:
    normalized = str(value).strip().casefold()
    if (
        normalized.count("@") != 1
        or any(character.isspace() for character in normalized)
    ):
        raise ValueError("Counterparty discovery requires valid email addresses.")
    return normalized


def _subject_key(subject: str) -> str:
    value = " ".join(str(subject or "").casefold().split())
    previous = None
    while previous != value:
        previous = value
        value = _REPLY_PREFIX.sub("", value).strip()
    return value or "(no-subject)"


class CounterpartyDiscoveryCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email_address: str
    domain: str
    message_count: int = Field(ge=1)
    inbound_count: int = Field(ge=0)
    outbound_count: int = Field(ge=0)
    thread_count: int = Field(ge=1)
    first_observed_at: datetime
    last_observed_at: datetime
    master_match_status: CounterpartyMatchStatus = "unmatched"
    subject_type: CounterpartySubjectType | None = None
    subject_id: str | None = None
    subject_label: str | None = None


class CounterpartyDomainSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str
    candidate_address_count: int = Field(ge=1)
    contact_event_count: int = Field(ge=1)
    inbound_count: int = Field(ge=0)
    outbound_count: int = Field(ge=0)
    thread_count: int = Field(ge=1)
    first_observed_at: datetime
    last_observed_at: datetime
    addresses: list[str] = Field(min_length=1, max_length=500)


class CounterpartyDiscoveryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_message_count: int = Field(ge=0)
    unique_message_count: int = Field(ge=0)
    duplicate_message_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    unmatched_candidate_count: int = Field(ge=0)
    known_candidate_count: int = Field(ge=0)
    ambiguous_candidate_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    candidates: list[CounterpartyDiscoveryCandidate] = Field(default_factory=list)
    domains: list[CounterpartyDomainSummary] = Field(default_factory=list)
    raw_body_persisted: bool = False
    note: str = (
        "Discovery is read-only. Unmatched addresses are candidates for human "
        "classification and do not create customer or supplier master data."
    )


Owner = tuple[CounterpartySubjectType, str, str]


def _collapse_owners(
    source: dict[str, set[Owner]],
) -> tuple[dict[str, Owner], set[str]]:
    index: dict[str, Owner] = {}
    ambiguous: set[str] = set()
    for key, entries in source.items():
        if len(entries) == 1:
            index[key] = next(iter(entries))
        elif entries:
            ambiguous.add(key)
    return index, ambiguous


def _master_indexes(
    repository: MasterDataRepository,
) -> tuple[dict[str, Owner], set[str], dict[str, Owner], set[str]]:
    address_owners: dict[str, set[Owner]] = defaultdict(set)
    domain_owners: dict[str, set[Owner]] = defaultdict(set)

    for customer in repository.list_customers():
        owner: Owner = ("customer", customer.customer_id, customer.customer_name)
        addresses = set(customer.trusted_sender_addresses)
        addresses.update(
            contact.email
            for contact in customer.contacts
            if contact.active and contact.email
        )
        for address in addresses:
            address_owners[_address(address)].add(owner)
        for domain in customer.trusted_sender_domains:
            normalized = str(domain).strip().casefold().lstrip("@")
            if normalized and "." in normalized and not any(
                character.isspace() for character in normalized
            ):
                domain_owners[normalized].add(owner)

    for supplier in repository.list_suppliers():
        owner = ("supplier", supplier.supplier_id, supplier.supplier_name)
        for contact in supplier.contacts:
            if contact.active and contact.email:
                address_owners[_address(contact.email)].add(owner)

    address_index, ambiguous_addresses = _collapse_owners(address_owners)
    domain_index, ambiguous_domains = _collapse_owners(domain_owners)
    return (
        address_index,
        ambiguous_addresses,
        domain_index,
        ambiguous_domains,
    )


def _master_match(
    email_address: str,
    *,
    address_index: dict[str, Owner],
    ambiguous_addresses: set[str],
    domain_index: dict[str, Owner],
    ambiguous_domains: set[str],
) -> tuple[CounterpartyMatchStatus, Owner | None]:
    domain = email_address.rsplit("@", 1)[-1]
    if email_address in ambiguous_addresses or domain in ambiguous_domains:
        return "ambiguous_master", None
    direct = address_index.get(email_address)
    if direct is not None:
        return (
            "known_customer" if direct[0] == "customer" else "known_supplier",
            direct,
        )
    domain_owner = domain_index.get(domain)
    if domain_owner is not None:
        if domain_owner[0] != "customer":
            return "ambiguous_master", None
        return "known_customer_domain", domain_owner
    return "unmatched", None


def discover_historical_counterparties(
    *,
    messages: list[HistoricalMailMessage],
    agency_addresses: list[str],
    master_repository: MasterDataRepository,
) -> CounterpartyDiscoveryResult:
    agency = {_address(address) for address in agency_addresses}
    if not agency:
        raise ValueError(
            "Counterparty discovery requires at least one agency email address."
        )

    unique: dict[str, HistoricalMailMessage] = {}
    for message in messages:
        existing = unique.get(message.source_reference)
        if existing is not None and existing.model_dump() != message.model_dump():
            raise ValueError(
                "Historical source_reference was reused with different message evidence."
            )
        unique[message.source_reference] = message

    address_index, ambiguous_addresses, domain_index, ambiguous_domains = (
        _master_indexes(master_repository)
    )
    stats: dict[str, dict[str, object]] = {}
    domain_threads: dict[str, set[str]] = defaultdict(set)
    for message in unique.values():
        sender = _address(message.sender_address)
        recipients = {_address(address) for address in message.recipient_addresses}
        if sender in agency:
            direction = "outbound"
            counterparties = recipients - agency
        elif sender not in agency and recipients.intersection(agency):
            direction = "inbound"
            counterparties = {sender}
        else:
            continue

        thread_key = (
            message.in_reply_to_reference or _subject_key(message.subject)
        )
        for email_address in counterparties:
            if email_address in agency:
                continue
            item = stats.setdefault(
                email_address,
                {
                    "inbound": 0,
                    "outbound": 0,
                    "threads": set(),
                    "first": message.sent_at,
                    "last": message.sent_at,
                },
            )
            item[direction] = int(item[direction]) + 1
            cast_threads = item["threads"]
            assert isinstance(cast_threads, set)
            cast_threads.add(thread_key)
            domain_threads[email_address.rsplit("@", 1)[-1]].add(thread_key)
            first = item["first"]
            last = item["last"]
            assert isinstance(first, datetime) and isinstance(last, datetime)
            if message.sent_at < first:
                item["first"] = message.sent_at
            if message.sent_at > last:
                item["last"] = message.sent_at

    candidates: list[CounterpartyDiscoveryCandidate] = []
    for email_address, item in stats.items():
        match_status, owner = _master_match(
            email_address,
            address_index=address_index,
            ambiguous_addresses=ambiguous_addresses,
            domain_index=domain_index,
            ambiguous_domains=ambiguous_domains,
        )
        inbound = int(item["inbound"])
        outbound = int(item["outbound"])
        threads = item["threads"]
        first = item["first"]
        last = item["last"]
        assert isinstance(threads, set)
        assert isinstance(first, datetime) and isinstance(last, datetime)
        candidates.append(
            CounterpartyDiscoveryCandidate(
                email_address=email_address,
                domain=email_address.rsplit("@", 1)[-1],
                message_count=inbound + outbound,
                inbound_count=inbound,
                outbound_count=outbound,
                thread_count=len(threads),
                first_observed_at=first,
                last_observed_at=last,
                master_match_status=match_status,
                subject_type=None if owner is None else owner[0],
                subject_id=None if owner is None else owner[1],
                subject_label=None if owner is None else owner[2],
            )
        )

    candidates.sort(
        key=lambda item: (-item.message_count, item.email_address)
    )

    by_domain: dict[str, list[CounterpartyDiscoveryCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_domain[candidate.domain].append(candidate)

    domains: list[CounterpartyDomainSummary] = []
    for domain, items in by_domain.items():
        domains.append(
            CounterpartyDomainSummary(
                domain=domain,
                candidate_address_count=len(items),
                contact_event_count=sum(item.message_count for item in items),
                inbound_count=sum(item.inbound_count for item in items),
                outbound_count=sum(item.outbound_count for item in items),
                thread_count=len(domain_threads[domain]),
                first_observed_at=min(item.first_observed_at for item in items),
                last_observed_at=max(item.last_observed_at for item in items),
                addresses=sorted(item.email_address for item in items),
            )
        )
    domains.sort(
        key=lambda item: (-item.contact_event_count, item.domain)
    )

    unmatched_count = sum(
        item.master_match_status == "unmatched" for item in candidates
    )
    ambiguous_count = sum(
        item.master_match_status == "ambiguous_master" for item in candidates
    )
    known_count = len(candidates) - unmatched_count - ambiguous_count

    return CounterpartyDiscoveryResult(
        input_message_count=len(messages),
        unique_message_count=len(unique),
        duplicate_message_count=len(messages) - len(unique),
        candidate_count=len(candidates),
        unmatched_candidate_count=unmatched_count,
        known_candidate_count=known_count,
        ambiguous_candidate_count=ambiguous_count,
        domain_count=len(domains),
        candidates=candidates,
        domains=domains,
    )
