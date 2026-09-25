from __future__ import annotations

import base64
import hashlib
import html as html_module
import imaplib
import ipaddress
import quopri
import re
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable

import certifi

from src.core.mail import InboundAttachmentMetadata, InboundMailEnvelope
from src.core.relationship_history import HistoricalMailMessage
from src.integrations.mailbox_credentials import ImapMailboxCredential

IMAP_PROVIDER_NAME = "imap"
MAX_IMAP_RAW_MESSAGE_BYTES = 2 * 1024 * 1024
MAX_IMAP_TEXT_BODY_BYTES = 256 * 1024
MAX_IMAP_HISTORY_MESSAGES = 10_000
DEFAULT_IMAP_TIMEOUT_SECONDS = 20.0


class ImapMailboxError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ImapMessageRejection:
    external_message_id: str
    received_at: str
    reason_code: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if value:
            self.parts.append(value)

    def text(self) -> str:
        return "\n".join(self.parts)


def _html_to_text(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    parser.close()
    return html_module.unescape(parser.text())


def _safe_host_addresses(host: str) -> list[str]:
    try:
        answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ImapMailboxError("imap_host_resolution_failed") from exc
    addresses = sorted({item[4][0] for item in answers})
    if not addresses:
        raise ImapMailboxError("imap_host_resolution_failed")
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_unspecified
            or ip.is_reserved
        ):
            raise ImapMailboxError("imap_host_resolves_to_nonpublic_address")
    return addresses


def _tls_context(credential: ImapMailboxCredential) -> ssl.SSLContext:
    if credential.certificate_sha256:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=certifi.where())


def _message_datetime(message: Message) -> datetime:
    raw = message.get("Date")
    if not raw:
        raise ImapMailboxError("imap_message_date_missing")
    try:
        value = parsedate_to_datetime(raw)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ImapMailboxError("imap_message_date_invalid") from exc
    if value is None:
        raise ImapMailboxError("imap_message_date_invalid")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _addresses(message: Message, names: tuple[str, ...]) -> list[str]:
    raw_values: list[str] = []
    for name in names:
        raw_values.extend(message.get_all(name, []))
    result: list[str] = []
    for _, address in getaddresses(raw_values):
        normalized = address.strip().casefold()
        if normalized.count("@") == 1 and not any(ch.isspace() for ch in normalized):
            if normalized not in result:
                result.append(normalized)
    return result


def _sender(message: Message) -> tuple[str, str | None]:
    items = getaddresses(message.get_all("From", []))
    if len(items) != 1:
        raise ImapMailboxError("imap_message_sender_invalid")
    name, address = items[0]
    normalized = address.strip().casefold()
    if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
        raise ImapMailboxError("imap_message_sender_invalid")
    return normalized, (name.strip() or None)


def _body_and_attachments(message: Message) -> tuple[str, list[InboundAttachmentMetadata]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[InboundAttachmentMetadata] = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition == "attachment" or filename:
            attachments.append(
                InboundAttachmentMetadata(
                    name=(filename or "attachment")[:512],
                    content_type=(part.get_content_type() or None),
                    size_bytes=0,
                    kind="file",
                    is_inline=disposition == "inline",
                )
            )
            continue
        content_type = (part.get_content_type() or "").lower()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            continue
        if not isinstance(value, str):
            continue
        if content_type == "text/plain":
            plain_parts.append(value)
        else:
            html_parts.append(_html_to_text(value))
    body = "\n\n".join(item.strip() for item in (plain_parts or html_parts) if item.strip())
    return body, attachments



@dataclass(frozen=True)
class _ImapBodyPart:
    section: str
    content_type: str
    charset: str | None
    transfer_encoding: str
    size_bytes: int
    filename: str | None
    disposition: str | None

    @property
    def is_safe_text(self) -> bool:
        return (
            self.content_type in {"text/plain", "text/html"}
            and self.disposition != "attachment"
            and self.filename is None
        )


def _imap_bodystructure_tokens(raw: bytes) -> list[object]:
    text = raw.decode("ascii", errors="strict")
    marker = re.search(r"\bBODYSTRUCTURE\s+", text, flags=re.I)
    if marker is None:
        raise ImapMailboxError("imap_bodystructure_missing")
    text = text[marker.end():]
    tokens: list[object] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "()":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            index += 1
            value: list[str] = []
            while index < length:
                char = text[index]
                if char == "\\" and index + 1 < length:
                    value.append(text[index + 1])
                    index += 2
                    continue
                if char == '"':
                    index += 1
                    break
                value.append(char)
                index += 1
            else:
                raise ImapMailboxError("imap_bodystructure_invalid")
            tokens.append("".join(value))
            continue
        start = index
        while index < length and not text[index].isspace() and text[index] not in "()":
            index += 1
        atom = text[start:index]
        if not atom:
            raise ImapMailboxError("imap_bodystructure_invalid")
        if atom.upper() == "NIL":
            tokens.append(None)
        elif atom.isdigit():
            tokens.append(int(atom))
        else:
            tokens.append(atom)
    return tokens


def _parse_imap_list(tokens: list[object]) -> list[object]:
    position = 0

    def parse_one():
        nonlocal position
        if position >= len(tokens):
            raise ImapMailboxError("imap_bodystructure_invalid")
        token = tokens[position]
        position += 1
        if token == "(":
            result: list[object] = []
            while True:
                if position >= len(tokens):
                    raise ImapMailboxError("imap_bodystructure_invalid")
                if tokens[position] == ")":
                    position += 1
                    return result
                result.append(parse_one())
        if token == ")":
            raise ImapMailboxError("imap_bodystructure_invalid")
        return token

    value = parse_one()
    if not isinstance(value, list):
        raise ImapMailboxError("imap_bodystructure_invalid")
    # FETCH responses may contain a trailing ')' belonging to the FETCH wrapper.
    while position < len(tokens) and tokens[position] == ")":
        position += 1
    return value


def _bodystructure_params(value: object) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    result: dict[str, str] = {}
    for index in range(0, len(value) - 1, 2):
        key = value[index]
        item = value[index + 1]
        if isinstance(key, str) and isinstance(item, str):
            result[key.casefold()] = item
    return result


def _bodystructure_disposition(value: object) -> tuple[str | None, dict[str, str]]:
    if not isinstance(value, list) or not value:
        return None, {}
    raw = value[0]
    disposition = raw.casefold() if isinstance(raw, str) else None
    params = _bodystructure_params(value[1] if len(value) > 1 else None)
    return disposition, params


def _collect_body_parts(structure: list[object]) -> list[_ImapBodyPart]:
    parts: list[_ImapBodyPart] = []

    def visit(node: list[object], path: tuple[int, ...]) -> None:
        if not node:
            raise ImapMailboxError("imap_bodystructure_invalid")
        if isinstance(node[0], list):
            child_index = 1
            for child in node:
                if not isinstance(child, list):
                    break
                visit(child, (*path, child_index))
                child_index += 1
            return
        if len(node) < 7:
            raise ImapMailboxError("imap_bodystructure_invalid")
        raw_type, raw_subtype = node[0], node[1]
        if not isinstance(raw_type, str) or not isinstance(raw_subtype, str):
            raise ImapMailboxError("imap_bodystructure_invalid")
        content_type = f"{raw_type}/{raw_subtype}".casefold()
        params = _bodystructure_params(node[2])
        encoding = str(node[5] or "7BIT").strip().upper()
        size = node[6]
        if not isinstance(size, int) or size < 0:
            raise ImapMailboxError("imap_bodystructure_invalid")
        # TEXT adds a line-count field, so extension fields begin at 8 instead of 7.
        extension_index = 8 if raw_type.casefold() == "text" else 7
        # MESSAGE/RFC822 has envelope/body/line-count before extension fields.
        if raw_type.casefold() == "message" and raw_subtype.casefold() == "rfc822":
            extension_index = 10
        disposition_value = None
        # extension order: MD5, disposition, language, location...
        if len(node) > extension_index + 1:
            disposition_value = node[extension_index + 1]
        disposition, disposition_params = _bodystructure_disposition(disposition_value)
        filename = (
            disposition_params.get("filename")
            or params.get("name")
            or None
        )
        section = ".".join(str(item) for item in path) if path else "TEXT"
        parts.append(
            _ImapBodyPart(
                section=section,
                content_type=content_type,
                charset=params.get("charset"),
                transfer_encoding=encoding,
                size_bytes=size,
                filename=filename,
                disposition=disposition,
            )
        )

    visit(structure, ())
    return parts


def _extract_fetch_literal(rows) -> bytes:
    if not rows:
        raise ImapMailboxError("imap_message_fetch_failed")
    for item in rows:
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    raise ImapMailboxError("imap_message_fetch_failed")


def _extract_bodystructure(rows) -> list[object]:
    if not rows:
        raise ImapMailboxError("imap_bodystructure_missing")
    raw_chunks = [item for item in rows if isinstance(item, bytes)]
    if not raw_chunks:
        for item in rows:
            if isinstance(item, tuple) and item and isinstance(item[0], bytes):
                raw_chunks.append(item[0])
    if not raw_chunks:
        raise ImapMailboxError("imap_bodystructure_missing")
    raw = b" ".join(raw_chunks)
    return _parse_imap_list(_imap_bodystructure_tokens(raw))


def _decode_text_part(raw: bytes, part: _ImapBodyPart) -> str:
    encoding = part.transfer_encoding.upper()
    try:
        if encoding == "BASE64":
            decoded = base64.b64decode(raw, validate=False)
        elif encoding == "QUOTED-PRINTABLE":
            decoded = quopri.decodestring(raw)
        else:
            decoded = raw
    except (ValueError, TypeError) as exc:
        raise ImapMailboxError("imap_text_part_decode_failed") from exc
    charset = (part.charset or "utf-8").strip() or "utf-8"
    try:
        text = decoded.decode(charset, errors="strict")
    except (LookupError, UnicodeDecodeError):
        try:
            text = decoded.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ImapMailboxError("imap_text_part_decode_failed") from exc
    if part.content_type == "text/html":
        return _html_to_text(text)
    return text


def _folder_name(raw: bytes) -> tuple[set[bytes], str] | None:
    try:
        flags = set(imaplib.ParseFlags(raw))
        text = raw.decode("ascii", errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    match = re.search(r' (?P<name>"(?:[^"\\]|\\.)*"|[^ ]+)$', text)
    if match is None:
        return None
    name = match.group("name")
    if name.startswith('"') and name.endswith('"'):
        name = name[1:-1].replace(r'\"', '"').replace(r"\\", "\\")
    return flags, name


class ImapReadClient:
    def __init__(
        self,
        *,
        credential: ImapMailboxCredential,
        timeout: float = DEFAULT_IMAP_TIMEOUT_SECONDS,
        connection_factory: Callable[..., imaplib.IMAP4_SSL] | None = None,
    ) -> None:
        self.credential = credential
        self.timeout = timeout
        self.connection_factory = connection_factory or imaplib.IMAP4_SSL
        self.last_message_rejections: list[ImapMessageRejection] = []

    def _connect(self):
        _safe_host_addresses(self.credential.host)
        try:
            client = self.connection_factory(
                self.credential.host,
                self.credential.port,
                ssl_context=_tls_context(self.credential),
                timeout=self.timeout,
            )
        except (OSError, ssl.SSLError, imaplib.IMAP4.error) as exc:
            raise ImapMailboxError("imap_tls_connection_failed") from exc
        try:
            if self.credential.certificate_sha256:
                certificate = client.sock.getpeercert(binary_form=True)
                actual = hashlib.sha256(certificate).hexdigest()
                if actual != self.credential.certificate_sha256:
                    raise ImapMailboxError("imap_certificate_pin_mismatch")
            client.login(
                self.credential.username,
                self.credential.password.get_secret_value(),
            )
            return client
        except ImapMailboxError:
            try:
                client.shutdown()
            except Exception:
                pass
            raise
        except (OSError, ssl.SSLError, imaplib.IMAP4.error) as exc:
            try:
                client.shutdown()
            except Exception:
                pass
            raise ImapMailboxError("imap_authentication_failed") from exc

    @staticmethod
    def _close(client) -> None:
        try:
            client.logout()
        except Exception:
            try:
                client.shutdown()
            except Exception:
                pass

    def test_connection(self) -> None:
        client = self._connect()
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapMailboxError("imap_inbox_readonly_select_failed")
        finally:
            self._close(client)

    @staticmethod
    def _uid_validity(client) -> str:
        _, values = client.response("UIDVALIDITY")
        if values and values[0]:
            raw = values[0]
            if isinstance(raw, bytes):
                return raw.decode("ascii", errors="replace")
            return str(raw)
        return "unknown"

    @staticmethod
    def _search_uids(
        client, *, start_at: datetime | None = None, end_at: datetime | None = None
    ) -> list[bytes]:
        criteria: list[str] = []
        if start_at is not None:
            criteria.extend(["SINCE", start_at.strftime("%d-%b-%Y")])
        if end_at is not None:
            criteria.extend(["BEFORE", (end_at + timedelta(days=1)).strftime("%d-%b-%Y")])
        if not criteria:
            criteria = ["ALL"]
        status, rows = client.uid("search", None, *criteria)
        if status != "OK" or not rows:
            raise ImapMailboxError("imap_search_failed")
        return [item for item in rows[0].split() if item]

    @staticmethod
    def _fetch_header(client, uid: bytes) -> bytes:
        status, rows = client.uid("fetch", uid, "(BODY.PEEK[HEADER])")
        if status != "OK":
            raise ImapMailboxError("imap_message_header_fetch_failed")
        raw = _extract_fetch_literal(rows)
        if len(raw) > 128 * 1024:
            raise ImapMailboxError("imap_message_header_too_large")
        return raw

    @staticmethod
    def _fetch_body_parts(client, uid: bytes) -> tuple[list[_ImapBodyPart], str]:
        status, rows = client.uid("fetch", uid, "(BODYSTRUCTURE)")
        if status != "OK":
            raise ImapMailboxError("imap_bodystructure_fetch_failed")
        structure = _extract_bodystructure(rows)
        parts = _collect_body_parts(structure)
        if not parts:
            raise ImapMailboxError("imap_bodystructure_invalid")

        safe_text = [part for part in parts if part.is_safe_text]
        total_declared = sum(part.size_bytes for part in safe_text)
        if total_declared > MAX_IMAP_TEXT_BODY_BYTES:
            raise ImapMailboxError("imap_text_body_too_large")

        plain: list[str] = []
        html: list[str] = []
        actual_bytes = 0
        for part in safe_text:
            query = f"(BODY.PEEK[{part.section}])"
            status, body_rows = client.uid("fetch", uid, query)
            if status != "OK":
                raise ImapMailboxError("imap_text_part_fetch_failed")
            raw = _extract_fetch_literal(body_rows)
            actual_bytes += len(raw)
            if actual_bytes > MAX_IMAP_TEXT_BODY_BYTES:
                raise ImapMailboxError("imap_text_body_too_large")
            value = _decode_text_part(raw, part).strip()
            if not value:
                continue
            if part.content_type == "text/plain":
                plain.append(value)
            elif part.content_type == "text/html":
                html.append(value)
        body = "\n\n".join(plain or html).strip()
        return parts, body

    def _normalize_inbound(
        self,
        *,
        header: bytes,
        parts: list[_ImapBodyPart],
        body: str,
        uid: bytes,
        folder: str,
        uid_validity: str,
    ) -> InboundMailEnvelope:
        try:
            message = BytesParser(policy=policy.default).parsebytes(header)
        except Exception as exc:
            raise ImapMailboxError("imap_message_header_parse_failed") from exc
        sender_address, sender_name = _sender(message)
        to_addresses = _addresses(message, ("To",))
        cc_addresses = _addresses(message, ("Cc",))
        bcc_addresses = _addresses(message, ("Bcc",))
        recipients = list(
            dict.fromkeys([*to_addresses, *cc_addresses, *bcc_addresses])
        )
        attachments = [
            InboundAttachmentMetadata(
                name=(part.filename or "attachment")[:512],
                content_type=part.content_type,
                size_bytes=part.size_bytes,
                kind="file",
                is_inline=part.disposition == "inline",
            )
            for part in parts
            if not part.is_safe_text
        ]
        message_id = (message.get("Message-ID") or "").strip() or None
        external_id = message_id or f"uid:{uid_validity}:{uid.decode('ascii', errors='replace')}"
        in_reply_to = (message.get("In-Reply-To") or "").strip() or None
        return InboundMailEnvelope(
            external_message_id=external_id[:500],
            provider_name=IMAP_PROVIDER_NAME,
            mailbox_id=self.credential.mailbox_id,
            sender_address=sender_address,
            sender_name=sender_name,
            recipient_addresses=recipients,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            bcc_addresses=bcc_addresses,
            subject=str(message.get("Subject") or "").strip() or None,
            body_text=body,
            raw_body_sha256=(
                hashlib.sha256(body.encode("utf-8")).hexdigest()
                if body
                else None
            ),
            received_at=_message_datetime(message),
            in_reply_to_message_id=in_reply_to,
            has_attachments=bool(attachments),
            attachment_manifest=attachments[:25],
            attachment_manifest_truncated=len(attachments) > 25,
            source="email",
        )

    def _sent_folder(self, client) -> str | None:
        status, rows = client.list()
        if status != "OK" or rows is None:
            raise ImapMailboxError("imap_folder_list_failed")
        fallbacks: list[str] = []
        for raw in rows:
            if not isinstance(raw, bytes):
                continue
            parsed = _folder_name(raw)
            if parsed is None:
                continue
            flags, name = parsed
            if b"\\Sent" in flags:
                return name
            lowered = name.casefold()
            if any(marker in lowered for marker in ("sent", "gönder", "gonder")):
                fallbacks.append(name)
        return fallbacks[0] if fallbacks else None


    def get_message(
        self,
        external_message_id: str,
    ) -> InboundMailEnvelope:
        external_id = str(external_message_id or "").strip()
        if not external_id:
            raise ValueError("IMAP message id is required.")
        client = self._connect()
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapMailboxError("imap_inbox_readonly_select_failed")
            uid_validity = self._uid_validity(client)
            uid: bytes | None = None
            if external_id.startswith("uid:"):
                parts = external_id.split(":", 2)
                if len(parts) != 3 or parts[1] != uid_validity or not parts[2]:
                    raise ImapMailboxError("imap_message_identity_stale")
                uid = parts[2].encode("ascii", errors="strict")
            else:
                status, rows = client.uid(
                    "search", None, "HEADER", "Message-ID", external_id
                )
                if status != "OK" or not rows:
                    raise ImapMailboxError("imap_message_search_failed")
                matches = [item for item in rows[0].split() if item]
                if len(matches) != 1:
                    raise ImapMailboxError("imap_message_identity_ambiguous")
                uid = matches[0]

            header = self._fetch_header(client, uid)
            parts, body = self._fetch_body_parts(client, uid)
            return self._normalize_inbound(
                header=header,
                parts=parts,
                body=body,
                uid=uid,
                folder="INBOX",
                uid_validity=uid_validity,
            )
        finally:
            self._close(client)

    def list_inbox_messages(self, *, limit: int) -> list[InboundMailEnvelope]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= 100):
            raise ValueError("IMAP inbox limit must be between 1 and 100.")
        self.last_message_rejections = []
        client = self._connect()
        accepted: list[InboundMailEnvelope] = []
        try:
            status, _ = client.select("INBOX", readonly=True)
            if status != "OK":
                raise ImapMailboxError("imap_inbox_readonly_select_failed")
            uid_validity = self._uid_validity(client)
            uids = self._search_uids(client)[-limit:]
            for uid in reversed(uids):
                source = f"uid:{uid_validity}:{uid.decode('ascii', errors='replace')}"
                try:
                    header = self._fetch_header(client, uid)
                    parts, body = self._fetch_body_parts(client, uid)
                    accepted.append(
                        self._normalize_inbound(
                            header=header,
                            parts=parts,
                            body=body,
                            uid=uid,
                            folder="INBOX",
                            uid_validity=uid_validity,
                        )
                    )
                except ImapMailboxError as exc:
                    self.last_message_rejections.append(
                        ImapMessageRejection(
                            external_message_id=source,
                            received_at="unavailable",
                            reason_code=exc.code,
                        )
                    )
        finally:
            self._close(client)
        return accepted

    def list_relationship_history(
        self, *, start_at: datetime, end_at: datetime, max_messages: int = 5000
    ) -> list[HistoricalMailMessage]:
        if start_at.tzinfo is None or end_at.tzinfo is None:
            raise ValueError("Historical IMAP range requires timezone-aware timestamps.")
        start = start_at.astimezone(timezone.utc)
        end = end_at.astimezone(timezone.utc)
        if end <= start:
            raise ValueError("Historical IMAP end_at must be after start_at.")
        if isinstance(max_messages, bool) or not isinstance(max_messages, int) or not (
            1 <= max_messages <= MAX_IMAP_HISTORY_MESSAGES
        ):
            raise ValueError(
                f"Historical IMAP max_messages must be between 1 and {MAX_IMAP_HISTORY_MESSAGES}."
            )
        self.last_message_rejections = []
        client = self._connect()
        collected: dict[str, HistoricalMailMessage] = {}
        try:
            sent_folder = self._sent_folder(client)
            folders = ["INBOX"] + ([sent_folder] if sent_folder else [])
            quota = max(1, max_messages // len(folders))
            for folder in folders:
                if len(collected) >= max_messages:
                    break
                status, _ = client.select(folder, readonly=True)
                if status != "OK":
                    continue
                uid_validity = self._uid_validity(client)
                uids = self._search_uids(client, start_at=start, end_at=end)
                for uid in uids[-quota:]:
                    if len(collected) >= max_messages:
                        break
                    source = f"imap:{folder}:{uid_validity}:{uid.decode('ascii', errors='replace')}"
                    try:
                        header = self._fetch_header(client, uid)
                        parts, body = self._fetch_body_parts(client, uid)
                        envelope = self._normalize_inbound(
                            header=header,
                            parts=parts,
                            body=body,
                            uid=uid,
                            folder=folder,
                            uid_validity=uid_validity,
                        )
                        sent_at = envelope.received_at
                        if sent_at is None or not (start <= sent_at < end):
                            continue
                        if not envelope.sender_address or not envelope.recipient_addresses:
                            continue
                        collected[source] = HistoricalMailMessage(
                            source_reference=source,
                            sent_at=sent_at,
                            sender_address=envelope.sender_address,
                            recipient_addresses=envelope.recipient_addresses,
                            subject=envelope.subject or "",
                            body_text=envelope.body_text[:50_000],
                            in_reply_to_reference=envelope.in_reply_to_message_id,
                            source="authorized_mailbox",
                        )
                    except (ImapMailboxError, ValueError) as exc:
                        self.last_message_rejections.append(
                            ImapMessageRejection(
                                external_message_id=source,
                                received_at="unavailable",
                                reason_code=getattr(exc, "code", "imap_history_message_invalid"),
                            )
                        )
        finally:
            self._close(client)
        return sorted(collected.values(), key=lambda item: (item.sent_at, item.source_reference))
