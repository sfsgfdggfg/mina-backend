from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.relationship_history import (
    RelationshipHistoryAIAnalyzer,
    analyze_relationship_history,
)
from src.integrations.microsoft_auth import MicrosoftAuthConfig, acquire_silent_access_token
from src.integrations.outlook_graph import OutlookGraphReadClient


class RelationshipOnboardingAuthorizationError(PermissionError):
    pass


def run_outlook_relationship_onboarding(
    *, config: MicrosoftAuthConfig, start_at: datetime, end_at: datetime,
    max_messages: int, authorization_confirmed: bool,
    master_repository: MasterDataRepository, learning_repository: LearningFactRepository,
    created_by: str, ai_analyzer: RelationshipHistoryAIAnalyzer | None = None,
    agency_addresses: list[str] | None = None,
    token_provider: Callable[[MicrosoftAuthConfig], str] = acquire_silent_access_token,
    graph_client_factory: Callable[..., Any] = OutlookGraphReadClient,
) -> dict:
    if authorization_confirmed is not True:
        raise RelationshipOnboardingAuthorizationError(
            "Historical mailbox onboarding requires explicit operator authorization confirmation."
        )
    access_token = token_provider(config)
    client = graph_client_factory(access_token=access_token, mailbox_id=config.mailbox_id)
    messages = client.list_relationship_history(
        start_at=start_at, end_at=end_at, max_messages=max_messages,
    )
    try:
        result = analyze_relationship_history(
            messages=messages,
            agency_addresses=list(dict.fromkeys([config.mailbox_id, *(agency_addresses or [])])),
            master_repository=master_repository, learning_repository=learning_repository,
            created_by=created_by, ai_analyzer=ai_analyzer,
        )
        payload = result.model_dump()
        payload.update({
            "source": "authorized_outlook_history",
            "mailbox_message_rejection_count": len(getattr(client, "last_message_rejections", ())),
            "history_start_at": start_at,
            "history_end_at": end_at,
            "max_messages": max_messages,
            "ai_analysis_requested": ai_analyzer is not None,
            "raw_messages_persisted": False,
        })
        return payload
    finally:
        # Keep raw historical bodies transient even if a downstream analyzer fails.
        messages.clear()
