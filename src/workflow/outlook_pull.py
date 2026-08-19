from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.ai.email_parser import (
    EmailParserUnavailableError,
)
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.operational_data import (
    OperationalDataSources,
)
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    acquire_silent_access_token,
)
from src.integrations.outlook_graph import (
    GRAPH_PROVIDER_NAME,
    OutlookGraphReadClient,
)
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
)
from src.workflow.outlook_inbound_ingestion import (
    process_controlled_outlook_customer_mail,
)


def _safe_result_summary(
    mail,
    result: dict,
) -> dict:
    proposal = result.get(
        "extraction_proposal"
    )

    proposal_id = None

    if proposal is not None:
        proposal_id = getattr(
            proposal,
            "proposal_id",
            None,
        )

        if (
            proposal_id is None
            and isinstance(proposal, dict)
        ):
            proposal_id = proposal.get(
                "proposal_id"
            )

    summary = {
        "external_message_id": (
            mail.external_message_id
        ),
        "received_at": (
            mail.received_at.isoformat()
            if mail.received_at is not None
            else None
        ),
        "result_type": str(
            result.get("result_type")
            or "unknown"
        ),
        "ingestion_status": result.get(
            "ingestion_status"
        ),
        "reason_code": result.get(
            "reason_code"
        ),
        "proposal_id": proposal_id,
    }

    return {
        key: value
        for key, value in summary.items()
        if value is not None
    }


def pull_controlled_outlook_inbox(
    *,
    config: MicrosoftAuthConfig,
    limit: int,
    shipment_parser,
    proposal_repository: (
        ExtractionProposalRepository
    ),
    operational_data_sources: (
        OperationalDataSources | None
    ),
    token_provider: Callable[
        [MicrosoftAuthConfig],
        str,
    ] = acquire_silent_access_token,
    graph_client_factory: Callable[
        ..., Any
    ] = OutlookGraphReadClient,
    inbound_processor: Callable[
        ..., dict
    ] = process_controlled_outlook_customer_mail,
) -> dict:
    access_token = token_provider(
        config
    )

    graph_client = graph_client_factory(
        access_token=access_token,
        mailbox_id=config.mailbox_id,
    )

    mails = graph_client.list_inbox_messages(
        limit=limit
    )

    summaries: list[dict] = []
    parser_unavailable = False

    for mail in mails:
        try:
            result = inbound_processor(
                mail=mail,
                shipment_parser=shipment_parser,
                proposal_repository=(
                    proposal_repository
                ),
                operational_data_sources=(
                    operational_data_sources
                ),
            )

        except (
            InboundMailIdempotencyConflictError
        ):
            result = {
                "result_type": (
                    "inbound_mail_rejected"
                ),
                "ingestion_status": "blocked",
                "reason_code": (
                    "inbound_message_id_conflict"
                ),
                "extraction_proposal": None,
            }

        except EmailParserUnavailableError:
            result = {
                "result_type": (
                    "email_parser_unavailable"
                ),
                "ingestion_status": "blocked",
                "reason_code": (
                    "email_parser_unavailable"
                ),
                "extraction_proposal": None,
            }
            parser_unavailable = True

        summaries.append(
            _safe_result_summary(
                mail,
                result,
            )
        )

        if parser_unavailable:
            break

    proposal_count = sum(
        1
        for item in summaries
        if item.get("proposal_id")
    )

    return {
        "provider": GRAPH_PROVIDER_NAME,
        "mailbox_id": config.mailbox_id,
        "requested_limit": limit,
        "fetched_message_count": len(mails),
        "handled_message_count": (
            len(summaries)
        ),
        "proposal_count": proposal_count,
        "pull_status": (
            "partial_parser_unavailable"
            if parser_unavailable
            else "complete"
        ),
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "results": summaries,
    }
