from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.agency_learning_bootstrap import (
    AgencyCounterpartyLearningCandidate,
    AgencyLearningBootstrapSnapshot,
    AgencyWorkflowPatternSummary,
    source_reference_hash,
)
from src.core.pilot_store import SQLitePilotStore


IncrementalLearningStatus = Literal[
    "not_started", "waiting_bootstrap", "running", "healthy", "failed"
]


class AgencyIncrementalLearningState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: IncrementalLearningStatus = "not_started"
    provider: str | None = Field(default=None, max_length=40)
    mailbox_id: str | None = Field(default=None, max_length=320)
    cursor_at: datetime | None = None
    last_started_at: datetime | None = None
    last_completed_at: datetime | None = None
    last_ai_analysis_at: datetime | None = None
    last_structured_derivation_at: datetime | None = None
    run_count: int = Field(default=0, ge=0)
    last_scanned_message_count: int = Field(default=0, ge=0)
    last_new_message_count: int = Field(default=0, ge=0)
    total_new_message_count: int = Field(default=0, ge=0)
    last_proposed_fact_count: int = Field(default=0, ge=0)
    total_proposed_fact_count: int = Field(default=0, ge=0)
    last_structured_proposed_fact_count: int = Field(default=0, ge=0)
    total_structured_proposed_fact_count: int = Field(default=0, ge=0)
    last_rejected_message_count: int = Field(default=0, ge=0)
    recent_source_hashes: list[str] = Field(default_factory=list, max_length=10000)
    error_code: str | None = Field(default=None, max_length=300)

    @field_validator(
        "cursor_at", "last_started_at", "last_completed_at", "last_ai_analysis_at",
        "last_structured_derivation_at"
    )
    @classmethod
    def require_aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Incremental learning timestamps must be timezone-aware.")
        return value

    @field_validator("recent_source_hashes")
    @classmethod
    def validate_source_hashes(cls, values):
        normalized = []
        for value in values:
            item = str(value).strip().casefold()
            if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
                raise ValueError("Incremental source hashes must be SHA-256 hex digests.")
            if item not in normalized:
                normalized.append(item)
        return normalized


class SQLiteAgencyIncrementalLearningRepository:
    NAMESPACE = "agency_incremental_learning"
    RECORD_KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> AgencyIncrementalLearningState:
        raw = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        if raw is None:
            return AgencyIncrementalLearningState()
        return AgencyIncrementalLearningState.model_validate(raw)

    def save(
        self, state: AgencyIncrementalLearningState
    ) -> AgencyIncrementalLearningState:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=self.RECORD_KEY,
            payload=state.model_dump(mode="json"),
            event_type="agency_incremental_learning_state_changed",
            entity_type="agency_incremental_learning",
        )
        return state


def add_workflow_patterns(
    base: AgencyWorkflowPatternSummary,
    delta: AgencyWorkflowPatternSummary,
) -> AgencyWorkflowPatternSummary:
    rfq_fields = dict(base.rfq_field_frequencies)
    for key, value in delta.rfq_field_frequencies.items():
        rfq_fields[key] = int(rfq_fields.get(key, 0)) + int(value)
    quote_terms = dict(base.quote_term_frequencies)
    for key, value in delta.quote_term_frequencies.items():
        quote_terms[key] = int(quote_terms.get(key, 0)) + int(value)
    return AgencyWorkflowPatternSummary(
        supplier_rfq_message_count=(
            base.supplier_rfq_message_count + delta.supplier_rfq_message_count
        ),
        customer_quote_message_count=(
            base.customer_quote_message_count + delta.customer_quote_message_count
        ),
        customer_quote_followup_count=(
            base.customer_quote_followup_count + delta.customer_quote_followup_count
        ),
        supplier_negotiation_message_count=(
            base.supplier_negotiation_message_count
            + delta.supplier_negotiation_message_count
        ),
        operational_update_message_count=(
            base.operational_update_message_count
            + delta.operational_update_message_count
        ),
        finance_message_count=(
            base.finance_message_count + delta.finance_message_count
        ),
        rfq_field_frequencies=dict(sorted(rfq_fields.items())),
        quote_term_frequencies=dict(sorted(quote_terms.items())),
    )


def _role_from_counts(
    *,
    domain: str,
    customer_score: int,
    supplier_score: int,
    thread_count: int,
) -> tuple[str, float]:
    generic_domains = {
        "gmail.com", "hotmail.com", "outlook.com", "icloud.com", "yahoo.com",
        "live.com", "msn.com", "proton.me", "protonmail.com",
    }
    margin = abs(customer_score - supplier_score)
    strongest = max(customer_score, supplier_score)
    if domain in generic_domains and strongest < 4:
        return "unknown", 0.45
    if strongest >= 4 and margin >= 3 and thread_count >= 2:
        return ("customer" if customer_score > supplier_score else "supplier"), 0.92
    if strongest >= 2 and margin >= 2:
        return ("customer" if customer_score > supplier_score else "supplier"), 0.78
    return "unknown", (0.50 if strongest else 0.35)


def merge_candidates(
    existing: list[AgencyCounterpartyLearningCandidate],
    delta: list[AgencyCounterpartyLearningCandidate],
) -> list[AgencyCounterpartyLearningCandidate]:
    merged = {item.email_address: item for item in existing}
    for item in delta:
        prior = merged.get(item.email_address)
        if prior is None:
            merged[item.email_address] = item
            continue

        subject_type = item.subject_type or prior.subject_type
        subject_id = item.subject_id or prior.subject_id
        subject_label = item.subject_label or prior.subject_label
        customer_score = prior.customer_signal_count + item.customer_signal_count
        supplier_score = prior.supplier_signal_count + item.supplier_signal_count
        # Do not add thread counts across polling windows: one long email
        # conversation can reappear in several overlap windows. Taking the maximum
        # is conservative and prevents false confidence escalation.
        thread_count = max(prior.thread_count, item.thread_count)

        if subject_type in {"customer", "supplier"}:
            role = subject_type
            confidence = 0.99
        else:
            role, confidence = _role_from_counts(
                domain=prior.domain,
                customer_score=customer_score,
                supplier_score=supplier_score,
                thread_count=thread_count,
            )

        merged[item.email_address] = AgencyCounterpartyLearningCandidate(
            email_address=prior.email_address,
            domain=prior.domain,
            message_count=prior.message_count + item.message_count,
            inbound_count=prior.inbound_count + item.inbound_count,
            outbound_count=prior.outbound_count + item.outbound_count,
            thread_count=thread_count,
            master_match_status=(
                item.master_match_status
                if item.master_match_status != "unmatched"
                else prior.master_match_status
            ),
            inferred_role=role,
            confidence=confidence,
            customer_signal_count=customer_score,
            supplier_signal_count=supplier_score,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_label=subject_label,
            first_observed_at=min(prior.first_observed_at, item.first_observed_at),
            last_observed_at=max(prior.last_observed_at, item.last_observed_at),
        )

    return sorted(
        merged.values(),
        key=lambda item: (-item.confidence, -item.message_count, item.email_address),
    )[:300]


def snapshot_with_incremental_delta(
    *,
    snapshot: AgencyLearningBootstrapSnapshot,
    inbound_delta: int,
    outbound_delta: int,
    workflow_delta: AgencyWorkflowPatternSummary,
    candidate_delta: list[AgencyCounterpartyLearningCandidate],
    proposed_fact_delta: int,
) -> AgencyLearningBootstrapSnapshot:
    candidates = merge_candidates(snapshot.candidates, candidate_delta)
    return AgencyLearningBootstrapSnapshot.model_validate(
        snapshot.model_copy(
            update={
                "inbound_message_count": snapshot.inbound_message_count + inbound_delta,
                "outbound_message_count": snapshot.outbound_message_count + outbound_delta,
                "workflow_patterns": add_workflow_patterns(
                    snapshot.workflow_patterns, workflow_delta
                ),
                "candidate_count": len(candidates),
                "known_candidate_count": sum(
                    item.subject_type in {"customer", "supplier"} for item in candidates
                ),
                "high_confidence_candidate_count": sum(
                    item.subject_type is None
                    and item.inferred_role in {"customer", "supplier"}
                    and item.confidence >= 0.90
                    for item in candidates
                ),
                "proposed_fact_count": (
                    snapshot.proposed_fact_count + proposed_fact_delta
                ),
                "candidates": candidates,
            }
        ).model_dump(mode="json")
    )
