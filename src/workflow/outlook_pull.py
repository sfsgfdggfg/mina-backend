from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.ai.email_parser import (
    EmailParserUnavailableError,
)
from src.ai.supplier_response_parser import (
    SupplierResponseParserUnavailableError,
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
    OutlookGraphMessageRejection,
    OutlookGraphReadClient,
)
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
)
from src.workflow.outlook_inbound_router import (
    process_controlled_outlook_inbound_mail,
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
        "inbound_route": result.get(
            "inbound_route"
        ),
        "rfq_id": result.get(
            "rfq_id"
        ),
        "correlation_method": result.get(
            "correlation_method"
        ),
        "proposal_id": proposal_id,
        "attachment_intake_status": result.get(
            "attachment_intake_status"
        ),
        "attachment_intake_reason_code": result.get(
            "attachment_intake_reason_code"
        ),
        "attachment_count": result.get(
            "attachment_count"
        ),
        "attachment_total_size_bytes": result.get(
            "attachment_total_size_bytes"
        ),
        "attachment_retrieval_status": result.get(
            "attachment_retrieval_status"
        ),
        "attachment_retrieval_reason_code": result.get(
            "attachment_retrieval_reason_code"
        ),
        "attachment_content_download_performed": result.get(
            "attachment_content_download_performed"
        ),
        "attachment_verified_count": result.get(
            "attachment_verified_count"
        ),
    }

    return {
        key: value
        for key, value in summary.items()
        if value is not None
    }


def _safe_rejection_summary(
    rejection: OutlookGraphMessageRejection,
) -> dict:
    return {
        "external_message_id": (
            rejection.external_message_id
        ),
        "received_at": rejection.received_at,
        "result_type": "inbound_message_rejected",
        "ingestion_status": "blocked",
        "reason_code": rejection.reason_code,
        "inbound_route": "manual_review",
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
    supplier_parser=None,
    supplier_repository=None,
    token_provider: Callable[
        [MicrosoftAuthConfig],
        str,
    ] = acquire_silent_access_token,
    graph_client_factory: Callable[
        ..., Any
    ] = OutlookGraphReadClient,
    inbound_processor: Callable[
        ..., dict
    ] = process_controlled_outlook_inbound_mail,
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
    rejections = list(
        getattr(
            graph_client,
            "last_message_rejections",
            (),
        )
    )

    summaries: list[dict] = [
        _safe_rejection_summary(rejection)
        for rejection in rejections
    ]
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
                supplier_parser=(
                    supplier_parser
                ),
                supplier_repository=(
                    supplier_repository
                ),
                attachment_retriever=getattr(
                    graph_client,
                    "retrieve_allowlisted_attachments",
                    None,
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

        except SupplierResponseParserUnavailableError:
            result = {
                "result_type": (
                    "supplier_response_parser_unavailable"
                ),
                "ingestion_status": "blocked",
                "reason_code": (
                    "supplier_response_parser_unavailable"
                ),
                "inbound_route": "supplier",
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

    supplier_response_count = sum(
        1
        for item in summaries
        if (
            item.get("inbound_route")
            == "supplier"
            and item.get(
                "ingestion_status"
            )
            == "response_attached"
        )
    )

    manual_review_count = sum(
        1
        for item in summaries
        if (
            item.get("inbound_route") == "manual_review"
            or item.get("result_type")
            == "inbound_mail_manual_review_required"
        )
    )

    return {
        "provider": GRAPH_PROVIDER_NAME,
        "mailbox_id": config.mailbox_id,
        "requested_limit": limit,
        "fetched_message_count": (
            len(mails) + len(rejections)
        ),
        "handled_message_count": (
            len(summaries)
        ),
        "proposal_count": proposal_count,
        "supplier_response_count": (
            supplier_response_count
        ),
        "manual_review_count": (
            manual_review_count
        ),
        "pull_status": (
            "partial_parser_unavailable"
            if parser_unavailable
            else "complete"
        ),
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "results": summaries,
    }
