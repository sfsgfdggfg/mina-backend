from __future__ import annotations

from src.ai.email_parser import EmailParserUnavailableError
from src.ai.supplier_response_parser import SupplierResponseParserUnavailableError
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.operational_data import OperationalDataSources
from src.integrations.imap_mail import IMAP_PROVIDER_NAME, ImapReadClient
from src.integrations.mailbox_credentials import ImapMailboxCredential
from src.workflow.mail_ingestion import InboundMailIdempotencyConflictError
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail
from src.workflow.outlook_pull import _safe_rejection_summary, _safe_result_summary


def pull_controlled_imap_inbox(
    *,
    credential: ImapMailboxCredential,
    limit: int,
    shipment_parser,
    proposal_repository: ExtractionProposalRepository,
    operational_data_sources: OperationalDataSources | None,
    master_data_repository=None,
    supplier_parser=None,
    supplier_repository=None,
    attachment_review_repository=None,
    supplier_operational_repository=None,
    mina_job_repository=None,
    interpret_attachments: bool = False,
    client_factory=ImapReadClient,
    inbound_processor=process_controlled_outlook_inbound_mail,
) -> dict:
    client = client_factory(credential=credential)
    mails = client.list_inbox_messages(limit=limit)
    rejections = list(getattr(client, "last_message_rejections", ()))
    summaries: list[dict] = [
        _safe_rejection_summary(rejection) for rejection in rejections
    ]
    parser_unavailable = False

    for mail in mails:
        try:
            result = inbound_processor(
                mail=mail,
                shipment_parser=shipment_parser,
                proposal_repository=proposal_repository,
                operational_data_sources=operational_data_sources,
                master_data_repository=master_data_repository,
                supplier_parser=supplier_parser,
                supplier_repository=supplier_repository,
                attachment_retriever=None,
                # IMAP P1 reads attachment metadata only. Content retrieval is
                # intentionally unavailable and therefore remains manual-review.
                attachment_interpreter=None,
                attachment_review_repository=None,
                supplier_operational_repository=supplier_operational_repository,
                mina_job_repository=mina_job_repository,
            )
        except InboundMailIdempotencyConflictError:
            result = {
                "result_type": "inbound_mail_rejected",
                "ingestion_status": "blocked",
                "reason_code": "inbound_message_id_conflict",
                "extraction_proposal": None,
            }
        except EmailParserUnavailableError:
            result = {
                "result_type": "email_parser_unavailable",
                "ingestion_status": "blocked",
                "reason_code": "email_parser_unavailable",
                "extraction_proposal": None,
            }
            parser_unavailable = True
        except SupplierResponseParserUnavailableError:
            result = {
                "result_type": "supplier_response_parser_unavailable",
                "ingestion_status": "blocked",
                "reason_code": "supplier_response_parser_unavailable",
                "inbound_route": "supplier",
                "extraction_proposal": None,
            }
            parser_unavailable = True

        summaries.append(_safe_result_summary(mail, result))
        if parser_unavailable:
            break

    proposal_count = sum(1 for item in summaries if item.get("proposal_id"))
    supplier_response_count = sum(
        1
        for item in summaries
        if item.get("inbound_route") == "supplier"
        and item.get("ingestion_status") == "response_attached"
    )
    manual_review_count = sum(
        1
        for item in summaries
        if item.get("inbound_route") == "manual_review"
        or item.get("result_type") == "inbound_mail_manual_review_required"
        or item.get("ingestion_status") == "review_required"
    )
    supplier_operational_count = sum(
        1
        for item in summaries
        if item.get("result_type") == "supplier_operational_notification"
    )
    attachment_review_count = sum(
        1 for item in summaries if item.get("attachment_review_id")
    )

    return {
        "provider": IMAP_PROVIDER_NAME,
        "mailbox_id": credential.mailbox_id,
        "requested_limit": limit,
        "fetched_message_count": len(mails) + len(rejections),
        "handled_message_count": len(summaries),
        "proposal_count": proposal_count,
        "supplier_response_count": supplier_response_count,
        "manual_review_count": manual_review_count,
        "supplier_operational_count": supplier_operational_count,
        "attachment_review_count": attachment_review_count,
        "pull_status": (
            "partial_parser_unavailable" if parser_unavailable else "complete"
        ),
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "attachment_interpretation_requested": interpret_attachments,
        "attachment_content_retrieval_supported": False,
        "results": summaries,
    }
