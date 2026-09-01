from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4
from typing import Any
from urllib.parse import quote, urlsplit

import requests
from pydantic import ValidationError

from src.core.mail import (
    MAX_ATTACHMENT_MANIFEST_ITEMS,
    InboundAttachmentMetadata,
    InboundMailEnvelope,
    MailSendResult,
    OutboundMailRequest,
)
from src.integrations.microsoft_auth import MicrosoftAuthConfig, acquire_silent_access_token


GRAPH_API_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_PROVIDER_NAME = "microsoft_graph"
DEFAULT_TIMEOUT_SECONDS = 10.0
MAX_PULL_MESSAGES = 50
_ATTACHMENT_SELECT_FIELDS = "name,contentType,size,isInline"

_GRAPH_SELECT_FIELDS = (
    "id,subject,body,from,toRecipients,"
    "receivedDateTime,hasAttachments,isDraft"
)

_GRAPH_PREFER = (
    'IdType="ImmutableId", '
    'outlook.body-content-type="text"'
)


class OutlookGraphReadError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OutlookGraphMessageError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OutlookGraphMessageRejection:
    external_message_id: str
    received_at: str
    reason_code: str


def _required_text(
    value: Any,
    *,
    code: str,
) -> str:
    if not isinstance(value, str):
        raise OutlookGraphMessageError(code)

    normalized = value.strip()
    if not normalized:
        raise OutlookGraphMessageError(code)

    return normalized


def _optional_text(
    value: Any,
    *,
    code: str,
) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise OutlookGraphMessageError(code)

    normalized = value.strip()
    return normalized or None


def _graph_email_address(
    value: Any,
    *,
    code: str,
) -> tuple[str, str | None]:
    if not isinstance(value, dict):
        raise OutlookGraphMessageError(code)

    email_address = value.get("emailAddress")
    if not isinstance(email_address, dict):
        raise OutlookGraphMessageError(code)

    address = _required_text(
        email_address.get("address"),
        code=code,
    )

    name = _optional_text(
        email_address.get("name"),
        code=code,
    )

    return address, name


def _blank_text_body_rejection(
    raw_message: dict[str, Any],
) -> OutlookGraphMessageRejection | None:
    body = raw_message.get("body")
    if not isinstance(body, dict):
        return None

    content_type = body.get("contentType")
    content = body.get("content")

    if (
        not isinstance(content_type, str)
        or content_type.strip().lower() != "text"
        or not isinstance(content, str)
        or content.strip()
    ):
        return None

    message_id = _required_text(
        raw_message.get("id"),
        code="graph_message_id_missing",
    )
    received_at = _required_text(
        raw_message.get("receivedDateTime"),
        code="graph_received_time_missing",
    )

    is_draft = raw_message.get("isDraft")
    if not isinstance(is_draft, bool):
        raise OutlookGraphMessageError(
            "graph_message_draft_state_missing"
        )
    if is_draft:
        raise OutlookGraphMessageError(
            "graph_draft_message_rejected"
        )

    has_attachments = raw_message.get("hasAttachments")
    if not isinstance(has_attachments, bool):
        raise OutlookGraphMessageError(
            "graph_attachment_state_missing"
        )

    return OutlookGraphMessageRejection(
        external_message_id=message_id,
        received_at=received_at,
        reason_code="graph_empty_message_body",
    )


def _normalize_graph_attachment_metadata(
    raw_attachment: Any,
) -> InboundAttachmentMetadata:
    if not isinstance(raw_attachment, dict):
        raise OutlookGraphReadError("graph_attachment_metadata_invalid")

    name = _required_text(
        raw_attachment.get("name"),
        code="graph_attachment_name_missing",
    )
    content_type = _optional_text(
        raw_attachment.get("contentType"),
        code="graph_attachment_content_type_invalid",
    )
    size = raw_attachment.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise OutlookGraphReadError("graph_attachment_size_invalid")
    is_inline = raw_attachment.get("isInline")
    if not isinstance(is_inline, bool):
        raise OutlookGraphReadError("graph_attachment_inline_state_invalid")

    try:
        return InboundAttachmentMetadata(
            name=name,
            content_type=content_type,
            size_bytes=size,
            is_inline=is_inline,
        )
    except (ValidationError, ValueError) as exc:
        raise OutlookGraphReadError("graph_attachment_metadata_invalid") from exc


def normalize_graph_message(
    raw_message: dict[str, Any],
    *,
    mailbox_id: str,
    attachment_manifest: list[InboundAttachmentMetadata] | None = None,
    attachment_manifest_truncated: bool = False,
) -> InboundMailEnvelope:
    if not isinstance(raw_message, dict):
        raise OutlookGraphMessageError(
            "graph_message_not_object"
        )

    message_id = _required_text(
        raw_message.get("id"),
        code="graph_message_id_missing",
    )

    is_draft = raw_message.get("isDraft")
    if not isinstance(is_draft, bool):
        raise OutlookGraphMessageError(
            "graph_message_draft_state_missing"
        )
    if is_draft:
        raise OutlookGraphMessageError(
            "graph_draft_message_rejected"
        )

    has_attachments = raw_message.get(
        "hasAttachments"
    )
    if not isinstance(has_attachments, bool):
        raise OutlookGraphMessageError(
            "graph_attachment_state_missing"
        )

    body = raw_message.get("body")
    if not isinstance(body, dict):
        raise OutlookGraphMessageError(
            "graph_message_body_missing"
        )

    content_type = _required_text(
        body.get("contentType"),
        code="graph_message_body_type_missing",
    ).lower()

    if content_type != "text":
        raise OutlookGraphMessageError(
            "graph_non_text_body_rejected"
        )

    raw_body_text = body.get("content")
    if not isinstance(raw_body_text, str):
        raise OutlookGraphMessageError(
            "graph_message_body_missing"
        )
    body_text = raw_body_text
    if not body_text.strip() and not has_attachments:
        raise OutlookGraphMessageError(
            "graph_message_body_missing"
        )

    sender_address, sender_name = (
        _graph_email_address(
            raw_message.get("from"),
            code="graph_sender_missing",
        )
    )

    raw_recipients = raw_message.get(
        "toRecipients"
    )
    if not isinstance(raw_recipients, list):
        raise OutlookGraphMessageError(
            "graph_recipients_missing"
        )

    recipient_addresses: list[str] = []
    for recipient in raw_recipients:
        address, _ = _graph_email_address(
            recipient,
            code="graph_recipient_invalid",
        )
        recipient_addresses.append(address)

    subject = _optional_text(
        raw_message.get("subject"),
        code="graph_subject_invalid",
    )

    received_at = _required_text(
        raw_message.get("receivedDateTime"),
        code="graph_received_time_missing",
    )

    normalized_mailbox = _required_text(
        mailbox_id,
        code="graph_mailbox_id_missing",
    ).lower()

    try:
        return InboundMailEnvelope(
            external_message_id=message_id,
            provider_name=GRAPH_PROVIDER_NAME,
            mailbox_id=normalized_mailbox,
            sender_address=sender_address,
            sender_name=sender_name,
            recipient_addresses=recipient_addresses,
            subject=subject,
            body_text=body_text,
            received_at=received_at,
            has_attachments=has_attachments,
            attachment_manifest=(attachment_manifest or []),
            attachment_manifest_truncated=attachment_manifest_truncated,
            source="email",
        )
    except (ValidationError, ValueError) as exc:
        raise OutlookGraphMessageError(
            "graph_message_contract_invalid"
        ) from exc


def _validated_next_link(value: Any) -> str | None:
    if value is None:
        return None

    if not isinstance(value, str):
        raise OutlookGraphReadError(
            "graph_next_link_invalid"
        )

    normalized = value.strip()
    if not normalized:
        return None

    parsed = urlsplit(normalized)

    if (
        parsed.scheme != "https"
        or parsed.hostname != "graph.microsoft.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
        or not parsed.path.startswith("/v1.0/")
    ):
        raise OutlookGraphReadError(
            "graph_next_link_invalid"
        )

    return normalized


class OutlookGraphReadClient:
    def __init__(
        self,
        *,
        access_token: str,
        mailbox_id: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any | None = None,
    ) -> None:
        normalized_token = access_token.strip()
        normalized_mailbox = mailbox_id.strip()

        if not normalized_token:
            raise ValueError(
                "Microsoft Graph access token is required."
            )

        if not normalized_mailbox:
            raise ValueError(
                "Microsoft Graph mailbox identity is required."
            )

        if timeout <= 0:
            raise ValueError(
                "Microsoft Graph timeout must be positive."
            )

        self.__access_token = normalized_token
        self.mailbox_id = normalized_mailbox.lower()
        self.timeout = timeout
        self.session = session or requests.Session()
        self.last_message_rejections: list[
            OutlookGraphMessageRejection
        ] = []

        try:
            self.session.trust_env = False
        except AttributeError:
            pass

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": (
                f"Bearer {self.__access_token}"
            ),
            "Accept": "application/json",
            "Prefer": _GRAPH_PREFER,
        }

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                "GET",
                url,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise OutlookGraphReadError(
                "microsoft_graph_unavailable"
            ) from exc

        status_code = int(
            getattr(response, "status_code", 0)
        )

        if 300 <= status_code < 400:
            raise OutlookGraphReadError(
                "microsoft_graph_redirect_refused"
            )

        if status_code < 200 or status_code >= 300:
            raise OutlookGraphReadError(
                f"microsoft_graph_http_{status_code}"
            )

        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise OutlookGraphReadError(
                "microsoft_graph_invalid_json"
            ) from exc

        if not isinstance(payload, dict):
            raise OutlookGraphReadError(
                "microsoft_graph_invalid_payload"
            )

        return payload

    def _attachment_manifest_for_message(
        self,
        message_id: str,
    ) -> tuple[list[InboundAttachmentMetadata], bool]:
        encoded_message_id = quote(message_id, safe="")
        url = (
            f"{GRAPH_API_BASE_URL}/me/messages/"
            f"{encoded_message_id}/attachments"
        )
        payload = self._get_json(
            url,
            params={
                "$select": _ATTACHMENT_SELECT_FIELDS,
                "$top": MAX_ATTACHMENT_MANIFEST_ITEMS,
            },
        )
        raw_items = payload.get("value")
        if not isinstance(raw_items, list):
            raise OutlookGraphReadError("microsoft_graph_attachments_missing")
        if len(raw_items) > MAX_ATTACHMENT_MANIFEST_ITEMS:
            raise OutlookGraphReadError("graph_attachment_manifest_oversized")
        manifest = [
            _normalize_graph_attachment_metadata(item)
            for item in raw_items
        ]
        truncated = _validated_next_link(payload.get("@odata.nextLink")) is not None
        return manifest, truncated

    def list_inbox_messages(
        self,
        *,
        limit: int = 25,
    ) -> list[InboundMailEnvelope]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or limit < 1
            or limit > MAX_PULL_MESSAGES
        ):
            raise ValueError(
                "Microsoft Graph pull limit must be "
                f"between 1 and {MAX_PULL_MESSAGES}."
            )

        url = (
            f"{GRAPH_API_BASE_URL}"
            "/me/mailFolders/inbox/messages"
        )

        params: dict[str, Any] | None = {
            "$select": _GRAPH_SELECT_FIELDS,
            "$orderby": "receivedDateTime desc",
            "$top": limit,
        }

        messages: list[InboundMailEnvelope] = []
        self.last_message_rejections = []
        examined_count = 0

        while url and examined_count < limit:
            payload = self._get_json(
                url,
                params=params,
            )

            raw_items = payload.get("value")
            if not isinstance(raw_items, list):
                raise OutlookGraphReadError(
                    "microsoft_graph_messages_missing"
                )

            for raw_item in raw_items:
                if examined_count >= limit:
                    break

                examined_count += 1

                if not isinstance(raw_item, dict):
                    raise OutlookGraphReadError(
                        "microsoft_graph_message_invalid"
                    )

                rejection = _blank_text_body_rejection(
                    raw_item
                )
                if (
                    rejection is not None
                    and raw_item.get("hasAttachments") is not True
                ):
                    self.last_message_rejections.append(
                        rejection
                    )
                    continue

                attachment_manifest: list[InboundAttachmentMetadata] = []
                attachment_manifest_truncated = False
                if raw_item.get("hasAttachments") is True:
                    message_id = _required_text(
                        raw_item.get("id"),
                        code="graph_message_id_missing",
                    )
                    (
                        attachment_manifest,
                        attachment_manifest_truncated,
                    ) = self._attachment_manifest_for_message(message_id)

                messages.append(
                    normalize_graph_message(
                        raw_item,
                        mailbox_id=self.mailbox_id,
                        attachment_manifest=attachment_manifest,
                        attachment_manifest_truncated=(
                            attachment_manifest_truncated
                        ),
                    )
                )

            next_link = _validated_next_link(
                payload.get("@odata.nextLink")
            )

            if examined_count >= limit:
                break

            url = next_link
            params = None

        return messages


class OutlookGraphSendClient:
    def __init__(self, *, config: MicrosoftAuthConfig, timeout: float = DEFAULT_TIMEOUT_SECONDS, session: Any | None = None) -> None:
        self.config = config
        self.timeout = timeout
        self.session = session or requests.Session()
        try:
            self.session.trust_env = False
        except AttributeError:
            pass

    def send(self, request: OutboundMailRequest) -> MailSendResult:
        token = acquire_silent_access_token(self.config)
        client_request_id = str(uuid4())
        payload = {
            "message": {
                "subject": request.subject,
                "body": {"contentType": "Text", "content": request.body_text},
                "toRecipients": [
                    {"emailAddress": {"address": address}}
                    for address in request.recipients
                ],
            },
            "saveToSentItems": True,
        }
        try:
            response = self.session.request(
                "POST",
                f"{GRAPH_API_BASE_URL}/me/sendMail",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "client-request-id": client_request_id,
                    "return-client-request-id": "true",
                },
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            return MailSendResult(
                operation_id=request.operation_id,
                status="failed",
                reason="Microsoft Graph mail send was unavailable.",
                provider_name=GRAPH_PROVIDER_NAME,
            )
        status_code = int(getattr(response, "status_code", 0))
        if status_code != 202:
            return MailSendResult(
                operation_id=request.operation_id,
                status="failed",
                reason=f"Microsoft Graph mail send returned HTTP {status_code}.",
                provider_name=GRAPH_PROVIDER_NAME,
            )
        headers = getattr(response, "headers", {}) or {}
        provider_reference = str(headers.get("request-id") or headers.get("client-request-id") or client_request_id).strip()
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="Microsoft Graph accepted the message for delivery.",
            provider_name=GRAPH_PROVIDER_NAME,
            provider_message_id=provider_reference,
            sent_at=datetime.now(timezone.utc),
        )


def outlook_graph_sender_from_environment() -> OutlookGraphSendClient:
    return OutlookGraphSendClient(config=MicrosoftAuthConfig.from_environment())
