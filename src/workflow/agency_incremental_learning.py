from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.ai.relationship_history_analyzer import (
    OpenAIRelationshipHistoryAnalyzer,
    RelationshipHistoryAnalyzerUnavailableError,
)
from src.core.agency_incremental_learning import (
    AgencyIncrementalLearningState,
    SQLiteAgencyIncrementalLearningRepository,
    snapshot_with_incremental_delta,
    source_reference_hash,
)
from src.core.agency_learning_bootstrap import (
    SQLiteAgencyLearningBootstrapRepository,
    build_candidate_snapshot,
    count_mail_directions,
    infer_agency_addresses,
    summarize_agency_workflow_patterns,
)
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.relationship_history import HistoricalMailMessage, analyze_relationship_history
from src.integrations.imap_mail import ImapReadClient
from src.integrations.mailbox_credentials import ImapMailboxCredential
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    acquire_silent_access_token,
)
from src.integrations.outlook_graph import OutlookGraphReadClient


DEFAULT_INCREMENTAL_MAX_MESSAGES = 1000
DEFAULT_INCREMENTAL_OVERLAP_HOURS = 48
DEFAULT_INCREMENTAL_AI_MIN_NEW_MESSAGES = 3
DEFAULT_INCREMENTAL_AI_INTERVAL_HOURS = 6
_MAX_SCAN_SPLIT_DEPTH = 7
_MIN_SPLIT_WINDOW = timedelta(minutes=30)


class AgencyIncrementalLearningBacklogError(RuntimeError):
    pass


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Incremental learning timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _scan_history_complete(
    *,
    client,
    start_at: datetime,
    end_at: datetime,
    max_messages: int,
    depth: int = 0,
) -> tuple[list[HistoricalMailMessage], int]:
    messages = client.list_relationship_history(
        start_at=start_at,
        end_at=end_at,
        max_messages=max_messages,
    )
    scan = dict(getattr(client, "last_relationship_history_scan", {}) or {})
    rejection_count = len(getattr(client, "last_message_rejections", ()) or ())
    truncated = bool(scan.get("truncated"))
    if not scan and len(messages) >= max_messages:
        truncated = True
    if not truncated:
        return messages, rejection_count

    span = end_at - start_at
    if depth >= _MAX_SCAN_SPLIT_DEPTH or span <= _MIN_SPLIT_WINDOW:
        raise AgencyIncrementalLearningBacklogError(
            "incremental_mail_window_exceeds_safe_scan_capacity"
        )
    midpoint = start_at + span / 2
    left, left_rejections = _scan_history_complete(
        client=client,
        start_at=start_at,
        end_at=midpoint,
        max_messages=max_messages,
        depth=depth + 1,
    )
    right, right_rejections = _scan_history_complete(
        client=client,
        start_at=midpoint,
        end_at=end_at,
        max_messages=max_messages,
        depth=depth + 1,
    )
    merged = {item.source_reference: item for item in [*left, *right]}
    return (
        sorted(merged.values(), key=lambda item: (item.sent_at, item.source_reference)),
        left_rejections + right_rejections,
    )


def _recent_hashes(
    messages: list[HistoricalMailMessage],
    prior_hashes: list[str],
) -> list[str]:
    ordered: list[str] = []
    for item in prior_hashes:
        if item not in ordered:
            ordered.append(item)
    for message in sorted(messages, key=lambda item: (item.sent_at, item.source_reference)):
        digest = source_reference_hash(message.source_reference)
        if digest in ordered:
            ordered.remove(digest)
        ordered.append(digest)
    return ordered[-10000:]


def _new_messages(
    *,
    messages: list[HistoricalMailMessage],
    state: AgencyIncrementalLearningState,
    cursor_at: datetime,
) -> list[HistoricalMailMessage]:
    seen = set(state.recent_source_hashes)
    first_run_without_bootstrap_hashes = (
        state.run_count == 0 and not state.recent_source_hashes
    )
    result = []
    for message in messages:
        digest = source_reference_hash(message.source_reference)
        if digest in seen:
            continue
        if first_run_without_bootstrap_hashes and message.sent_at <= cursor_at:
            # Backward-compatible migration path for bootstrap snapshots created
            # before recent source hashes were persisted.
            continue
        result.append(message)
    return result


def _ai_due(
    *,
    state: AgencyIncrementalLearningState,
    now: datetime,
    new_message_count: int,
    include_ai_observations: bool,
    minimum_new_messages: int,
    interval_hours: int,
) -> bool:
    if not include_ai_observations or new_message_count < minimum_new_messages:
        return False
    if state.last_ai_analysis_at is None:
        return True
    return now - state.last_ai_analysis_at >= timedelta(hours=interval_hours)


def run_incremental_agency_learning(
    *,
    client,
    provider: str,
    mailbox_id: str,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    bootstrap_repository: SQLiteAgencyLearningBootstrapRepository,
    incremental_repository: SQLiteAgencyIncrementalLearningRepository,
    created_by: str = "MINAI Incremental Agency Learning",
    max_messages: int = DEFAULT_INCREMENTAL_MAX_MESSAGES,
    overlap_hours: int = DEFAULT_INCREMENTAL_OVERLAP_HOURS,
    include_ai_observations: bool = False,
    ai_min_new_messages: int = DEFAULT_INCREMENTAL_AI_MIN_NEW_MESSAGES,
    ai_interval_hours: int = DEFAULT_INCREMENTAL_AI_INTERVAL_HOURS,
    agency_alias_addresses: list[str] | tuple[str, ...] | set[str] = (),
    ai_analyzer_factory: Callable[[], Any] = OpenAIRelationshipHistoryAnalyzer,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _aware(now or datetime.now(timezone.utc))
    if not 1 <= max_messages <= 10000:
        raise ValueError("Incremental learning max_messages must be 1-10000.")
    if not 1 <= overlap_hours <= 168:
        raise ValueError("Incremental learning overlap_hours must be 1-168.")
    if not 1 <= ai_min_new_messages <= 100:
        raise ValueError("Incremental AI minimum new messages must be 1-100.")
    if not 1 <= ai_interval_hours <= 168:
        raise ValueError("Incremental AI interval hours must be 1-168.")

    bootstrap = bootstrap_repository.get()
    state = incremental_repository.get()
    if state.mailbox_id != mailbox_id or state.provider != provider:
        state = AgencyIncrementalLearningState(
            provider=provider,
            mailbox_id=mailbox_id,
            recent_source_hashes=list(bootstrap.recent_source_hashes),
        )
    elif (
        state.run_count == 0
        and not state.recent_source_hashes
        and bootstrap.recent_source_hashes
    ):
        state = AgencyIncrementalLearningState.model_validate(
            state.model_copy(
                update={
                    "recent_source_hashes": list(bootstrap.recent_source_hashes),
                }
            ).model_dump(mode="json")
        )
    if (
        bootstrap.status != "completed"
        or bootstrap.provider != provider
        or bootstrap.mailbox_id != mailbox_id
    ):
        waiting = AgencyIncrementalLearningState.model_validate(
            state.model_copy(
                update={
                    "status": "waiting_bootstrap",
                    "provider": provider,
                    "mailbox_id": mailbox_id,
                    "error_code": None,
                }
            ).model_dump(mode="json")
        )
        incremental_repository.save(waiting)
        return {
            "status": "waiting_bootstrap",
            "new_message_count": 0,
            "raw_messages_persisted": False,
        }

    cursor = _aware(
        state.cursor_at
        or bootstrap.history_end_at
        or bootstrap.completed_at
        or current
    )
    if cursor > current:
        cursor = current
    start_at = cursor - timedelta(hours=overlap_hours)

    running = AgencyIncrementalLearningState.model_validate(
        state.model_copy(
            update={
                "status": "running",
                "last_started_at": current,
                "error_code": None,
            }
        ).model_dump(mode="json")
    )
    incremental_repository.save(running)

    messages: list[HistoricalMailMessage] = []
    try:
        messages, rejection_count = _scan_history_complete(
            client=client,
            start_at=start_at,
            end_at=current,
            max_messages=max_messages,
        )
        new_messages = _new_messages(
            messages=messages,
            state=state,
            cursor_at=cursor,
        )
        agency_addresses = sorted(
            {
                *bootstrap.inferred_agency_addresses,
                *infer_agency_addresses(messages, mailbox_id),
                *(
                    str(item).strip().casefold()
                    for item in agency_alias_addresses
                    if str(item).strip() and "@" in str(item)
                ),
            }
        )
        inbound_delta, outbound_delta = count_mail_directions(
            messages=new_messages,
            agency_addresses=agency_addresses,
        )
        workflow_delta = summarize_agency_workflow_patterns(
            messages=new_messages,
            agency_addresses=agency_addresses,
        )
        if new_messages:
            _aliases, candidate_delta, _discovery = build_candidate_snapshot(
                messages=new_messages,
                mailbox_id=mailbox_id,
                master_repository=master_repository,
                agency_alias_addresses=agency_addresses,
            )
        else:
            candidate_delta = []

        run_ai = _ai_due(
            state=state,
            now=current,
            new_message_count=len(new_messages),
            include_ai_observations=include_ai_observations,
            minimum_new_messages=ai_min_new_messages,
            interval_hours=ai_interval_hours,
        )
        proposed_fact_count = 0
        relationship_payload = None
        if new_messages:
            ai_analyzer = None
            if run_ai:
                try:
                    ai_analyzer = ai_analyzer_factory()
                except (ValueError, RelationshipHistoryAnalyzerUnavailableError):
                    ai_analyzer = None
                    run_ai = False
            try:
                relationship = analyze_relationship_history(
                    messages=messages,
                    agency_addresses=agency_addresses,
                    master_repository=master_repository,
                    learning_repository=learning_repository,
                    created_by=created_by,
                    ai_analyzer=ai_analyzer,
                    occurred_at=current,
                    propose_deterministic_metrics=False,
                )
            except RelationshipHistoryAnalyzerUnavailableError:
                run_ai = False
                relationship = analyze_relationship_history(
                    messages=messages,
                    agency_addresses=agency_addresses,
                    master_repository=master_repository,
                    learning_repository=learning_repository,
                    created_by=created_by,
                    ai_analyzer=None,
                    occurred_at=current,
                    propose_deterministic_metrics=False,
                )
            proposed_fact_count = relationship.proposed_fact_count
            relationship_payload = relationship.model_dump()

        completed = AgencyIncrementalLearningState(
            status="healthy",
            provider=provider,
            mailbox_id=mailbox_id,
            cursor_at=current,
            last_started_at=running.last_started_at,
            last_completed_at=datetime.now(timezone.utc),
            last_ai_analysis_at=current if run_ai else state.last_ai_analysis_at,
            run_count=state.run_count + 1,
            last_scanned_message_count=len(messages),
            last_new_message_count=len(new_messages),
            total_new_message_count=(
                state.total_new_message_count + len(new_messages)
            ),
            last_proposed_fact_count=proposed_fact_count,
            total_proposed_fact_count=(
                state.total_proposed_fact_count + proposed_fact_count
            ),
            last_rejected_message_count=rejection_count,
            recent_source_hashes=_recent_hashes(
                messages, state.recent_source_hashes
            ),
            error_code=None,
        )
        updated_bootstrap = snapshot_with_incremental_delta(
            snapshot=bootstrap,
            inbound_delta=inbound_delta,
            outbound_delta=outbound_delta,
            workflow_delta=workflow_delta,
            candidate_delta=candidate_delta,
            proposed_fact_delta=proposed_fact_count,
        )
        if incremental_repository.store is bootstrap_repository.store:
            with incremental_repository.store.transaction():
                bootstrap_repository.save(updated_bootstrap)
                incremental_repository.save(completed)
        else:
            bootstrap_repository.save(updated_bootstrap)
            incremental_repository.save(completed)

        return {
            "status": completed.status,
            "scanned_message_count": len(messages),
            "new_message_count": len(new_messages),
            "inbound_new_message_count": inbound_delta,
            "outbound_new_message_count": outbound_delta,
            "proposed_fact_count": proposed_fact_count,
            "ai_analysis_performed": run_ai,
            "relationship_analysis": relationship_payload,
            "raw_messages_persisted": False,
        }
    finally:
        messages.clear()


def run_outlook_incremental_agency_learning(
    *,
    config: MicrosoftAuthConfig,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    bootstrap_repository: SQLiteAgencyLearningBootstrapRepository,
    incremental_repository: SQLiteAgencyIncrementalLearningRepository,
    token_provider=acquire_silent_access_token,
    graph_client_factory=OutlookGraphReadClient,
    **kwargs,
) -> dict[str, Any]:
    token = token_provider(config)
    client = graph_client_factory(
        access_token=token,
        mailbox_id=config.mailbox_id,
    )
    return run_incremental_agency_learning(
        client=client,
        provider="outlook",
        mailbox_id=config.mailbox_id,
        master_repository=master_repository,
        learning_repository=learning_repository,
        bootstrap_repository=bootstrap_repository,
        incremental_repository=incremental_repository,
        **kwargs,
    )


def run_imap_incremental_agency_learning(
    *,
    credential: ImapMailboxCredential,
    master_repository: MasterDataRepository,
    learning_repository: LearningFactRepository,
    bootstrap_repository: SQLiteAgencyLearningBootstrapRepository,
    incremental_repository: SQLiteAgencyIncrementalLearningRepository,
    client_factory=ImapReadClient,
    **kwargs,
) -> dict[str, Any]:
    client = client_factory(credential=credential)
    return run_incremental_agency_learning(
        client=client,
        provider="imap",
        mailbox_id=credential.mailbox_id,
        master_repository=master_repository,
        learning_repository=learning_repository,
        bootstrap_repository=bootstrap_repository,
        incremental_repository=incremental_repository,
        **kwargs,
    )
