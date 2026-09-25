from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.ai.relationship_history_analyzer import (
    OpenAIRelationshipHistoryAnalyzer,
    RelationshipHistoryAnalyzerUnavailableError,
)
from src.core.agency_learning_bootstrap import (
    AgencyLearningBootstrapSnapshot,
    SQLiteAgencyLearningBootstrapRepository,
    build_candidate_snapshot,
    count_mail_directions,
    source_reference_hash,
    summarize_agency_workflow_patterns,
)
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.relationship_history import analyze_relationship_history
from src.core.supplier_history_backfill import propose_supplier_operational_backfill
from src.integrations.imap_mail import ImapReadClient
from src.integrations.mailbox_credentials import ImapMailboxCredential
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    acquire_silent_access_token,
)
from src.integrations.outlook_graph import OutlookGraphReadClient


DEFAULT_BOOTSTRAP_HISTORY_DAYS = 180
DEFAULT_BOOTSTRAP_MAX_MESSAGES = 5000


def _run_bootstrap(
    *,
    client,
    provider: str,
    mailbox_id: str,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    state_repository: SQLiteAgencyLearningBootstrapRepository,
    created_by: str,
    history_days: int = DEFAULT_BOOTSTRAP_HISTORY_DAYS,
    max_messages: int = DEFAULT_BOOTSTRAP_MAX_MESSAGES,
    include_ai_observations: bool = False,
    ai_analyzer_factory: Callable[[], Any] = OpenAIRelationshipHistoryAnalyzer,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Agency learning bootstrap now must be timezone-aware.")
    current = current.astimezone(timezone.utc)
    if history_days < 30 or history_days > 370:
        raise ValueError("Agency learning bootstrap history_days must be 30-370.")
    if max_messages < 1 or max_messages > 10000:
        raise ValueError("Agency learning bootstrap max_messages must be 1-10000.")
    start_at = current - timedelta(days=history_days)
    state_repository.save(
        AgencyLearningBootstrapSnapshot(
            status="running",
            provider=provider,
            mailbox_id=mailbox_id,
            started_at=current,
            history_start_at=start_at,
            history_end_at=current,
        )
    )
    messages = client.list_relationship_history(
        start_at=start_at,
        end_at=current,
        max_messages=max_messages,
    )
    try:
        agency_addresses, candidates, discovery = build_candidate_snapshot(
            messages=messages,
            mailbox_id=mailbox_id,
            master_repository=master_repository,
        )
        inbound_count, outbound_count = count_mail_directions(
            messages=messages,
            agency_addresses=agency_addresses,
        )
        workflow_patterns = summarize_agency_workflow_patterns(
            messages=messages,
            agency_addresses=agency_addresses,
        )
        ai_analyzer = None
        if include_ai_observations:
            try:
                ai_analyzer = ai_analyzer_factory()
            except (ValueError, RelationshipHistoryAnalyzerUnavailableError):
                ai_analyzer = None
        try:
            relationship = analyze_relationship_history(
                messages=messages,
                agency_addresses=agency_addresses,
                master_repository=master_repository,
                learning_repository=learning_repository,
                created_by=created_by,
                ai_analyzer=ai_analyzer,
                occurred_at=current,
            )
        except RelationshipHistoryAnalyzerUnavailableError:
            relationship = analyze_relationship_history(
                messages=messages,
                agency_addresses=agency_addresses,
                master_repository=master_repository,
                learning_repository=learning_repository,
                created_by=created_by,
                ai_analyzer=None,
                occurred_at=current,
            )
        supplier_backfill = propose_supplier_operational_backfill(
            analysis=relationship,
            learning_repository=learning_repository,
            master_repository=master_repository,
            created_by=created_by,
        )
        snapshot = AgencyLearningBootstrapSnapshot(
            status="completed",
            provider=provider,
            mailbox_id=mailbox_id,
            started_at=current,
            completed_at=datetime.now(timezone.utc),
            history_start_at=start_at,
            history_end_at=current,
            scanned_message_count=len(messages),
            inbound_message_count=inbound_count,
            outbound_message_count=outbound_count,
            rejected_message_count=len(
                getattr(client, "last_message_rejections", ()) or ()
            ),
            inferred_agency_addresses=agency_addresses,
            workflow_patterns=workflow_patterns,
            candidate_count=len(candidates),
            known_candidate_count=sum(
                item.master_match_status != "unmatched" for item in candidates
            ),
            high_confidence_candidate_count=sum(
                item.subject_type is None
                and item.inferred_role in {"customer", "supplier"}
                and item.confidence >= 0.90
                for item in candidates
            ),
            proposed_fact_count=relationship.proposed_fact_count,
            matched_subject_count=len(relationship.subjects),
            candidates=candidates,
            recent_source_hashes=[
                source_reference_hash(item.source_reference)
                for item in sorted(
                    messages,
                    key=lambda item: (item.sent_at, item.source_reference),
                )[-10000:]
            ],
            raw_messages_persisted=False,
        )
        state_repository.save(snapshot)
        payload = snapshot.model_dump()
        payload.update(
            {
                "relationship_analysis": relationship.model_dump(),
                "counterparty_discovery": {
                    "candidate_count": discovery.candidate_count,
                    "unmatched_candidate_count": discovery.unmatched_candidate_count,
                    "known_candidate_count": discovery.known_candidate_count,
                    "ambiguous_candidate_count": discovery.ambiguous_candidate_count,
                    "domain_count": discovery.domain_count,
                },
                "supplier_operational_backfill": supplier_backfill,
                "ai_analysis_requested": include_ai_observations,
                "raw_messages_persisted": False,
            }
        )
        return payload
    finally:
        messages.clear()


def run_outlook_agency_learning_bootstrap(
    *,
    config: MicrosoftAuthConfig,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    state_repository: SQLiteAgencyLearningBootstrapRepository,
    created_by: str = "MINAI Agency Learning Bootstrap",
    history_days: int = DEFAULT_BOOTSTRAP_HISTORY_DAYS,
    max_messages: int = DEFAULT_BOOTSTRAP_MAX_MESSAGES,
    include_ai_observations: bool = False,
    token_provider=acquire_silent_access_token,
    graph_client_factory=OutlookGraphReadClient,
) -> dict[str, Any]:
    token = token_provider(config)
    client = graph_client_factory(
        access_token=token,
        mailbox_id=config.mailbox_id,
    )
    return _run_bootstrap(
        client=client,
        provider="outlook",
        mailbox_id=config.mailbox_id,
        master_repository=master_repository,
        learning_repository=learning_repository,
        state_repository=state_repository,
        created_by=created_by,
        history_days=history_days,
        max_messages=max_messages,
        include_ai_observations=include_ai_observations,
    )


def run_imap_agency_learning_bootstrap(
    *,
    credential: ImapMailboxCredential,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    state_repository: SQLiteAgencyLearningBootstrapRepository,
    created_by: str = "MINAI Agency Learning Bootstrap",
    history_days: int = DEFAULT_BOOTSTRAP_HISTORY_DAYS,
    max_messages: int = DEFAULT_BOOTSTRAP_MAX_MESSAGES,
    include_ai_observations: bool = False,
    client_factory=ImapReadClient,
) -> dict[str, Any]:
    client = client_factory(credential=credential)
    return _run_bootstrap(
        client=client,
        provider="imap",
        mailbox_id=credential.mailbox_id,
        master_repository=master_repository,
        learning_repository=learning_repository,
        state_repository=state_repository,
        created_by=created_by,
        history_days=history_days,
        max_messages=max_messages,
        include_ai_observations=include_ai_observations,
    )
