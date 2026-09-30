from __future__ import annotations

from src.core.mail import InboundMailEnvelope

_FREIGHT_TERMS = (
    "navlun", "freight", "taşıma", "tasima", "yük", "yuk", "yükleme", "yukleme",
    "teslim", "pickup", "delivery", "loading", "truck", "tır", "tir", "ftl", "ltl",
    "parsiyel", "partial", "konteyner", "container", "palet", "pallet", "kg", "ton",
    "door to door", "depo", "warehouse", "ithalat", "ihracat", "import", "export",
)

_QUOTE_REQUEST_TERMS = (
    "maliyet teklifi", "fiyat teklifi", "navlun teklifi", "teklif iletebilir misiniz",
    "teklif verebilir misiniz", "teklifinizi rica", "fiyat iletebilir misiniz",
    "fiyat verebilir misiniz", "fiyat rica", "navlun rica", "fiyat alabilir miyiz",
    "fiyat alabilir miyim", "teklif alabilir miyiz", "teklif alabilir miyim",
    "please quote", "rate request", "quotation request", "request for quote", "can you quote",
    "could you quote", "please provide a rate", "please provide your rate", "rfq",
)


def _message_text(mail: InboundMailEnvelope) -> str:
    return " ".join(f"{mail.subject or ''}\n{mail.body_text or ''}".strip().casefold().split())


def looks_like_freight_quote_request(mail: InboundMailEnvelope) -> bool:
    """Detect an inbound request asking the agency to quote a shipment.

    This classifies the transaction expressed by this message; it deliberately does
    not classify the sender's company as permanently customer or supplier.
    """
    text = _message_text(mail)
    freight_signal_count = sum(term in text for term in _FREIGHT_TERMS)
    quote_request = any(term in text for term in _QUOTE_REQUEST_TERMS)
    return quote_request and freight_signal_count >= 1
