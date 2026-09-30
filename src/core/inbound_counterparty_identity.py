from __future__ import annotations

import re


_SIGNOFF_MARKERS = {
    "saygılarımla", "saygilarimla", "iyi çalışmalar", "iyi calismalar",
    "best regards", "kind regards", "regards", "thanks and regards",
    "srdacan pozdrav", "srdačan pozdrav",
}
_BUSINESS_RE = re.compile(
    r"(?ix)\b(?:lojistik|logistics|transport(?:ation)?|shipping|freight|"
    r"forwarding|nakliyat|taşımacılık|tasimacilik|ticaret|sanayi)\b"
)
_LEGAL_SUFFIX_RE = re.compile(
    r"(?ix)\b(?:gmbh|llc|ltd\.?|limited|inc\.?|corp(?:oration)?\.?|plc|"
    r"s\.?r\.?l\.?|d\.?o\.?o\.?|b\.?v\.?|n\.?v\.?|"
    r"s\.?p\.?a\.?|a\.?ş\.?|a\.?s\.?)\b"
)
_OPERATIONAL_WORD_RE = re.compile(
    r"(?i)\b(?:quote|quotation|teklif|fiyat|rica|request|yük|yuk|loading|"
    r"delivery|teslim|pickup|kg|ton|palet|pallet|ftl|ltl)\b"
)
_OPERATIONAL_SUFFIX_RE = re.compile(
    r"(?ix)(?:\b\d+(?:[.,]\d+)?\s*(?:kg|ton|cbm|m3|m³)\b)"
    r"|(?:\b\d+\s*(?:palet|pallets?|koli|pcs?|pieces?)\b)"
    r"|(?:\b(?:pickup|loading|delivery|yükleme|yukleme|teslim|commodity|"
    r"ürün|urun|equipment|ekipman|ready\s*date|cargo\s*ready)\b\s*[:\-])"
    r"|(?:\b(?:reefer|tenteli|curtainsider|FTL|LTL|ADR)\b)"
)
_LABEL_RE = re.compile(
    r"(?i)^(?:address|adres|phone|telefon|mobile|gsm|e-?mail|web|website|fax)\s*:"
)


def _clean_line(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _is_signoff_line(line: str) -> bool:
    normalized = _clean_line(line).casefold().rstrip(",;:")
    if normalized in _SIGNOFF_MARKERS:
        return True
    segments = [segment.strip(" ,;:") for segment in re.split(r"[/|]", normalized)]
    return any(segment in _SIGNOFF_MARKERS for segment in segments if segment)


def message_body_before_signature(text: str) -> str:
    lines = str(text or "").splitlines()
    for index, line in enumerate(lines):
        if index < 2 or not _is_signoff_line(line):
            continue
        suffix_index = next(
            (
                candidate
                for candidate in range(index + 1, len(lines))
                if _OPERATIONAL_SUFFIX_RE.search(lines[candidate])
            ),
            None,
        )
        prefix = lines[:index]
        if suffix_index is None:
            return "\n".join(prefix).rstrip()
        return "\n".join([*prefix, "", *lines[suffix_index:]]).rstrip()
    return str(text or "")


def infer_sender_organization_name(body_text: str) -> str | None:
    """Return only a high-confidence organization name from sender evidence."""
    lines = [_clean_line(line) for line in str(body_text or "").splitlines()]
    signoff_index = next(
        (index for index, line in enumerate(lines) if index >= 2 and _is_signoff_line(line)),
        None,
    )
    search_ranges = []
    if signoff_index is not None:
        search_ranges.append(lines[signoff_index + 1 : signoff_index + 12])
    search_ranges.append(lines)

    for range_index, candidates in enumerate(search_ranges):
        signature_context = signoff_index is not None and range_index == 0
        for line in candidates:
            if not line or len(line) > 120 or _LABEL_RE.search(line):
                continue
            if "@" in line or line.startswith("http") or "<EMAIL_" in line:
                continue
            has_legal_suffix = bool(_LEGAL_SUFFIX_RE.search(line))
            has_business_term = bool(_BUSINESS_RE.search(line))
            if not (has_legal_suffix or has_business_term):
                continue
            if not signature_context and not has_legal_suffix:
                words = re.findall(r"[\wÀ-ž]+", line)
                if len(words) > 6 or _OPERATIONAL_WORD_RE.search(line):
                    continue
            if line.count(".") > 6 or line.count(",") > 3:
                continue
            return line.strip(" -–—,;:") or None
    return None


def value_supported_before_signature(value: str | None, body_text: str) -> bool:
    if not value:
        return False
    prefix = message_body_before_signature(body_text)
    if prefix == str(body_text or ""):
        return True
    tokens = [
        token.casefold()
        for token in re.findall(r"[\wÀ-ž]+", str(value))
        if len(token) >= 3
    ]
    if not tokens:
        return False
    normalized_prefix = prefix.casefold()
    matched = sum(token in normalized_prefix for token in tokens)
    return matched >= max(1, (2 * len(tokens) + 2) // 3)
