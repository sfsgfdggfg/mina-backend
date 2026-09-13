from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_table_review import AirRateTableReview, AirRateTableRowCandidate
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.attachment_safe_extraction import AttachmentSafeExtractionError, extract_verified_attachment
from src.core.mail import InboundAttachmentMetadata


class AirRateTableReviewNotFoundError(LookupError):
    pass


class AirRateTableReviewTransitionError(ValueError):
    pass


_BREAK_PATTERN = re.compile(
    r"(?P<min>\bMIN(?:IMUM)?\b)|(?P<plus>(?<!\w)\+\s*(?P<weight>[1-9][0-9]{0,3})(?:\s*KG\b)?)",
    re.I,
)
_CURRENCY_PATTERN = re.compile(r"^(USD|EUR|TRY|GBP|CHF|AED|SAR|JPY|CNY)$", re.I)
_NUMBER_PATTERN = re.compile(r"^[0-9]{1,6}(?:[.,][0-9]{1,4})?$")
_DEST_CODE_PATTERN = re.compile(r"^[A-Z]{3}$")
_BLOCKED_PREFIX_TOKENS = {
    "FSC", "SSC", "SURCHARGE", "SECURITY", "AWB", "HANDLING", "SCREENING",
    "RATE", "RATES", "ROUTING", "ROUTE", "TRANSIT", "FLIGHT", "NOTES", "NOTE",
    "MINIMUM", "FUEL", "WAR", "RISK", "VOLUMETRIC", "VOLUME", "DIM", "KG",
}


def _normalized_break(match: re.Match[str]) -> str:
    if match.group("min"):
        return "MIN"
    return f"+{int(match.group('weight'))}"


def _breaks_on_line(line: str, allowed: set[str]) -> list[str]:
    values: list[str] = []
    for match in _BREAK_PATTERN.finditer(line):
        value = _normalized_break(match)
        if value in allowed and value not in values:
            values.append(value)
    return values


def _parse_decimal_token(token: str) -> Decimal | None:
    if not _NUMBER_PATTERN.fullmatch(token):
        return None
    try:
        value = Decimal(token.replace(",", "."))
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0 or value > Decimal("1000000"):
        return None
    return value


def _candidate_id(*, line_number: int, destination: str, currency: str | None, rates: dict[str, Decimal]) -> str:
    serialized = "|".join(f"{key}={rates[key]}" for key in rates)
    payload = f"{line_number}\\0{destination}\\0{currency or ''}\\0{serialized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def detect_air_rate_table_candidates(
    text: str,
    *,
    confirmed_weight_breaks: list[str],
    confirmed_currencies: list[str],
) -> list[AirRateTableRowCandidate]:
    """Conservatively detect exact-width numeric rows under confirmed tariff headers."""
    allowed_breaks = set(confirmed_weight_breaks)
    allowed_currencies = {item.upper() for item in confirmed_currencies}
    active_breaks: list[str] | None = None
    active_currency: str | None = None
    candidates: list[AirRateTableRowCandidate] = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = " ".join(raw_line.strip().split())
        if not line:
            continue
        header_breaks = _breaks_on_line(line, allowed_breaks)
        if len(header_breaks) >= 2:
            active_breaks = header_breaks
            header_currencies = [token.upper() for token in line.split() if _CURRENCY_PATTERN.fullmatch(token)]
            explicit = [item for item in header_currencies if item in allowed_currencies]
            active_currency = explicit[0] if len(set(explicit)) == 1 else None
            continue
        if not active_breaks:
            continue

        tokens = line.split()
        explicit_currencies = [token.upper() for token in tokens if _CURRENCY_PATTERN.fullmatch(token)]
        explicit_currencies = [item for item in explicit_currencies if item in allowed_currencies]
        if len(set(explicit_currencies)) > 1:
            continue
        row_currency = explicit_currencies[0] if explicit_currencies else active_currency
        if row_currency is None and len(allowed_currencies) == 1:
            row_currency = next(iter(allowed_currencies))
        if row_currency is None and len(allowed_currencies) > 1:
            continue

        filtered_tokens = [token for token in tokens if token.upper() not in allowed_currencies]
        count = len(active_breaks)
        if len(filtered_tokens) <= count:
            continue
        numeric_tokens = filtered_tokens[-count:]
        parsed = [_parse_decimal_token(token) for token in numeric_tokens]
        if any(value is None for value in parsed):
            continue
        prefix = filtered_tokens[:-count]
        if not prefix or len(prefix) > 8 or not any(any(ch.isalpha() for ch in token) for token in prefix):
            continue
        uppercase_prefix = {token.upper().strip("():;,-") for token in prefix}
        if uppercase_prefix.intersection(_BLOCKED_PREFIX_TOKENS):
            continue
        destination = " ".join(prefix)
        if len(destination) > 160:
            continue
        destination_code = next(
            (token.upper() for token in reversed(prefix) if _DEST_CODE_PATTERN.fullmatch(token.upper())
             and token.upper() not in allowed_currencies),
            None,
        )
        rates = {key: value for key, value in zip(active_breaks, parsed) if value is not None}
        line_sha256 = hashlib.sha256(line.encode("utf-8")).hexdigest()
        candidates.append(AirRateTableRowCandidate(
            candidate_id=_candidate_id(
                line_number=line_number, destination=destination, currency=row_currency, rates=rates
            ),
            destination_label=destination,
            destination_code=destination_code,
            currency=row_currency,
            rates=rates,
            source_line_number=line_number,
            source_line_sha256=line_sha256,
        ))
        if len(candidates) >= 250:
            break
    return candidates


def create_air_rate_table_review(
    *,
    source_id: str,
    source_repository: AirShadowRepository,
    structure_repository: AirRateStructureReviewRepository,
    review_repository: AirRateTableReviewRepository,
    document_store: AirRateDocumentStore,
    requested_by: str,
) -> tuple[AirRateTableReview, bool]:
    existing = review_repository.find_by_source(source_id)
    if existing is not None:
        return existing, False
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirRateTableReviewNotFoundError(f"Air rate source not found: {source_id}")
    structure = structure_repository.find_by_source(source_id)
    if structure is None:
        raise AirRateTableReviewTransitionError("air_rate_structure_review_required")
    if structure.status != "completed":
        raise AirRateTableReviewTransitionError("air_rate_structure_review_must_be_completed")
    confirmed_breaks = [
        item.value for item in structure.candidates
        if item.kind == "weight_break" and item.status == "confirmed"
    ]
    if len(confirmed_breaks) < 2:
        raise AirRateTableReviewTransitionError("air_rate_table_requires_two_confirmed_weight_breaks")
    confirmed_currencies = [
        item.value for item in structure.candidates
        if item.kind == "currency" and item.status == "confirmed"
    ]

    content = document_store.read_verified_pdf(source.sha256_hex)
    metadata = InboundAttachmentMetadata(
        name=source.document_name,
        content_type="application/pdf",
        size_bytes=len(content),
        kind="file",
        is_inline=False,
    )
    try:
        artifact = extract_verified_attachment(
            metadata,
            content,
            expected_sha256_hex=source.sha256_hex,
            expected_profile="pdf",
        )
    except AttachmentSafeExtractionError as exc:
        raise AirRateTableReviewTransitionError(exc.code) from exc
    text = artifact.text or ""
    if not text:
        raise AirRateTableReviewTransitionError("air_rate_pdf_no_extractable_text")
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if text_sha256 != structure.extracted_text_sha256:
        raise AirRateTableReviewTransitionError("air_rate_extracted_text_changed_after_structure_review")

    candidates = detect_air_rate_table_candidates(
        text,
        confirmed_weight_breaks=confirmed_breaks,
        confirmed_currencies=confirmed_currencies,
    )
    review = AirRateTableReview(
        source_id=source.source_id,
        source_sha256=source.sha256_hex,
        structure_review_id=structure.review_id,
        extracted_text_sha256=text_sha256,
        weight_breaks=confirmed_breaks,
        candidates=candidates,
        status="pending" if candidates else "no_candidates",
        requested_by=requested_by,
    )
    return review_repository.create(review)


def decide_air_rate_table_row(
    *,
    review_id: str,
    candidate_id: str,
    decision: Literal["confirm", "reject"],
    review_note: str,
    reviewed_by: str,
    repository: AirRateTableReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateTableReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateTableReviewNotFoundError(f"Air rate table review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateTableReviewTransitionError("Air rate table row review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateTableReviewNotFoundError(f"Air rate table row candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "proposed":
        raise AirRateTableReviewTransitionError("Air rate table row is already reviewed.")
    timestamp = reviewed_at or datetime.now(timezone.utc)
    updated = candidate.model_copy(update={
        "status": "confirmed" if decision == "confirm" else "rejected",
        "reviewed_by": reviewed_by,
        "reviewed_at": timestamp,
        "review_note": note,
    })
    candidates = [item.model_copy(deep=True) for item in review.candidates]
    candidates[index] = updated
    remaining = sum(item.status == "proposed" for item in candidates)
    status = "completed" if remaining == 0 else "partially_reviewed"
    changed = review.model_copy(update={"candidates": candidates, "status": status})
    return repository.save(AirRateTableReview.model_validate(changed.model_dump()))


def build_air_rate_table_review_view(
    *,
    repository: AirRateTableReviewRepository,
    source_repository: AirShadowRepository,
) -> dict:
    reviews = sorted(repository.list_all(), key=lambda item: (item.created_at, item.review_id), reverse=True)
    rows = []
    for review in reviews:
        source = source_repository.get_rate_source(review.source_id)
        rows.append({
            **review.model_dump(mode="json"),
            "airline_name": None if source is None else source.airline_name,
            "document_name": None if source is None else source.document_name,
            "runtime_authoritative": False,
        })
    return {
        "reviews": rows,
        "ai_interpretation_enabled": False,
        "structured_numeric_reference_enabled": True,
        "pricing_authority_enabled": False,
        "quote_calculation_enabled": False,
    }
