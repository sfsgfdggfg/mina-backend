from __future__ import annotations

from datetime import date
from typing import Optional

from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_shadow import AirCargoScope, AirRateSource
from src.core.air_shadow_repository import AirShadowRepository
from src.core.attachment_content_verification import (
    AttachmentContentVerificationError,
    verify_attachment_content,
)
from src.core.attachment_intake_policy import MAX_ATTACHMENT_FILE_BYTES
from src.core.mail import InboundAttachmentMetadata


class AirRateSourceUploadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def register_commercial_air_rate_pdf(
    *,
    repository: AirShadowRepository,
    document_store: AirRateDocumentStore,
    entry_id: str,
    airline_name: str,
    document_name: str,
    content_type: str,
    content: bytes,
    cargo_scope: AirCargoScope = "unknown",
    origin_airport: Optional[str] = None,
    valid_from: Optional[date] = None,
    valid_to: Optional[date] = None,
    recorded_by: str,
    notes: Optional[str] = None,
) -> tuple[AirRateSource, bool]:
    normalized_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if normalized_type != "application/pdf":
        raise AirRateSourceUploadError("air_rate_pdf_content_type_required")
    if not content:
        raise AirRateSourceUploadError("air_rate_pdf_empty")
    if len(content) > MAX_ATTACHMENT_FILE_BYTES:
        raise AirRateSourceUploadError("air_rate_pdf_size_exceeds_limit")
    metadata = InboundAttachmentMetadata(
        name=document_name,
        content_type=normalized_type,
        size_bytes=len(content),
        kind="file",
        is_inline=False,
    )
    try:
        receipt = verify_attachment_content(metadata, content)
    except AttachmentContentVerificationError as exc:
        raise AirRateSourceUploadError(exc.code) from exc
    source = AirRateSource(
        entry_id=entry_id,
        airline_name=airline_name,
        document_name=document_name,
        mime_type="application/pdf",
        sha256_hex=receipt.sha256_hex,
        size_bytes=receipt.size_bytes,
        cargo_scope=cargo_scope,
        origin_airport=origin_airport,
        valid_from=valid_from,
        valid_to=valid_to,
        recorded_by=recorded_by,
        notes=notes,
    )
    document_store.store_verified_pdf(
        sha256_hex=source.sha256_hex,
        content=content,
    )
    stored, created = repository.create_rate_source(source)
    return stored, created


def build_air_rate_source_view(
    *,
    repository: AirShadowRepository,
    document_store: AirRateDocumentStore,
) -> dict:
    items = sorted(
        repository.list_rate_sources(),
        key=lambda item: (item.recorded_at, item.source_id),
        reverse=True,
    )
    return {
        "rate_sources": [
            {
                **item.model_dump(mode="json"),
                "document_stored": document_store.is_stored(item.sha256_hex),
                "runtime_authoritative": False,
            }
            for item in items
        ],
        "shadow_only": True,
        "commercial_air_pricing_enabled": False,
        "express_pricing_enabled": False,
    }
