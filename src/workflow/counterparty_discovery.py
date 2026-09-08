from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable

from src.core.counterparty_discovery import discover_historical_counterparties
from src.core.master_data_repository import MasterDataRepository
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    OUTLOOK_BASIC_READ_SCOPES,
    acquire_silent_access_token,
)
from src.integrations.outlook_graph import (
    MAX_COUNTERPARTY_DISCOVERY_DAYS,
    MAX_HISTORY_MESSAGES,
    MIN_COUNTERPARTY_DISCOVERY_MESSAGES,
    OutlookGraphReadClient,
)


class CounterpartyDiscoveryAuthorizationError(PermissionError):
    pass


def run_outlook_counterparty_discovery(
    *,
    config: MicrosoftAuthConfig,
    start_at: datetime,
    end_at: datetime,
    max_messages: int,
    authorization_confirmed: bool,
    master_repository: MasterDataRepository,
    agency_addresses: list[str] | None = None,
    token_provider: Callable[[MicrosoftAuthConfig], str] = acquire_silent_access_token,
    graph_client_factory: Callable[..., Any] = OutlookGraphReadClient,
) -> dict[str, Any]:
    if authorization_confirmed is not True:
        raise CounterpartyDiscoveryAuthorizationError(
            "Historical counterparty discovery requires explicit operator authorization."
        )
    if tuple(config.scopes) != OUTLOOK_BASIC_READ_SCOPES:
        raise MicrosoftAuthConfigurationError(
            "Historical counterparty discovery requires Outlook Mail.ReadBasic only."
        )
    if start_at.tzinfo is None or end_at.tzinfo is None:
        raise ValueError("Counterparty discovery timestamps must be timezone-aware.")
    if end_at <= start_at:
        raise ValueError("Counterparty discovery end_at must be after start_at.")
    if end_at - start_at > timedelta(days=MAX_COUNTERPARTY_DISCOVERY_DAYS):
        raise ValueError(
            "Counterparty discovery history window cannot exceed "
            f"{MAX_COUNTERPARTY_DISCOVERY_DAYS} days."
        )
    if (
        isinstance(max_messages, bool)
        or not isinstance(max_messages, int)
        or not (MIN_COUNTERPARTY_DISCOVERY_MESSAGES <= max_messages <= MAX_HISTORY_MESSAGES)
    ):
        raise ValueError(
            "Counterparty discovery max_messages must be between "
            f"{MIN_COUNTERPARTY_DISCOVERY_MESSAGES} and {MAX_HISTORY_MESSAGES}."
        )

    access_token = token_provider(config)
    client = graph_client_factory(
        access_token=access_token,
        mailbox_id=config.mailbox_id,
    )
    messages = client.list_counterparty_discovery_history(
        start_at=start_at,
        end_at=end_at,
        max_messages=max_messages,
    )
    try:
        result = discover_historical_counterparties(
            messages=messages,
            agency_addresses=list(
                dict.fromkeys([config.mailbox_id, *(agency_addresses or [])])
            ),
            master_repository=master_repository,
        )
        payload = result.model_dump()
        payload.update(
            {
                "source": "authorized_outlook_counterparty_discovery",
                "mailbox_message_rejection_count": len(
                    getattr(client, "last_message_rejections", ())
                ),
                "history_start_at": start_at,
                "history_end_at": end_at,
                "max_messages": max_messages,
                "history_scan": dict(
                    getattr(client, "last_counterparty_discovery_scan", {}) or {}
                ),
                "raw_messages_persisted": False,
                "master_data_mutated": False,
            }
        )
        return payload
    finally:
        messages.clear()
