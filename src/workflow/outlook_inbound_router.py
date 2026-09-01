from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.core.attachment_intake_policy import (
    assess_attachment_intake,
)
from src.core.customer_memory import (
    load_customer_memory,
    sender_matches_profile,
)
from src.core.data_provenance import (
    DataProvenanceError,
)
from src.core.extraction_confirmation import (
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    ExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.operational_data import (
    OperationalDataSources,
)
from src.core.privacy import PrivacySafeText
from src.core.supplier_response_ingestion import (
    correlate_supplier_reply,
)
from src.core.supplier_rfq_repository import (
    SupplierRFQRepository,
)
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
    existing_proposal_for_mail,
)
from src.workflow.outlook_inbound_ingestion import (
    OUTLOOK_GRAPH_PROVIDER,
    process_controlled_outlook_customer_mail,
)
from src.workflow.supplier_response_ingestion import (
    ingest_supplier_reply,
    supplier_message_is_exact_replay,
)


def _blocked_result(
    *,
    result_type: str,
    reason_code: str,
) -> dict:
    return {
        "result_type": result_type,
        "ingestion_status": "blocked",
        "reason_code": reason_code,
        "inbound_route": "manual_review",
        "extraction_proposal": None,
        "supplier_response": None,
    }


def _provider_metadata_valid(
    mail: InboundMailEnvelope,
) -> bool:
    return bool(
        mail.source == "email"
        and mail.provider_name
        == OUTLOOK_GRAPH_PROVIDER
        and mail.external_message_id
        and mail.mailbox_id
        and mail.sender_address
        and mail.received_at is not None
        and not mail.privacy_transformed
        and mail.raw_body_sha256 is None
        and mail.privacy_transform_version is None
    )


def _customer_matches(
    *,
    mail: InboundMailEnvelope,
    operational_data_sources: (
        OperationalDataSources | None
    ),
):
    if operational_data_sources is None:
        return None, "pilot_customer_data_unavailable"

    try:
        profiles = load_customer_memory(
            operational_data_sources
        )
    except DataProvenanceError:
        return None, "pilot_customer_data_unverified"

    matches = [
        profile
        for profile in profiles
        if profile.active
        and sender_matches_profile(
            profile,
            mail.sender_address,
        )
    ]

    return matches, None


def _with_attachment_intake(
    result: dict,
    assessment,
) -> dict:
    result.update({
        "attachment_intake_status": assessment.status,
        "attachment_intake_reason_code": assessment.reason_code,
        "attachment_count": assessment.attachment_count,
        "attachment_total_size_bytes": assessment.total_size_bytes,
    })
    return result


def _process_allowlisted_attachment_mail(
    *,
    mail: InboundMailEnvelope,
    assessment,
    supplier_repository: SupplierRFQRepository,
    operational_data_sources: OperationalDataSources | None,
    attachment_retriever: Callable[[InboundMailEnvelope], Any] | None,
) -> dict:
    customer_matches, customer_error = _customer_matches(
        mail=mail,
        operational_data_sources=operational_data_sources,
    )
    if customer_error is not None:
        return _with_attachment_intake(
            _blocked_result(
                result_type="data_provenance_blocked",
                reason_code=customer_error,
            ),
            assessment,
        )

    supplier_correlation = correlate_supplier_reply(
        mail,
        supplier_repository,
    )
    customer_count = len(customer_matches or [])
    supplier_matched = supplier_correlation.status == "matched"

    if customer_count > 1:
        return _with_attachment_intake(
            _blocked_result(
                result_type="inbound_sender_verification_required",
                reason_code="sender_matches_multiple_pilot_customers",
            ),
            assessment,
        )
    if customer_count == 1 and supplier_matched:
        return _with_attachment_intake(
            _blocked_result(
                result_type="inbound_mail_manual_review_required",
                reason_code="sender_matches_customer_and_supplier",
            ),
            assessment,
        )
    if supplier_correlation.status == "ambiguous_rfq":
        return _with_attachment_intake(
            _blocked_result(
                result_type="inbound_mail_manual_review_required",
                reason_code="supplier_rfq_correlation_ambiguous",
            ),
            assessment,
        )

    if supplier_matched:
        trusted_route = "supplier"
    elif customer_count == 1:
        trusted_route = "customer"
    else:
        return _with_attachment_intake(
            _blocked_result(
                result_type="inbound_sender_verification_required",
                reason_code="sender_not_in_verified_inbound_scope",
            ),
            assessment,
        )

    result = _blocked_result(
        result_type="inbound_mail_manual_review_required",
        reason_code="outlook_attachment_retrieval_not_available",
    )
    result["inbound_route"] = trusted_route
    if supplier_matched:
        result["rfq_id"] = supplier_correlation.rfq_id
        result["correlation_method"] = supplier_correlation.method

    if attachment_retriever is None:
        result.update({
            "attachment_retrieval_status": "manual_review",
            "attachment_retrieval_reason_code": "attachment_retrieval_not_available",
            "attachment_content_download_performed": False,
            "attachment_verified_count": 0,
        })
        return _with_attachment_intake(result, assessment)

    retrieval = attachment_retriever(mail)
    artifacts = list(getattr(retrieval, "extracted_artifacts", ()))
    extraction_attempted = bool(
        getattr(retrieval, "extraction_attempted", False)
    )
    if retrieval.status == "verified" and artifacts:
        result["reason_code"] = "outlook_attachment_content_extracted_not_interpreted"
        extraction_status = "extracted"
        extraction_reason_code = "attachment_safe_extraction_complete"
    elif retrieval.status == "verified":
        result["reason_code"] = "outlook_attachment_content_verified_not_parsed"
        extraction_status = "not_attempted"
        extraction_reason_code = "attachment_safe_extraction_not_attempted"
    else:
        result["reason_code"] = "outlook_attachment_retrieval_manual_review"
        extraction_status = "manual_review" if extraction_attempted else "not_attempted"
        extraction_reason_code = (
            retrieval.reason_code
            if extraction_attempted
            else "attachment_safe_extraction_not_attempted"
        )
    result.update({
        "attachment_retrieval_status": retrieval.status,
        "attachment_retrieval_reason_code": retrieval.reason_code,
        "attachment_content_download_performed": retrieval.content_download_performed,
        "attachment_verified_count": len(retrieval.verified_receipts),
        "attachment_extraction_status": extraction_status,
        "attachment_extraction_reason_code": extraction_reason_code,
        "attachment_extracted_count": len(artifacts),
        "attachment_extracted_character_count": sum(
            artifact.character_count for artifact in artifacts
        ),
        "attachment_extracted_table_count": sum(
            artifact.table_count for artifact in artifacts
        ),
        "attachment_extraction_artifacts": artifacts,
    })
    return _with_attachment_intake(result, assessment)


def process_controlled_outlook_inbound_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[
        [PrivacySafeText],
        ShipmentProposalSnapshot,
    ],
    supplier_parser,
    proposal_repository: (
        ExtractionProposalRepository
    ),
    supplier_repository: SupplierRFQRepository,
    operational_data_sources: (
        OperationalDataSources | None
    ),
    attachment_retriever: (
        Callable[[InboundMailEnvelope], Any] | None
    ) = None,
) -> dict:
    """Route Outlook mail deterministically before any AI parser."""

    if not _provider_metadata_valid(mail):
        return _blocked_result(
            result_type="inbound_mail_rejected",
            reason_code=(
                "outlook_provider_metadata_invalid"
            ),
        )

    if mail.has_attachments:
        assessment = assess_attachment_intake(mail)
        if assessment.status != "metadata_allowlisted":
            return _with_attachment_intake(
                _blocked_result(
                    result_type="inbound_mail_manual_review_required",
                    reason_code="outlook_attachments_not_supported",
                ),
                assessment,
            )
        return _process_allowlisted_attachment_mail(
            mail=mail,
            assessment=assessment,
            supplier_repository=supplier_repository,
            operational_data_sources=operational_data_sources,
            attachment_retriever=attachment_retriever,
        )

    supplier_replay = (
        supplier_message_is_exact_replay(
            reply=mail,
            repository=supplier_repository,
        )
    )

    existing_customer_proposal = (
        existing_proposal_for_mail(
            mail=mail,
            repository=proposal_repository,
        )
    )

    if (
        supplier_replay
        and existing_customer_proposal
        is not None
    ):
        raise InboundMailIdempotencyConflictError(
            "Inbound message has conflicting "
            "prior route history."
        )

    if supplier_replay:
        return {
            "result_type": (
                "supplier_response_duplicate"
            ),
            "ingestion_status": (
                "duplicate_response"
            ),
            "reason_code": (
                "supplier_message_already_ingested"
            ),
            "inbound_route": "supplier",
            "extraction_proposal": None,
            "supplier_response": None,
        }

    if existing_customer_proposal is not None:
        return {
            "result_type": (
                "extraction_confirmation_required"
            ),
            "ingestion_status": (
                "duplicate_existing_proposal"
            ),
            "reason_code": (
                "customer_message_already_ingested"
            ),
            "inbound_route": "customer",
            "extraction_proposal": (
                existing_customer_proposal
            ),
            "supplier_response": None,
        }

    customer_matches, customer_error = (
        _customer_matches(
            mail=mail,
            operational_data_sources=(
                operational_data_sources
            ),
        )
    )

    if customer_error is not None:
        return _blocked_result(
            result_type="data_provenance_blocked",
            reason_code=customer_error,
        )

    supplier_correlation = (
        correlate_supplier_reply(
            mail,
            supplier_repository,
        )
    )

    customer_count = len(
        customer_matches or []
    )

    supplier_matched = (
        supplier_correlation.status
        == "matched"
    )

    if customer_count > 1:
        return _blocked_result(
            result_type=(
                "inbound_sender_verification_required"
            ),
            reason_code=(
                "sender_matches_multiple_pilot_customers"
            ),
        )

    if customer_count == 1 and supplier_matched:
        return _blocked_result(
            result_type=(
                "inbound_mail_manual_review_required"
            ),
            reason_code=(
                "sender_matches_customer_and_supplier"
            ),
        )

    if supplier_matched:
        supplier_result = ingest_supplier_reply(
            reply=mail,
            repository=supplier_repository,
            parser=supplier_parser,
        )

        return {
            "result_type": (
                "supplier_response_ingestion"
            ),
            "ingestion_status": (
                supplier_result.status
            ),
            "reason_code": (
                supplier_result.status
            ),
            "inbound_route": "supplier",
            "rfq_id": supplier_result.rfq_id,
            "correlation_method": (
                supplier_result.correlation_method
            ),
            "supplier_response": (
                supplier_result.response
            ),
            "supplier_rfq": (
                supplier_result.supplier_rfq
            ),
            "extraction_proposal": None,
        }

    if customer_count == 1:
        customer_result = (
            process_controlled_outlook_customer_mail(
                mail=mail,
                shipment_parser=shipment_parser,
                proposal_repository=(
                    proposal_repository
                ),
                operational_data_sources=(
                    operational_data_sources
                ),
            )
        )

        customer_result[
            "inbound_route"
        ] = "customer"

        customer_result[
            "supplier_response"
        ] = None

        return customer_result

    if supplier_correlation.status == (
        "ambiguous_rfq"
    ):
        return _blocked_result(
            result_type=(
                "inbound_mail_manual_review_required"
            ),
            reason_code=(
                "supplier_rfq_correlation_ambiguous"
            ),
        )

    return _blocked_result(
        result_type=(
            "inbound_sender_verification_required"
        ),
        reason_code=(
            "sender_not_in_verified_inbound_scope"
        ),
    )
