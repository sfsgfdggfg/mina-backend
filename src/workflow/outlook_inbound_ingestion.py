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
from src.workflow.mail_ingestion import (
    process_customer_inquiry_mail,
)


OUTLOOK_GRAPH_PROVIDER = "microsoft_graph"


def _blocked_result(
    *,
    result_type: str,
    reason_code: str,
) -> dict:
    return {
        "result_type": result_type,
        "ingestion_status": "blocked",
        "reason_code": reason_code,
        "inbound_gate_status": "blocked",
        "extraction_proposal": None,
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


def process_controlled_outlook_customer_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[
        [PrivacySafeText],
        ShipmentProposalSnapshot,
    ],
    proposal_repository: ExtractionProposalRepository,
    operational_data_sources: (
        OperationalDataSources | None
    ),
) -> dict:
    """Gate real Outlook mail before AI extraction."""

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

    if operational_data_sources is None:
        return _blocked_result(
            result_type="data_provenance_blocked",
            reason_code=(
                "pilot_customer_data_unavailable"
            ),
        )

    try:
        profiles = load_customer_memory(
            operational_data_sources
        )
    except DataProvenanceError:
        return _blocked_result(
            result_type="data_provenance_blocked",
            reason_code=(
                "pilot_customer_data_unverified"
            ),
        )

    matches = [
        profile
        for profile in profiles
        if profile.active
        and sender_matches_profile(
            profile,
            mail.sender_address,
        )
    ]

    if not matches:
        return _blocked_result(
            result_type=(
                "inbound_sender_verification_required"
            ),
            reason_code=(
                "sender_not_in_verified_pilot_scope"
            ),
        )

    if len(matches) != 1:
        return _blocked_result(
            result_type=(
                "inbound_sender_verification_required"
            ),
            reason_code=(
                "sender_matches_multiple_pilot_customers"
            ),
        )

    result = process_customer_inquiry_mail(
        mail=mail,
        shipment_parser=shipment_parser,
        proposal_repository=proposal_repository,
        trusted_customer_name=matches[0].customer_name,
    )

    result["inbound_gate_status"] = "pass"
    result["inbound_gate_reason"] = (
        "trusted_pilot_sender"
    )

    return result
