from __future__ import annotations

from pathlib import PurePath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.core.mail import InboundMailEnvelope


MAX_ATTACHMENT_FILE_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_AUTO_FILES = 5

AttachmentIntakeStatus = Literal[
    "metadata_allowlisted",
    "manual_review",
]

_ALLOWED_MIME_TYPES: dict[str, frozenset[str]] = {
    ".pdf": frozenset({"application/pdf"}),
    ".xlsx": frozenset({
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
    ".csv": frozenset({
        "text/csv",
        "application/csv",
        "text/plain",
        "application/vnd.ms-excel",
    }),
}


class AttachmentIntakeAssessment(BaseModel):
    """Metadata-only attachment policy result. Never authorizes content retrieval."""

    model_config = ConfigDict(extra="forbid")

    status: AttachmentIntakeStatus
    reason_code: str = Field(min_length=1, max_length=128)
    attachment_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)


def _assessment(
    *,
    status: AttachmentIntakeStatus,
    reason_code: str,
    attachment_count: int,
    total_size_bytes: int,
) -> AttachmentIntakeAssessment:
    return AttachmentIntakeAssessment(
        status=status,
        reason_code=reason_code,
        attachment_count=attachment_count,
        total_size_bytes=total_size_bytes,
    )


def assess_attachment_intake(
    mail: InboundMailEnvelope,
) -> AttachmentIntakeAssessment:
    """Classify attachment metadata without downloading attachment content."""

    if not mail.has_attachments:
        raise ValueError("Attachment intake requires has_attachments=true.")

    manifest = mail.attachment_manifest
    count = len(manifest)
    total_size = sum(item.size_bytes for item in manifest)

    def manual(reason_code: str) -> AttachmentIntakeAssessment:
        return _assessment(
            status="manual_review",
            reason_code=reason_code,
            attachment_count=count,
            total_size_bytes=total_size,
        )

    if mail.attachment_manifest_truncated:
        return manual("attachment_manifest_truncated")
    if not manifest:
        return manual("attachment_manifest_missing")
    if count > MAX_ATTACHMENT_AUTO_FILES:
        return manual("attachment_count_exceeds_limit")
    if total_size > MAX_ATTACHMENT_TOTAL_BYTES:
        return manual("attachment_total_size_exceeds_limit")

    for item in manifest:
        if item.kind != "file":
            return manual("attachment_kind_not_allowed")
        if item.is_inline:
            return manual("attachment_inline_not_allowed")
        if item.size_bytes > MAX_ATTACHMENT_FILE_BYTES:
            return manual("attachment_file_size_exceeds_limit")

        extension = PurePath(item.name).suffix.lower()
        allowed_mimes = _ALLOWED_MIME_TYPES.get(extension)
        if allowed_mimes is None:
            return manual("attachment_extension_not_allowed")
        if item.content_type is None:
            return manual("attachment_mime_missing")
        if item.content_type not in allowed_mimes:
            return manual("attachment_mime_mismatch")

    return _assessment(
        status="metadata_allowlisted",
        reason_code="attachment_metadata_allowlisted",
        attachment_count=count,
        total_size_bytes=total_size,
    )
