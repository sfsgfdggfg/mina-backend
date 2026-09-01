from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


InboundMailChannel = Literal[
    "email",
    "manual",
    "portal",
    "api",
]

MailPurpose = Literal[
    "customer_clarification",
    "supplier_rfq",
    "customer_quote",
]

MailSendStatus = Literal[
    "sent",
    "failed",
    "rejected_before_provider",
    "provider_unavailable",
]

MAX_INBOUND_MAIL_BODY_BYTES = 256 * 1024
MAX_ATTACHMENT_MANIFEST_ITEMS = 25

AttachmentKind = Literal[
    "file",
    "item",
    "reference",
    "unknown",
]


class InboundAttachmentMetadata(BaseModel):
    """Non-content attachment metadata safe for inbound routing decisions."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=512)
    content_type: Optional[str] = Field(default=None, max_length=255)
    size_bytes: int = Field(ge=0)
    kind: AttachmentKind = "unknown"
    is_inline: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Attachment name must not be empty.")
        return normalized

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None



def _validate_inbound_mail_body_size(value: str) -> str:
    body_size = len(value.encode("utf-8"))

    if body_size > MAX_INBOUND_MAIL_BODY_BYTES:
        raise ValueError(
            "Inbound mail body exceeds the controlled "
            f"{MAX_INBOUND_MAIL_BODY_BYTES}-byte limit."
        )

    return value


def validate_inbound_mail_body(value: str) -> str:
    if not value.strip():
        raise ValueError(
            "Inbound mail body must not be empty."
        )

    return _validate_inbound_mail_body_size(value)


def _normalize_address(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or "@" not in normalized:
        raise ValueError("A valid mail address is required.")
    return normalized


class InboundMailEnvelope(BaseModel):
    """Provider-neutral inbound message consumed by MINAI workflows."""

    model_config = ConfigDict(extra="forbid")

    external_message_id: Optional[str] = None
    provider_name: Optional[str] = None
    mailbox_id: Optional[str] = None
    sender_address: Optional[str] = None
    sender_name: Optional[str] = None
    recipient_addresses: list[str] = Field(default_factory=list)
    subject: Optional[str] = None
    body_text: str
    raw_body_sha256: Optional[str] = None
    privacy_transformed: bool = False
    privacy_transform_version: Optional[str] = None
    received_at: Optional[datetime] = None
    in_reply_to_message_id: Optional[str] = None
    explicit_rfq_reference: Optional[str] = None
    has_attachments: bool = False
    attachment_manifest: list[InboundAttachmentMetadata] = Field(default_factory=list, max_length=MAX_ATTACHMENT_MANIFEST_ITEMS)
    attachment_manifest_truncated: bool = False
    source: InboundMailChannel = "manual"

    @model_validator(mode="after")
    def validate_attachment_manifest_consistency(self):
        if not self.body_text.strip() and not self.has_attachments:
            raise ValueError(
                "Inbound mail body must not be empty."
            )
        if (self.attachment_manifest or self.attachment_manifest_truncated) and not self.has_attachments:
            raise ValueError(
                "Attachment manifest requires has_attachments=true."
            )
        return self

    @field_validator("body_text")
    @classmethod
    def validate_body_text(cls, value: str) -> str:
        return _validate_inbound_mail_body_size(value)

    @field_validator("sender_address")
    @classmethod
    def normalize_sender_address(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _normalize_address(value)

    @field_validator("recipient_addresses")
    @classmethod
    def normalize_recipient_addresses(cls, value: list[str]) -> list[str]:
        normalized = [_normalize_address(address) for address in value]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Inbound recipient addresses must be unique.")
        return normalized

    @field_validator(
        "external_message_id",
        "provider_name",
        "mailbox_id",
        "sender_name",
        "subject",
        "raw_body_sha256",
        "privacy_transform_version",
        "in_reply_to_message_id",
        "explicit_rfq_reference",
    )
    @classmethod
    def normalize_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @property
    def message_deduplication_key(self) -> Optional[str]:
        if self.external_message_id is None:
            return None
        provider = (self.provider_name or self.source).strip().lower()
        mailbox = (self.mailbox_id or "default").strip().lower()
        return f"{provider}:{mailbox}:{self.external_message_id}"


class OutboundMailRequest(BaseModel):
    """Provider-neutral message; construction does not authorize sending."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    recipients: list[str]
    subject: str
    body_text: str
    purpose: MailPurpose
    correlation_reference: Optional[str] = None
    reference_metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("operation_id", "subject", "body_text")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Outbound mail fields must not be empty.")
        return normalized

    @field_validator("correlation_reference")
    @classmethod
    def normalize_correlation_reference(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("recipients")
    @classmethod
    def normalize_recipients(cls, value: list[str]) -> list[str]:
        normalized = [_normalize_address(address) for address in value]
        if not normalized:
            raise ValueError("At least one outbound recipient is required.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Outbound recipients must be unique.")
        return normalized

    @field_validator("reference_metadata")
    @classmethod
    def normalize_reference_metadata(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = raw_key.strip()
            item = raw_value.strip()
            if not key or not item:
                raise ValueError(
                    "Outbound reference metadata must not contain empty values."
                )
            normalized[key] = item
        return normalized


class MailSendResult(BaseModel):
    """Controlled provider-neutral delivery outcome."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    status: MailSendStatus
    reason: str
    provider_name: Optional[str] = None
    provider_message_id: Optional[str] = None
    sent_at: Optional[datetime] = None

    @field_validator("operation_id", "reason")
    @classmethod
    def require_result_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Mail send result fields must not be empty.")
        return normalized

    @field_validator("provider_name", "provider_message_id")
    @classmethod
    def normalize_optional_result_text(
        cls,
        value: Optional[str],
    ) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_delivery_metadata(self):
        if self.status == "sent":
            if self.provider_message_id is None or self.sent_at is None:
                raise ValueError(
                    "Sent mail requires provider_message_id and sent_at."
                )
        elif self.provider_message_id is not None or self.sent_at is not None:
            raise ValueError(
                "Unsent mail must not include successful delivery metadata."
            )
        return self


class InboundMailSource(Protocol):
    def receive(self) -> Iterable[InboundMailEnvelope]:
        ...


class OutboundMailSender(Protocol):
    def send(self, request: OutboundMailRequest) -> MailSendResult:
        ...
