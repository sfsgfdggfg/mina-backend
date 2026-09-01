from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.attachment_safe_extraction import SafeAttachmentExtractionArtifact
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.privacy import PrivacyBoundaryError, prepare_privacy_safe_source_bundle
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.ai.email_parser import EmailParserUnavailableError
from src.ai.supplier_response_parser import SupplierResponseParserUnavailableError

MAX_ATTACHMENT_INTERPRETATION_INPUT_CHARS = 120_000
AttachmentInterpretationRoute = Literal["customer", "supplier"]
AttachmentInterpretationStatus = Literal["interpreted", "manual_review"]


class AttachmentInterpretationResult(BaseModel):
    """Safe interpretation evidence; parsed payloads are internal and non-authoritative."""

    model_config = ConfigDict(extra="forbid")

    status: AttachmentInterpretationStatus
    reason_code: str = Field(min_length=1, max_length=128)
    route: AttachmentInterpretationRoute
    parser_called: bool = False
    source_attachment_count: int = Field(ge=0)
    source_character_count: int = Field(ge=0)
    source_table_count: int = Field(ge=0)
    privacy_transform_version: str | None = None
    source_profiles: list[Literal["pdf", "xlsx", "csv"]] = Field(default_factory=list)
    customer_proposal: ShipmentProposalSnapshot | None = Field(default=None, exclude=True, repr=False)
    supplier_extraction: SupplierResponseExtraction | None = Field(default=None, exclude=True, repr=False)


def _manual_result(*, route, reason_code, artifacts, parser_called=False):
    return AttachmentInterpretationResult(
        status="manual_review",
        reason_code=reason_code,
        route=route,
        parser_called=parser_called,
        source_attachment_count=len(artifacts),
        source_character_count=sum(item.character_count for item in artifacts),
        source_table_count=sum(item.table_count for item in artifacts),
        source_profiles=[item.content_profile for item in artifacts],
    )


def _artifact_text(index: int, artifact: SafeAttachmentExtractionArtifact) -> tuple[str, str]:
    label = f"ATTACHMENT_{index}_{artifact.content_profile.upper()}"
    if artifact.extraction_kind == "text":
        return label, artifact.text or ""
    payload = [
        {"table": table.name, "rows": table.rows}
        for table in artifact.tables
    ]
    return label, json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def build_attachment_interpretation_sections(
    mail: InboundMailEnvelope,
    artifacts: list[SafeAttachmentExtractionArtifact],
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    if mail.subject:
        sections.append(("EMAIL_SUBJECT", mail.subject))
    if mail.body_text.strip():
        sections.append(("EMAIL_BODY", mail.body_text))
    sections.extend(_artifact_text(index, artifact) for index, artifact in enumerate(artifacts, start=1))
    raw_size = len("\n\n".join(
        f"--- {label} ---\n{text}" for label, text in sections
    ))
    if raw_size > MAX_ATTACHMENT_INTERPRETATION_INPUT_CHARS:
        raise PrivacyBoundaryError("Attachment interpretation input exceeds limit.")
    return sections


def interpret_extracted_attachment_mail(
    *,
    mail: InboundMailEnvelope,
    artifacts: list[SafeAttachmentExtractionArtifact],
    route: AttachmentInterpretationRoute,
    shipment_parser: Any,
    supplier_parser: Any,
) -> AttachmentInterpretationResult:
    if not artifacts:
        return _manual_result(route=route, reason_code="attachment_interpretation_no_artifacts", artifacts=artifacts)
    if route == "supplier" and supplier_parser is None:
        return _manual_result(route=route, reason_code="attachment_supplier_parser_not_available", artifacts=artifacts)
    try:
        sections = build_attachment_interpretation_sections(mail, artifacts)
        transformed = prepare_privacy_safe_source_bundle(sections)
    except PrivacyBoundaryError:
        return _manual_result(route=route, reason_code="attachment_interpretation_privacy_or_size_block", artifacts=artifacts)

    if route == "customer":
        try:
            parsed = shipment_parser(transformed.safe_text)
            proposal = ShipmentProposalSnapshot.model_validate(parsed)
        except EmailParserUnavailableError:
            raise
        except Exception:
            return _manual_result(
                route=route, reason_code="attachment_customer_interpretation_failed",
                artifacts=artifacts, parser_called=True,
            )
        return AttachmentInterpretationResult(
            status="interpreted", reason_code="attachment_customer_interpretation_proposed", route=route,
            parser_called=True, source_attachment_count=len(artifacts),
            source_character_count=sum(item.character_count for item in artifacts),
            source_table_count=sum(item.table_count for item in artifacts),
            privacy_transform_version=transformed.transform_version,
            source_profiles=[item.content_profile for item in artifacts], customer_proposal=proposal,
        )

    try:
        parsed = supplier_parser.parse(transformed.safe_text)
        extraction = SupplierResponseExtraction.model_validate(parsed)
    except SupplierResponseParserUnavailableError:
        raise
    except Exception:
        return _manual_result(
            route=route, reason_code="attachment_supplier_interpretation_failed",
            artifacts=artifacts, parser_called=True,
        )
    return AttachmentInterpretationResult(
        status="interpreted", reason_code="attachment_supplier_interpretation_proposed", route=route,
        parser_called=True, source_attachment_count=len(artifacts),
        source_character_count=sum(item.character_count for item in artifacts),
        source_table_count=sum(item.table_count for item in artifacts),
        privacy_transform_version=transformed.transform_version,
        source_profiles=[item.content_profile for item in artifacts], supplier_extraction=extraction,
    )
