from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from src.ai.supplier_response_parser import (
    SupplierResponseParser,
    SupplierResponseParserUnavailableError,
)
from src.core.mail import InboundMailEnvelope
from src.core.relative_dates import infer_supplier_vehicle_available_date
from src.core.privacy import (
    fingerprint_text,
    prepare_privacy_safe_text,
)
from src.core.supplier_response_ingestion import (
    SupplierReplyIngestionResult,
    SupplierResponseExtraction,
    correlate_supplier_reply,
)
from src.core.supplier_commercial_safety import parse_transit_time
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQNotFoundError,
    SupplierRFQResponseError,
    SupplierRFQTransitionError,
    attach_supplier_rfq_response,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQResponseError,
    SupplierRFQRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
)


class SupplierReplyIngestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reply: InboundMailEnvelope
    extracted_response: Optional[dict[str, Any]] = None


_PRICE_ONLY_REPLY_PATTERN = re.compile(
    r"^\s*(?P<amount>[0-9][0-9., ]*)\s*"
    r"(?P<currency>EUR|USD|GBP|TRY)\s*[.!]?\s*$",
    flags=re.IGNORECASE,
)

_TRANSIT_ONLY_REPLY_PATTERN = re.compile(
    r"^\s*\d+(?:\s*[-–—]\s*\d+)?\s*"
    r"(?:business\s*days?|working\s*days?|iş\s*günü|is\s*gunu|"
    r"days?|gün|gun|hours?|hrs?|saat|weeks?|hafta)\s*[.!]?\s*$",
    flags=re.IGNORECASE,
)


def _normalized_price_amount(value: str) -> float | None:
    compact = value.replace(" ", "")
    if not compact or not compact[0].isdigit():
        return None

    separators = [separator for separator in (".", ",") if separator in compact]
    if len(separators) == 2:
        decimal_separator = max(separators, key=compact.rfind)
        thousands_separator = "," if decimal_separator == "." else "."
        compact = compact.replace(thousands_separator, "")
        compact = compact.replace(decimal_separator, ".")
    elif len(separators) == 1:
        separator = separators[0]
        parts = compact.split(separator)
        if len(parts) > 2:
            if all(len(part) == 3 for part in parts[1:]):
                compact = "".join(parts)
            else:
                return None
        elif len(parts) == 2:
            left, right = parts
            if len(right) == 3 and 1 <= len(left) <= 3:
                compact = left + right
            elif 1 <= len(right) <= 2:
                compact = left + "." + right
            else:
                return None

    try:
        amount = Decimal(compact)
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return float(amount)


def _deterministic_price_only_extraction(
    reply_text: str,
) -> SupplierResponseExtraction | None:
    match = _PRICE_ONLY_REPLY_PATTERN.fullmatch(reply_text)
    if match is None:
        return None
    amount = _normalized_price_amount(match.group("amount"))
    if amount is None:
        return None
    return SupplierResponseExtraction(
        status="quoted",
        cost=amount,
        currency=match.group("currency").upper(),
    )


def _deterministic_transit_only_extraction(
    reply_text: str,
) -> SupplierResponseExtraction | None:
    normalized = reply_text.strip()
    if _TRANSIT_ONLY_REPLY_PATTERN.fullmatch(normalized) is None:
        return None
    if parse_transit_time(normalized) is None:
        return None
    return SupplierResponseExtraction(transit_time=normalized.rstrip(".!"))


def _merge_clarification_extraction(
    *,
    draft,
    extraction: SupplierResponseExtraction,
    repository: SupplierRFQRepository,
) -> tuple[SupplierResponseExtraction, list[str], datetime | None]:
    if draft.status != "clarification_required":
        return extraction, [], None
    if extraction.status in {"declined", "no_capacity", "needs_clarification"}:
        return extraction, [], None
    prior_quotes = [
        response
        for response in repository.list_responses(draft.rfq_id)
        if response.status == "quoted"
    ]
    if not prior_quotes:
        return extraction, [], None
    prior = max(prior_quotes, key=lambda item: item.received_at)
    commercial_fields = (
        "cost",
        "currency",
        "transit_time",
        "validity_date",
        "vehicle_available_date",
        "equipment_type",
        "pricing_basis",
        "included_costs",
        "excluded_costs",
        "notes",
    )
    has_follow_up_fact = any(
        extraction.field_state(field_name) != "not_provided"
        for field_name in commercial_fields
    )
    if extraction.status is None and not has_follow_up_fact:
        return extraction, [], None

    update = {"status": "quoted"}
    inherited_fields: list[str] = []
    for field_name in commercial_fields:
        state = extraction.field_state(field_name)
        if state == "provided":
            update[field_name] = getattr(extraction, field_name)
        elif state == "uncertain":
            update[field_name] = None
        else:
            prior_value = getattr(prior, field_name)
            update[field_name] = prior_value
            if prior_value is not None:
                inherited_fields.append(field_name)
    update["uncertain_fields"] = list(extraction.uncertain_fields)
    return (
        SupplierResponseExtraction.model_validate(update),
        inherited_fields,
        prior.received_at,
    )


def _result_from_correlation(
    correlation,
    reply: InboundMailEnvelope,
) -> SupplierReplyIngestionResult:
    return SupplierReplyIngestionResult(
        status=correlation.status,
        reason=correlation.reason,
        rfq_id=correlation.rfq_id,
        correlation_method=correlation.method,
        external_message_id=reply.external_message_id,
    )


def _resolve_extraction(
    *,
    reply: InboundMailEnvelope,
    extracted_response: SupplierResponseExtraction | dict[str, Any] | None,
    parser: SupplierResponseParser | None,
) -> tuple[SupplierResponseExtraction | None, str | None, str | None]:
    if extracted_response is not None:
        try:
            extraction = SupplierResponseExtraction.model_validate(
                extracted_response
            )
        except ValidationError as exc:
            return None, "invalid_response", str(exc)
        return extraction, None, None

    try:
        safe_text = prepare_privacy_safe_text(
            reply.body_text
        ).safe_text
    except Exception:
        return (
            None,
            "parsing_failed",
            "Supplier response privacy transform failed.",
        )

    deterministic = _deterministic_price_only_extraction(str(safe_text))
    if deterministic is not None:
        return deterministic, None, None
    transit_only = _deterministic_transit_only_extraction(str(safe_text))
    if transit_only is not None:
        return transit_only, None, None

    if parser is None:
        return (
            None,
            "parsing_required",
            "No structured response or supplier response parser was provided.",
        )

    try:
        parsed = parser.parse(safe_text)
        extraction = SupplierResponseExtraction.model_validate(parsed)
        if extraction.vehicle_available_date is None:
            inferred_available = infer_supplier_vehicle_available_date(
                str(safe_text), reply.received_at
            )
            if inferred_available is not None:
                extraction = extraction.model_copy(
                    update={"vehicle_available_date": inferred_available}
                )
    except SupplierResponseParserUnavailableError:
        raise
    except Exception:
        return (
            None,
            "parsing_failed",
            "Supplier response parser failed or returned invalid output.",
        )
    return extraction, None, None


def _validate_required_extraction(
    extraction: SupplierResponseExtraction,
) -> tuple[str | None, str | None]:
    if extraction.field_state("status") == "uncertain":
        return "parsing_failed", "Supplier response status is uncertain."
    if extraction.status is None:
        return "invalid_response", "Supplier response status is required."
    if extraction.status == "quoted":
        uncertain_required = [
            field_name
            for field_name in ("cost", "currency")
            if extraction.field_state(field_name) == "uncertain"
        ]
        if uncertain_required:
            return (
                "parsing_failed",
                "Required quote fields are uncertain: "
                + ", ".join(uncertain_required),
            )
        missing_required = [
            field_name
            for field_name in ("cost", "currency")
            if extraction.field_state(field_name) == "not_provided"
        ]
        if missing_required:
            return (
                "invalid_response",
                "Quoted supplier response is missing required fields: "
                + ", ".join(missing_required),
            )
    return None, None


def supplier_message_is_exact_replay(
    *,
    reply: InboundMailEnvelope,
    repository: SupplierRFQRepository,
) -> bool:
    message_key = reply.message_deduplication_key

    if message_key is None:
        return False

    evidence = (
        repository.get_ingested_message_evidence(
            message_key
        )
    )

    if evidence is None:
        if repository.has_ingested_message(
            message_key
        ):
            raise (
                InboundMailIdempotencyConflictError(
                    "Previously ingested supplier "
                    "message lacks integrity evidence."
                )
            )
        return False

    incoming_hash = fingerprint_text(
        reply.body_text
    )

    if (
        evidence.get("body_sha256")
        != incoming_hash
        or evidence.get("sender_address")
        != reply.sender_address
    ):
        raise InboundMailIdempotencyConflictError(
            "Inbound supplier message ID was "
            "reused with different content or sender."
        )

    return True


def ingest_supplier_reply(
    *,
    reply: InboundMailEnvelope,
    repository: SupplierRFQRepository,
    extracted_response: SupplierResponseExtraction | dict[str, Any] | None = None,
    parser: SupplierResponseParser | None = None,
) -> SupplierReplyIngestionResult:
    message_key = reply.message_deduplication_key

    if supplier_message_is_exact_replay(
        reply=reply,
        repository=repository,
    ):
        return SupplierReplyIngestionResult(
            status="duplicate_response",
            reason=(
                "Inbound supplier message has "
                "already been ingested."
            ),
            external_message_id=(
                reply.external_message_id
            ),
        )

    correlation = correlate_supplier_reply(reply, repository)
    if correlation.status != "matched":
        if (
            correlation.status == "rfq_not_awaiting_response"
            and correlation.rfq_id
            and repository.list_responses(correlation.rfq_id)
        ):
            return SupplierReplyIngestionResult(
                status="duplicate_response",
                reason=(
                    "Supplier RFQ already has an attached response; "
                    "the inbound reply was not applied."
                ),
                rfq_id=correlation.rfq_id,
                correlation_method=correlation.method,
                external_message_id=reply.external_message_id,
            )
        return _result_from_correlation(correlation, reply)

    draft = repository.get_draft(correlation.rfq_id)
    if draft is None:
        return SupplierReplyIngestionResult(
            status="unresolved_rfq",
            reason="Correlated Supplier RFQ no longer exists.",
            external_message_id=reply.external_message_id,
        )

    extraction, extraction_status, extraction_reason = _resolve_extraction(
        reply=reply,
        extracted_response=extracted_response,
        parser=parser,
    )
    if extraction is None:
        return SupplierReplyIngestionResult(
            status=extraction_status,
            reason=extraction_reason or "Supplier response extraction failed.",
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )

    extraction, inherited_fields, prior_response_received_at = (
        _merge_clarification_extraction(
            draft=draft,
            extraction=extraction,
            repository=repository,
        )
    )

    validation_status, validation_reason = _validate_required_extraction(
        extraction
    )
    if validation_status:
        return SupplierReplyIngestionResult(
            status=validation_status,
            reason=validation_reason or "Supplier response is invalid.",
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )

    try:
        response = SupplierRFQResponse(
            rfq_id=draft.rfq_id,
            supplier_name=draft.supplier_name,
            rfq_priority=draft.priority,
            status=extraction.status,
            cost=extraction.cost,
            currency=extraction.currency,
            transit_time=extraction.transit_time,
            validity_date=extraction.validity_date,
            vehicle_available_date=extraction.vehicle_available_date,
            equipment_type=extraction.equipment_type,
            pricing_basis=extraction.pricing_basis,
            included_costs=extraction.included_costs,
            excluded_costs=extraction.excluded_costs,
            notes=extraction.notes,
            source=reply.source,
            received_at=reply.received_at or datetime.utcnow(),
            is_consolidated_follow_up=bool(inherited_fields),
            inherited_fields=inherited_fields,
            prior_response_received_at=prior_response_received_at,
        )
    except ValidationError as exc:
        return SupplierReplyIngestionResult(
            status="invalid_response",
            reason=str(exc),
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )

    try:
        with atomic_repository_transaction(repository):
            responded = attach_supplier_rfq_response(repository, response)
            if message_key:
                repository.record_ingested_message(
                    message_key,
                    body_sha256=fingerprint_text(
                        reply.body_text
                    ),
                    sender_address=(
                        reply.sender_address
                    ),
                )
    except DuplicateSupplierRFQResponseError as exc:
        return SupplierReplyIngestionResult(
            status="duplicate_response",
            reason=str(exc),
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )
    except SupplierRFQTransitionError as exc:
        return SupplierReplyIngestionResult(
            status="rfq_not_awaiting_response",
            reason=str(exc),
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )
    except SupplierRFQResponseError as exc:
        return SupplierReplyIngestionResult(
            status="invalid_response",
            reason=str(exc),
            rfq_id=draft.rfq_id,
            correlation_method=correlation.method,
            external_message_id=reply.external_message_id,
        )
    except SupplierRFQNotFoundError as exc:
        return SupplierReplyIngestionResult(
            status="unresolved_rfq",
            reason=str(exc),
            external_message_id=reply.external_message_id,
        )

    return SupplierReplyIngestionResult(
        status="response_attached",
        reason="Supplier response was validated and attached to the RFQ.",
        rfq_id=draft.rfq_id,
        correlation_method=correlation.method,
        external_message_id=reply.external_message_id,
        response=response,
        supplier_rfq=responded,
    )
