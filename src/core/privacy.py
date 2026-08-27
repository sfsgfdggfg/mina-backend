from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from src.core.mail import InboundMailEnvelope


PRIVACY_TRANSFORM_VERSION = "p1.28-v3"

_EMAIL_RE = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_TURKEY_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+90|0090|0)?\s*"
    r"(?:\(?[2-5]\d{2}\)?[\s.-]*)"
    r"\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"
)
_INTERNATIONAL_PHONE_RE = re.compile(
    r"(?<![\w\d])"
    r"(?:\+|00)\d{1,3}"
    r"(?:[\s()./-]*\d){7,14}"
    r"(?!\d)"
)
_IBAN_RE = re.compile(
    r"(?i)\b[A-Z]{2}\d{2}"
    r"(?:[\s-]?[A-Z0-9]){11,30}\b"
)

_SIGNATURE_MARKERS = {
    "saygılarımla",
    "saygilarimla",
    "iyi çalışmalar",
    "iyi calismalar",
    "best regards",
    "kind regards",
    "regards",
    "thanks and regards",
    "sent from my iphone",
    "sent from my android",
}


class PrivacyBoundaryError(ValueError):
    pass


_PRIVACY_CONSTRUCTION_TOKEN = object()


class PrivacySafeText(str):
    def __new__(
        cls,
        value: str,
        *,
        raw_body_sha256: str,
        transform_version: str,
        _token: object | None = None,
    ):
        if _token is not _PRIVACY_CONSTRUCTION_TOKEN:
            raise PrivacyBoundaryError(
                "PrivacySafeText may only be created by the approved "
                "privacy transform."
            )

        obj = super().__new__(cls, value)
        obj.raw_body_sha256 = raw_body_sha256
        obj.transform_version = transform_version
        return obj


@dataclass(frozen=True)
class PrivacyTransformResult:
    safe_text: PrivacySafeText
    raw_body_sha256: str
    transform_version: str


def fingerprint_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_quoted_reply(text: str) -> str:
    lines = text.splitlines()

    for index, line in enumerate(lines):
        normalized = line.strip().lower()

        if index == 0:
            continue

        if normalized in {
            "-----original message-----",
            "-----orijinal ileti-----",
            "-----forwarded message-----",
            "-----iletilen ileti-----",
        }:
            return "\n".join(
                lines[:index]
            ).rstrip()

        if (
            normalized.startswith("on ")
            and normalized.endswith(" wrote:")
        ):
            return "\n".join(
                lines[:index]
            ).rstrip()

        if (
            normalized.endswith(" tarihinde şunu yazdı:")
            and _EMAIL_RE.search(line)
        ):
            return "\n".join(
                lines[:index]
            ).rstrip()

        remaining = [
            item.strip().lower()
            for item in lines[
                index : index + 5
            ]
        ]

        if normalized.startswith("from:"):
            if (
                any(
                    item.startswith("sent:")
                    for item in remaining
                )
                and any(
                    item.startswith("to:")
                    for item in remaining
                )
                and any(
                    item.startswith("subject:")
                    for item in remaining
                )
            ):
                return "\n".join(
                    lines[:index]
                ).rstrip()

        if normalized.startswith("kimden:"):
            if (
                any(
                    item.startswith(
                        "gönderilme tarihi:"
                    )
                    or item.startswith(
                        "gonderilme tarihi:"
                    )
                    for item in remaining
                )
                and any(
                    item.startswith("kime:")
                    for item in remaining
                )
                and any(
                    item.startswith("konu:")
                    for item in remaining
                )
            ):
                return "\n".join(
                    lines[:index]
                ).rstrip()

    return text


def _strip_signature(text: str) -> str:
    lines = text.splitlines()
    if len(lines) < 3:
        return text

    earliest_signature_index = max(2, len(lines) // 2)

    for index in range(earliest_signature_index, len(lines)):
        normalized = lines[index].strip().lower().rstrip(",;:")
        if normalized in _SIGNATURE_MARKERS:
            return "\n".join(lines[:index]).rstrip()

    return text


def minimize_text(text: str) -> str:
    minimized = _strip_quoted_reply(text)
    minimized = _strip_signature(minimized)
    minimized = _EMAIL_RE.sub(
        "<EMAIL_REDACTED>",
        minimized,
    )
    minimized = _TURKEY_PHONE_RE.sub(
        "<PHONE_REDACTED>",
        minimized,
    )
    minimized = _INTERNATIONAL_PHONE_RE.sub(
        "<PHONE_REDACTED>",
        minimized,
    )
    minimized = _IBAN_RE.sub(
        "<IBAN_REDACTED>",
        minimized,
    )
    lines = [line.rstrip() for line in minimized.splitlines()]
    return "\n".join(lines).strip()


def prepare_privacy_safe_text(raw_text: str) -> PrivacyTransformResult:
    raw_body_sha256 = fingerprint_text(raw_text)
    minimized = minimize_text(raw_text)

    if not minimized:
        raise PrivacyBoundaryError(
            "Privacy transform removed the entire inbound message."
        )

    safe_text = PrivacySafeText(
        minimized,
        raw_body_sha256=raw_body_sha256,
        transform_version=PRIVACY_TRANSFORM_VERSION,
        _token=_PRIVACY_CONSTRUCTION_TOKEN,
    )
    return PrivacyTransformResult(
        safe_text=safe_text,
        raw_body_sha256=raw_body_sha256,
        transform_version=PRIVACY_TRANSFORM_VERSION,
    )


def prepare_inbound_mail_for_processing(
    mail: InboundMailEnvelope,
) -> tuple[InboundMailEnvelope, PrivacySafeText]:
    transformed = prepare_privacy_safe_text(mail.body_text)
    safe_subject = minimize_text(mail.subject) if mail.subject else None

    safe_mail = mail.model_copy(
        update={
            "body_text": str(transformed.safe_text),
            "subject": safe_subject,
            "sender_name": None,
            "raw_body_sha256": transformed.raw_body_sha256,
            "privacy_transformed": True,
            "privacy_transform_version": transformed.transform_version,
        }
    )

    return safe_mail, transformed.safe_text
