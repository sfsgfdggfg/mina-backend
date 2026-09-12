from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Literal

from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_rate_structure_review import (
    AirRateStructureCandidate,
    AirRateStructureReview,
)
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.attachment_safe_extraction import (
    AttachmentSafeExtractionError,
    extract_verified_attachment,
)
from src.core.mail import InboundAttachmentMetadata


class AirRateStructureReviewNotFoundError(LookupError):
    pass


class AirRateStructureReviewTransitionError(ValueError):
    pass


_SURCHARGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("FSC", re.compile(r"\bFSC\b|FUEL\s+SURCHARGE|YAKIT\s+EK\s+[ÜU]CRET[Iİ]?", re.I)),
    ("SSC", re.compile(r"\bSSC\b", re.I)),
    ("SECURITY", re.compile(r"SECURITY(?:\s+SURCHARGE)?|G[ÜU]VENL[Iİ]K(?:\s+EK\s+[ÜU]CRET[Iİ]?)?", re.I)),
    ("AWB", re.compile(r"\bAWB\b|AIR\s+WAYBILL", re.I)),
    ("HANDLING", re.compile(r"\bHANDLING\b|ELLE[CÇ]LEME", re.I)),
    ("SCREENING", re.compile(r"\bSCREENING\b|X[- ]?RAY", re.I)),
    ("WAR_RISK", re.compile(r"WAR\s+RISK|SAVA[SŞ]\s+R[Iİ]SK", re.I)),
)
_CURRENCY_PATTERN = re.compile(r"(?<![A-Z])(USD|EUR|TRY|GBP|CHF|AED|SAR|JPY|CNY)(?![A-Z])", re.I)
_CARGO_HINT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("general_cargo", re.compile(r"GENERAL\s+CARGO|GENEL\s+KARGO", re.I)),
    ("dangerous_goods", re.compile(r"DANGEROUS\s+GOODS|TEHL[Iİ]KEL[Iİ]\s+MADDE|\bDGR\b", re.I)),
    ("perishable", re.compile(r"\bPERISHABLE\b|BOZULAB[Iİ]L[Iİ]R", re.I)),
    ("pharma", re.compile(r"\bPHARMA(?:CEUTICAL)?\b|[İI]LA[CÇ]", re.I)),
    ("valuable", re.compile(r"VALUABLE\s+CARGO|DE[GĞ]ERL[Iİ]\s+KARGO", re.I)),
    ("live_animal", re.compile(r"LIVE\s+ANIMAL|CANLI\s+HAYVAN", re.I)),
    ("oversize", re.compile(r"\bOVERSIZE(?:D)?\b|GABAR[Iİ]\s+DI[SŞ]I", re.I)),
)


def _candidate_id(kind: str, value: str) -> str:
    return hashlib.sha256(f"{kind}\0{value}".encode("utf-8")).hexdigest()[:24]


def detect_air_rate_structure_candidates(text: str) -> list[AirRateStructureCandidate]:
    """Detect structural labels only; never parse or persist tariff prices."""
    observations: dict[tuple[str, str], list[int]] = {}

    def record(kind: str, value: str, line_number: int) -> None:
        key = (kind, value)
        observations.setdefault(key, []).append(line_number)

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if re.search(r"\bMIN(?:IMUM)?\b", line, re.I):
            record("weight_break", "MIN", line_number)
        for match in re.finditer(r"(?<!\w)\+\s*([1-9][0-9]{0,3})(?:\s*KG\b)?", line, re.I):
            weight = int(match.group(1))
            if weight <= 5000:
                record("weight_break", f"+{weight}", line_number)
        for normalized, pattern in _SURCHARGE_PATTERNS:
            if pattern.search(line):
                record("surcharge_label", normalized, line_number)
        for match in _CURRENCY_PATTERN.finditer(line):
            record("currency", match.group(1).upper(), line_number)
        divisor_matches = set(
            match.group(1)
            for match in re.finditer(r"(?:/|÷)\s*([4-7]000)\b", line)
        )
        if re.search(r"DIM|VOLUMETRIC|VOLUME|HAC[Iİ]MSEL|DES[Iİ]", line, re.I):
            divisor_matches.update(
                match.group(1)
                for match in re.finditer(r"\b([4-7]000)\b", line)
            )
        for divisor in sorted(divisor_matches):
            record("volumetric_divisor", divisor, line_number)
        for normalized, pattern in _CARGO_HINT_PATTERNS:
            if pattern.search(line):
                record("cargo_scope_hint", normalized, line_number)

    candidates = []
    for (kind, value), lines in sorted(observations.items()):
        unique_lines = sorted(set(lines))
        candidates.append(
            AirRateStructureCandidate(
                candidate_id=_candidate_id(kind, value),
                kind=kind,
                value=value,
                occurrence_count=len(lines),
                source_line_numbers=unique_lines[:20],
            )
        )
    return candidates[:100]


def create_air_rate_structure_review(
    *,
    source_id: str,
    source_repository: AirShadowRepository,
    review_repository: AirRateStructureReviewRepository,
    document_store: AirRateDocumentStore,
    requested_by: str,
) -> tuple[AirRateStructureReview, bool]:
    existing = review_repository.find_by_source(source_id)
    if existing is not None:
        return existing, False
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirRateStructureReviewNotFoundError(f"Air rate source not found: {source_id}")
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
        raise AirRateStructureReviewTransitionError(exc.code) from exc
    text = artifact.text or ""
    if not text:
        raise AirRateStructureReviewTransitionError("air_rate_pdf_no_extractable_text")
    candidates = detect_air_rate_structure_candidates(text)
    review = AirRateStructureReview(
        source_id=source.source_id,
        source_sha256=source.sha256_hex,
        extracted_text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        extracted_character_count=artifact.character_count,
        candidates=candidates,
        status="pending" if candidates else "no_candidates",
        requested_by=requested_by,
    )
    return review_repository.create(review)


def decide_air_rate_structure_candidate(
    *,
    review_id: str,
    candidate_id: str,
    decision: Literal["confirm", "reject"],
    review_note: str,
    reviewed_by: str,
    repository: AirRateStructureReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateStructureReview:
    review = repository.get(review_id)
    if review is None:
        raise AirRateStructureReviewNotFoundError(f"Air rate structure review not found: {review_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateStructureReviewTransitionError("Air rate structure review note is required.")
    index = next((i for i, item in enumerate(review.candidates) if item.candidate_id == candidate_id), None)
    if index is None:
        raise AirRateStructureReviewNotFoundError(f"Air rate structure candidate not found: {candidate_id}")
    candidate = review.candidates[index]
    if candidate.status != "proposed":
        raise AirRateStructureReviewTransitionError("Air rate structure candidate is already reviewed.")
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
    return repository.save(AirRateStructureReview.model_validate(changed.model_dump()))


def build_air_rate_structure_review_view(
    *,
    repository: AirRateStructureReviewRepository,
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
        "raw_extracted_text_persisted": False,
        "pricing_authority_enabled": False,
    }
