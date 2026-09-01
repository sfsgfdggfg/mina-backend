from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import PurePath
from typing import Literal
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field

from src.core.mail import InboundAttachmentMetadata


AttachmentContentProfile = Literal["pdf", "xlsx", "csv"]
AttachmentRetrievalStatus = Literal["verified", "manual_review"]
MAX_XLSX_ZIP_ENTRIES = 5000
MAX_XLSX_DECLARED_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


class AttachmentContentVerificationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class VerifiedAttachmentReceipt(BaseModel):
    """Provider-neutral verification evidence. Never contains attachment bytes or provider IDs."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=0)
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    content_profile: AttachmentContentProfile


class AttachmentRetrievalResult(BaseModel):
    """Safe result for controlled transient attachment retrieval."""

    model_config = ConfigDict(extra="forbid")

    status: AttachmentRetrievalStatus
    reason_code: str = Field(min_length=1, max_length=128)
    attachment_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)
    verified_receipts: list[VerifiedAttachmentReceipt] = Field(default_factory=list)
    content_download_performed: bool = False


def manual_retrieval_result(
    *,
    reason_code: str,
    attachment_count: int,
    total_size_bytes: int,
    content_download_performed: bool,
) -> AttachmentRetrievalResult:
    return AttachmentRetrievalResult(
        status="manual_review",
        reason_code=reason_code,
        attachment_count=attachment_count,
        total_size_bytes=total_size_bytes,
        verified_receipts=[],
        content_download_performed=content_download_performed,
    )


def _verify_pdf(content: bytes | bytearray) -> None:
    data = bytes(content)
    if not data.startswith(b"%PDF-"):
        raise AttachmentContentVerificationError("attachment_pdf_signature_invalid")
    if b"%%EOF" not in data[-4096:]:
        raise AttachmentContentVerificationError("attachment_pdf_eof_missing")


def _verify_xlsx(content: bytes | bytearray) -> None:
    if not bytes(content[:4]).startswith(b"PK"):
        raise AttachmentContentVerificationError("attachment_xlsx_signature_invalid")
    try:
        with ZipFile(BytesIO(bytes(content))) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_XLSX_ZIP_ENTRIES:
                raise AttachmentContentVerificationError(
                    "attachment_xlsx_entry_count_exceeds_limit"
                )
            if sum(info.file_size for info in infos) > MAX_XLSX_DECLARED_UNCOMPRESSED_BYTES:
                raise AttachmentContentVerificationError(
                    "attachment_xlsx_uncompressed_size_exceeds_limit"
                )
            names = {info.filename for info in infos}
            required = {
                "[Content_Types].xml",
                "_rels/.rels",
                "xl/workbook.xml",
            }
            if not required.issubset(names):
                raise AttachmentContentVerificationError(
                    "attachment_xlsx_structure_invalid"
                )
            lowered = {name.lower() for name in names}
            if any(
                name.endswith("vbaproject.bin")
                or "/macrosheets/" in name
                for name in lowered
            ):
                raise AttachmentContentVerificationError(
                    "attachment_xlsx_macro_content_rejected"
                )
    except BadZipFile as exc:
        raise AttachmentContentVerificationError(
            "attachment_xlsx_signature_invalid"
        ) from exc


def _verify_csv(content: bytes | bytearray) -> None:
    data = bytes(content)
    if b"\x00" in data:
        raise AttachmentContentVerificationError("attachment_csv_binary_content_rejected")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AttachmentContentVerificationError(
            "attachment_csv_encoding_not_allowed"
        ) from exc
    if any(
        ord(character) < 32
        and character not in "\t\r\n"
        for character in text
    ):
        raise AttachmentContentVerificationError("attachment_csv_control_character_rejected")


def verify_attachment_content(
    metadata: InboundAttachmentMetadata,
    content: bytes | bytearray,
) -> VerifiedAttachmentReceipt:
    """Verify a bounded attachment without parsing business meaning or invoking AI."""

    actual_size = len(content)
    if actual_size > metadata.size_bytes:
        raise AttachmentContentVerificationError(
            "attachment_content_size_exceeds_metadata"
        )
    if metadata.content_type is None:
        raise AttachmentContentVerificationError("attachment_content_type_missing")

    extension = PurePath(metadata.name).suffix.lower()
    if extension == ".pdf":
        _verify_pdf(content)
        profile: AttachmentContentProfile = "pdf"
    elif extension == ".xlsx":
        _verify_xlsx(content)
        profile = "xlsx"
    elif extension == ".csv":
        _verify_csv(content)
        profile = "csv"
    else:
        raise AttachmentContentVerificationError("attachment_content_extension_not_allowed")

    return VerifiedAttachmentReceipt(
        name=metadata.name,
        content_type=metadata.content_type,
        size_bytes=actual_size,
        sha256_hex=sha256(content).hexdigest(),
        content_profile=profile,
    )
