from __future__ import annotations

from collections.abc import Callable

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
        result = _blocked_result(
            result_type=(
                "inbound_mail_manual_review_required"
            ),
            reason_code=(
                "outlook_attachments_not_supported"
            ),
        )
        result.update({
            "attachment_intake_status": assessment.status,
            "attachment_intake_reason_code": assessment.reason_code,
            "attachment_count": assessment.attachment_count,
            "attachment_total_size_bytes": assessment.total_size_bytes,
        })
        return result

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
