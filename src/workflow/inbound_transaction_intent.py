from __future__ import annotations

import re

from src.core.mail import InboundMailEnvelope

_FREIGHT_TERMS = (
    "navlun", "freight", "taşıma", "tasima", "yük", "yuk", "yükleme", "yukleme",
    "teslim", "pickup", "delivery", "loading", "truck", "tır", "tir", "ftl", "ltl",
    "parsiyel", "partial", "konteyner", "container", "palet", "pallet", "kg", "ton",
    "door to door", "depo", "warehouse", "ithalat", "ihracat", "import", "export",
)

# Keep this list request-shaped. Bare nouns such as "navlun teklifi" are not
# enough: carrier circulars legitimately say "navlun teklifimiz" or present a
# quotation without asking the agency to quote anything.
_QUOTE_REQUEST_TERMS = (
    "teklifi iletebilir misiniz", "teklifi verebilir misiniz",
    "teklifi paylaşabilir misiniz", "teklifi paylasabilir misiniz",
    "teklifi rica", "teklif iletebilir misiniz", "teklif verebilir misiniz",
    "teklif paylaşabilir misiniz", "teklif paylasabilir misiniz",
    "teklifinizi rica", "fiyat iletebilir misiniz", "fiyat verebilir misiniz",
    "fiyat rica", "navlun rica", "fiyat alabilir miyiz", "fiyat alabilir miyim",
    "teklif alabilir miyiz", "teklif alabilir miyim", "teklif istiyoruz",
    "teklif istiyoruz", "fiyat istiyoruz", "fiyat istiyoruz",
    "please quote", "rate request", "quotation request", "request for quote",
    "can you quote", "could you quote", "please provide a rate",
    "please provide your rate", "rfq",
)

_SUBJECT_QUOTE_NOUNS = (
    "maliyet teklifi", "fiyat teklifi", "navlun teklifi",
    "freight quote", "rate quote", "quotation",
)

_URL_RE = re.compile(r"(?i)(?:https?://|www\.)\S+")
_MAILTO_RE = re.compile(r"(?i)mailto:\S+")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_CID_RE = re.compile(r"(?i)\bcid:[^\s>\]]+")


def _clean_text(value: str | None) -> str:
    text = str(value or "")
    # Tracking URLs frequently contain random token fragments such as RFQ, TIR,
    # KG or LTL. They are transport metadata, not authored intent.
    text = _URL_RE.sub(" ", text)
    text = _MAILTO_RE.sub(" ", text)
    text = _EMAIL_RE.sub(" ", text)
    text = _CID_RE.sub(" ", text)
    return " ".join(text.casefold().split())


def _contains_term(text: str, term: str) -> bool:
    pattern = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<!\w){pattern}(?!\w)", text, flags=re.UNICODE) is not None


def _message_text(mail: InboundMailEnvelope) -> str:
    return _clean_text(f"{mail.subject or ''}\n{mail.body_text or ''}")


def looks_like_freight_quote_request(mail: InboundMailEnvelope) -> bool:
    """Detect a message asking the agency to quote a freight movement.

    URL/email noise is removed before intent matching and short transport tokens
    use word boundaries. This prevents newsletters and tracking links from
    manufacturing RFQ/TIR/KG/LTL signals. The transaction expressed by the
    message is classified independently from the sender company's master role.
    """
    text = _message_text(mail)
    subject = _clean_text(mail.subject)
    freight_signal_count = sum(_contains_term(text, term) for term in _FREIGHT_TERMS)
    explicit_request = any(
        _contains_term(text, term) for term in _QUOTE_REQUEST_TERMS
    )
    terse_subject_request = any(
        _contains_term(subject, term) for term in _SUBJECT_QUOTE_NOUNS
    )
    return freight_signal_count >= 1 and (explicit_request or terse_subject_request)
