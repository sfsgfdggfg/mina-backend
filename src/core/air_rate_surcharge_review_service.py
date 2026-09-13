from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_surcharge_review import AirRateSurchargeCandidate, AirRateSurchargeReview
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.attachment_safe_extraction import AttachmentSafeExtractionError, extract_verified_attachment
from src.core.mail import InboundAttachmentMetadata


class AirRateSurchargeReviewNotFoundError(LookupError):
    pass


class AirRateSurchargeReviewTransitionError(ValueError):
    pass


_CURRENCY = r"USD|EUR|TRY|GBP|CHF|AED|SAR|JPY|CNY"
_CURRENCY_AMOUNT = re.compile(
    rf"(?<![A-Z])(?P<currency>{_CURRENCY})(?![A-Z])\s*[:=]?\s*(?P<amount>[0-9]{{1,6}}(?:[.,][0-9]{{1,4}})?)",
    re.I,
)
_AMOUNT_CURRENCY = re.compile(
    rf"(?P<amount>[0-9]{{1,6}}(?:[.,][0-9]{{1,4}})?)\s*(?P<currency>{_CURRENCY})(?![A-Z])",
    re.I,
)
_PER_KG = re.compile(r"(?:/\s*KG\b|\bPER\s+(?:KG|KILO)\b|\bKG\s+BA[SŞ]I\b)", re.I)
_FLAT = re.compile(
    r"(?:/\s*(?:AWB|HAWB|MAWB|SHIPMENT)\b|\bPER\s+(?:AWB|HAWB|MAWB|SHIPMENT)\b|\bSEVK[Iİ]YAT\s+BA[SŞ]I\b|\bG[ÖO]NDER[Iİ]\s+BA[SŞ]I\b)",
    re.I,
)
_PERCENTAGE = re.compile(r"%|\bPERCENT(?:AGE)?\b|\bY[ÜU]ZDE\b", re.I)
_SURCHARGE_PATTERNS: dict[str, re.Pattern[str]] = {
    "FSC": re.compile(r"\bFSC\b|FUEL\s+SURCHARGE|YAKIT\s+EK\s+[ÜU]CRET[Iİ]?", re.I),
    "SSC": re.compile(r"\bSSC\b", re.I),
    "SECURITY": re.compile(r"SECURITY(?:\s+SURCHARGE)?|G[ÜU]VENL[Iİ]K(?:\s+EK\s+[ÜU]CRET[Iİ]?)?", re.I),
    "AWB": re.compile(r"\bAWB\b|AIR\s+WAYBILL", re.I),
    "HANDLING": re.compile(r"\bHANDLING\b|ELLE[CÇ]LEME", re.I),
    "SCREENING": re.compile(r"\bSCREENING\b|X[- ]?RAY", re.I),
    "WAR_RISK": re.compile(r"WAR\s+RISK|SAVA[SŞ]\s+R[Iİ]SK", re.I),
}


def _parse_amount_currency(line: str) -> tuple[Decimal, str] | None:
    pairs: set[tuple[str, str]] = set()
    for pattern in (_CURRENCY_AMOUNT, _AMOUNT_CURRENCY):
        for match in pattern.finditer(line):
            pairs.add((match.group("currency").upper(), match.group("amount").replace(",", ".")))
    if len(pairs) != 1:
        return None
    currency, raw_amount = next(iter(pairs))
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount > Decimal("1000000"):
        return None
    return amount, currency


def _basis(line: str) -> Literal["flat", "per_kg"] | None:
    if _PERCENTAGE.search(line):
        return None
    per_kg = bool(_PER_KG.search(line))
    flat = bool(_FLAT.search(line))
    if per_kg == flat:
        return None
    return "per_kg" if per_kg else "flat"


def _candidate_id(*, code: str, amount: Decimal, currency: str, basis: str, line_number: int, line_sha256: str) -> str:
    payload = f"{code}|{amount}|{currency}|{basis}|{line_number}|{line_sha256}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def detect_air_rate_surcharge_candidates(
    text: str,
    *,
    confirmed_surcharge_lines: dict[str, list[int]],
) -> list[AirRateSurchargeCandidate]:
    """Extract only explicit amount+currency+unit surcharge rows from reviewed source lines."""
    lines = text.splitlines()
    candidates: list[AirRateSurchargeCandidate] = []
    seen: set[str] = set()
    for code, line_numbers in sorted(confirmed_surcharge_lines.items()):
        pattern = _SURCHARGE_PATTERNS.get(code)
        if pattern is None:
            continue
        for line_number in sorted(set(line_numbers)):
            if line_number < 1 or line_number > len(lines):
                continue
            line = " ".join(lines[line_number - 1].strip().split())
            if not line or not pattern.search(line):
                continue
            basis = _basis(line)
            parsed = _parse_amount_currency(line)
            if basis is None or parsed is None:
                continue
            amount, currency = parsed
            line_sha256 = hashlib.sha256(line.encode("utf-8")).hexdigest()
            candidate_id = _candidate_id(
                code=code,
                amount=amount,
                currency=currency,
                basis=basis,
                line_number=line_number,
                line_sha256=line_sha256,
            )
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            candidates.append(AirRateSurchargeCandidate(
                candidate_id=candidate_id,
                surcharge_code=code,
                amount=amount,
                currency=currency,
                basis=basis,
                source_line_number=line_number,
                source_line_sha256=line_sha256,
            ))
            if len(candidates) >= 100:
                return candidates
    return candidates


def create_air_rate_surcharge_review(
    *,
    source_id: str,
    source_repository: AirShadowRepository,
    structure_repository: AirRateStructureReviewRepository,
    review_repository: AirRateSurchargeReviewRepository,
    document_store: AirRateDocumentStore,
    requested_by: str,
) -> tuple[AirRateSurchargeReview, bool]:
    existing = review_repository.find_by_source(source_id)
    if existing is not None:
        return existing, False
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air rate source not found: {source_id}")
    structure = structure_repository.find_by_source(source_id)
    if structure is None:
        raise AirRateSurchargeReviewTransitionError("air_rate_structure_review_required")
    if structure.status != "completed":
        raise AirRateSurchargeReviewTransitionError("air_rate_structure_review_must_be_completed")
    confirmed = {
        item.value: list(item.source_line_numbers)
        for item in structure.candidates
        if item.kind == "surcharge_label" and item.status == "confirmed"
    }
    if not confirmed:
        raise AirRateSurchargeReviewTransitionError("air_rate_requires_confirmed_surcharge_label")

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
        raise AirRateSurchargeReviewTransitionError(exc.code) from exc
    text = artifact.text or ""
    if not text:
        raise AirRateSurchargeReviewTransitionError("air_rate_pdf_no_extractable_text")
    text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if text_sha256 != structure.extracted_text_sha256:
        raise AirRateSurchargeReviewTransitionError("air_rate_extracted_text_changed_after_structure_review")

    candidates = detect_air_rate_surcharge_candidates(text, confirmed_surcharge_lines=confirmed)
    review = AirRateSurchargeReview(
        source_id=source.source_id,
        source_sha256=source.sha256_hex,
        structure_review_id=structure.review_id,
        extracted_text_sha256=text_sha256,
        candidates=candidates,
        status="pending" if candidates else "no_candidates",
        requested_by=requested_by,
    )
    return review_repository.create(review)


def decide_air_rate_surcharge_candidate(
    *,
    review_id: str,
    candidate_id: str,
    decision: Literal["confirm", "reject"],
    review_note: str,
    reviewed_by: str,
    repository: AirRateSurchargeReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateSurchargeReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateSurchargeReviewTransitionError("Air surcharge review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "proposed":
        raise AirRateSurchargeReviewTransitionError("Air surcharge candidate is already reviewed.")
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
    return repository.save(AirRateSurchargeReview.model_validate(changed.model_dump()))


def decide_air_rate_surcharge_application_basis(
    *,
    review_id: str,
    candidate_id: str,
    application_basis: Literal["actual_weight", "chargeable_weight", "pivot_billed_weight", "flat"],
    review_note: str,
    reviewed_by: str,
    repository: AirRateSurchargeReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateSurchargeReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateSurchargeReviewTransitionError("Air surcharge application-basis review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "confirmed":
        raise AirRateSurchargeReviewTransitionError("Air surcharge candidate must be confirmed before application-basis review.")
    if candidate.application_basis is not None:
        raise AirRateSurchargeReviewTransitionError("Air surcharge application basis is already reviewed.")
    if candidate.basis == "flat" and application_basis != "flat":
        raise AirRateSurchargeReviewTransitionError("Flat surcharge requires flat application basis.")
    if candidate.basis == "per_kg" and application_basis not in {"actual_weight", "chargeable_weight", "pivot_billed_weight"}:
        raise AirRateSurchargeReviewTransitionError("Per-kg surcharge requires an explicit weight application basis.")
    timestamp = reviewed_at or datetime.now(timezone.utc)
    updated = candidate.model_copy(update={
        "application_basis": application_basis,
        "application_basis_reviewed_by": reviewed_by,
        "application_basis_reviewed_at": timestamp,
        "application_basis_review_note": note,
    })
    candidates = [item.model_copy(deep=True) for item in review.candidates]
    candidates[index] = updated
    changed = review.model_copy(update={"candidates": candidates})
    return repository.save(AirRateSurchargeReview.model_validate(changed.model_dump()))



def decide_air_rate_surcharge_applicability_scope(
    *,
    review_id: str,
    candidate_id: str,
    applicability_scope: Literal["source_wide", "destination_specific"],
    destination_code: str | None,
    review_note: str,
    reviewed_by: str,
    repository: AirRateSurchargeReviewRepository,
    table_repository: AirRateTableReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateSurchargeReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateSurchargeReviewTransitionError("Air surcharge applicability review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "confirmed":
        raise AirRateSurchargeReviewTransitionError("Air surcharge candidate must be confirmed before applicability review.")
    if candidate.application_basis is None:
        raise AirRateSurchargeReviewTransitionError("Air surcharge application basis must be reviewed before applicability review.")
    if candidate.applicability_scope is not None:
        raise AirRateSurchargeReviewTransitionError("Air surcharge applicability scope is already reviewed.")

    normalized_destination = None if destination_code is None else str(destination_code).strip().upper()
    if applicability_scope == "source_wide":
        if normalized_destination:
            raise AirRateSurchargeReviewTransitionError("Source-wide surcharge applicability cannot include a destination code.")
    elif applicability_scope == "destination_specific":
        if not normalized_destination or not re.fullmatch(r"[A-Z]{3}", normalized_destination):
            raise AirRateSurchargeReviewTransitionError("Destination-specific surcharge applicability requires a three-letter destination code.")
        table_review = table_repository.find_by_source(review.source_id)
        if table_review is None:
            raise AirRateSurchargeReviewTransitionError("air_rate_table_review_required_for_destination_scope")
        confirmed_codes = {
            item.destination_code
            for item in table_review.candidates
            if item.status == "confirmed" and item.destination_code
        }
        if normalized_destination not in confirmed_codes:
            raise AirRateSurchargeReviewTransitionError("destination_scope_requires_confirmed_tariff_row")
    else:
        raise AirRateSurchargeReviewTransitionError("Unsupported air surcharge applicability scope.")

    timestamp = reviewed_at or datetime.now(timezone.utc)
    updated = candidate.model_copy(update={
        "applicability_scope": applicability_scope,
        "applicability_destination_code": normalized_destination,
        "applicability_reviewed_by": reviewed_by,
        "applicability_reviewed_at": timestamp,
        "applicability_review_note": note,
    })
    candidates = [item.model_copy(deep=True) for item in review.candidates]
    candidates[index] = updated
    changed = review.model_copy(update={"candidates": candidates})
    return repository.save(AirRateSurchargeReview.model_validate(changed.model_dump()))


def decide_air_rate_surcharge_operational_conditions(
    *,
    review_id: str,
    candidate_id: str,
    cargo_applicability: Literal["source_scope", "general_cargo", "special_cargo"],
    routing_applicability: Literal["all_source_routings", "direct_only", "connecting_only", "via_airport"],
    via_airport: str | None,
    review_note: str,
    reviewed_by: str,
    repository: AirRateSurchargeReviewRepository,
    source_repository: AirShadowRepository,
    reviewed_at: datetime | None = None,
) -> AirRateSurchargeReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateSurchargeReviewTransitionError("Air surcharge operational-conditions review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air surcharge candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "confirmed" or candidate.application_basis is None or candidate.applicability_scope is None:
        raise AirRateSurchargeReviewTransitionError("Air surcharge prior reviews must be completed before operational conditions.")
    if candidate.cargo_applicability is not None or candidate.routing_applicability is not None:
        raise AirRateSurchargeReviewTransitionError("Air surcharge operational conditions are already reviewed.")
    source = source_repository.get_rate_source(review.source_id)
    if source is None:
        raise AirRateSurchargeReviewNotFoundError(f"Air rate source not found: {review.source_id}")
    if cargo_applicability == "source_scope":
        if source.cargo_scope == "unknown":
            raise AirRateSurchargeReviewTransitionError("Unknown source cargo scope cannot be accepted as source-scope evidence.")
    elif source.cargo_scope in {"general_cargo", "special_cargo"} and cargo_applicability != source.cargo_scope:
        raise AirRateSurchargeReviewTransitionError("Surcharge cargo applicability conflicts with immutable source cargo scope.")
    normalized_via = None if via_airport is None else str(via_airport).strip().upper()
    if routing_applicability == "via_airport":
        if not normalized_via or not re.fullmatch(r"[A-Z]{3}", normalized_via):
            raise AirRateSurchargeReviewTransitionError("Via-airport routing applicability requires a three-letter airport code.")
    elif normalized_via:
        raise AirRateSurchargeReviewTransitionError("Only via-airport routing applicability may carry an airport code.")
    timestamp = reviewed_at or datetime.now(timezone.utc)
    updated = candidate.model_copy(update={
        "cargo_applicability": cargo_applicability,
        "routing_applicability": routing_applicability,
        "routing_via_airport": normalized_via,
        "operational_conditions_reviewed_by": reviewed_by,
        "operational_conditions_reviewed_at": timestamp,
        "operational_conditions_review_note": note,
    })
    candidates = [item.model_copy(deep=True) for item in review.candidates]
    candidates[index] = updated
    changed = review.model_copy(update={"candidates": candidates})
    return repository.save(AirRateSurchargeReview.model_validate(changed.model_dump()))

def build_air_rate_surcharge_review_view(
    *,
    repository: AirRateSurchargeReviewRepository,
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
        "application_basis_review_enabled": True,
        "applicability_scope_review_enabled": True,
        "operational_conditions_review_enabled": True,
        "application_weight_authority_enabled": False,
        "calculation_consumption_enabled": False,
        "pricing_authority_enabled": False,
        "quote_calculation_enabled": False,
    }
