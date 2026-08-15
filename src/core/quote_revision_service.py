from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from src.core.models import CustomerQuote, QuoteDraft
from src.core.quote_approval import (
    QuoteApproval,
    QuoteApprovalSnapshot,
)
from src.core.quote_approval_repository import (
    QuoteApprovalRepository,
)
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_revision import QuoteRevision
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.sqlite_repositories import atomic_repository_transaction


class QuoteRevisionNotFoundError(LookupError):
    pass


class QuoteRevisionTransitionError(ValueError):
    pass


class QuoteRevisionResult(BaseModel):
    quote_case: QuoteCase
    revision: QuoteRevision
    previous_approval: QuoteApproval
    new_approval: QuoteApproval
    source: str = "quote_revision_service"


def _amount_forms(value: float) -> set[str]:
    amount = Decimal(str(value))

    forms = {
        format(amount, "f"),
        format(amount, ".2f"),
        format(amount, ".2f").replace(".", ","),
    }

    grouped = format(amount, ",.2f")
    forms.add(grouped)
    forms.add(
        grouped
        .replace(",", "#")
        .replace(".", ",")
        .replace("#", ".")
    )

    if amount == amount.to_integral_value():
        integer_value = int(amount)
        forms.add(str(integer_value))
        grouped_integer = format(integer_value, ",d")
        forms.add(grouped_integer)
        forms.add(grouped_integer.replace(",", "."))

    return {item for item in forms if item}


def _contains_amount(text: str, value: float) -> bool:
    return any(
        token in text
        for token in _amount_forms(value)
    )


def _build_consistency_warnings(
    *,
    quote_case: QuoteCase,
    revised_quote_draft: QuoteDraft,
    revised_customer_quote: CustomerQuote,
) -> list[str]:
    warnings: list[str] = []

    previous_customer_quote = quote_case.customer_quote
    previous_quote_draft = quote_case.quote_draft
    supplier_quote = quote_case.supplier_quote

    if (
        previous_customer_quote is not None
        and previous_customer_quote.final_price
        != revised_customer_quote.final_price
    ):
        warnings.append(
            "Operator changed the customer sales price "
            f"from {previous_customer_quote.final_price:g} "
            f"to {revised_customer_quote.final_price:g} "
            f"{revised_customer_quote.currency}; "
            "fresh final approval is required."
        )

    if (
        previous_customer_quote is not None
        and previous_quote_draft is not None
        and _contains_amount(
            previous_quote_draft.body,
            previous_customer_quote.final_price,
        )
        and not _contains_amount(
            revised_quote_draft.body,
            revised_customer_quote.final_price,
        )
    ):
        warnings.append(
            "Revised email body does not contain the "
            "current structured customer price."
        )

    currency = revised_customer_quote.currency.strip().upper()

    if (
        currency
        and previous_quote_draft is not None
        and currency in previous_quote_draft.body.upper()
        and currency not in revised_quote_draft.body.upper()
    ):
        warnings.append(
            "Revised email changed or removed the "
            "structured quote currency wording."
        )

    if supplier_quote is not None:
        transit = (supplier_quote.transit_time or "").strip()

        if (
            transit
            and previous_quote_draft is not None
            and transit.lower()
            in previous_quote_draft.body.lower()
            and transit.lower()
            not in revised_quote_draft.body.lower()
        ):
            warnings.append(
                "Revised email changed or removed "
                "the source-backed supplier transit wording."
            )

        equipment = (
            supplier_quote.equipment_type or ""
        ).strip()

        if (
            equipment
            and previous_quote_draft is not None
            and equipment.lower()
            in previous_quote_draft.body.lower()
            and equipment.lower()
            not in revised_quote_draft.body.lower()
        ):
            warnings.append(
                "Revised email changed or removed "
                "the source-backed equipment wording."
            )

    return warnings


def _invalidate_for_revision(
    approval: QuoteApproval,
    *,
    edited_by: str,
    edited_at: datetime,
) -> QuoteApproval:
    if approval.approval_status not in {
        "pending",
        "approved",
    }:
        return approval

    return QuoteApproval.model_validate(
        {
            **approval.model_dump(),
            "approval_status": "invalidated",
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "invalidated_by": edited_by,
            "invalidated_at": edited_at,
        }
    )


def revise_quote_case(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    expected_approval_id: str,
    subject: str,
    body: str,
    edited_by: str,
    final_price: Optional[float] = None,
    operator_note: Optional[str] = None,
    edited_at: Optional[datetime] = None,
) -> QuoteRevisionResult:
    normalized_subject = subject.strip()
    normalized_operator = edited_by.strip()
    normalized_expected_approval = expected_approval_id.strip()
    normalized_note = (
        operator_note.strip()
        if operator_note and operator_note.strip()
        else None
    )

    if not normalized_subject:
        raise ValueError(
            "Quote email subject must not be empty."
        )

    if not body.strip():
        raise ValueError(
            "Quote email body must not be empty."
        )

    if not normalized_operator:
        raise ValueError(
            "Quote revision operator is required."
        )

    if not normalized_expected_approval:
        raise ValueError(
            "Expected approval ID is required."
        )

    if final_price is not None and final_price <= 0:
        raise ValueError(
            "Revised final price must be positive."
        )

    now = edited_at or datetime.utcnow()

    with atomic_repository_transaction(
        quote_case_repository,
        approval_repository,
    ):
        quote_case = quote_case_repository.get(case_id)

        if quote_case is None:
            raise QuoteRevisionNotFoundError(
                f"Quote case not found: {case_id}"
            )

        if (
            quote_case.supplier_quote is None
            or quote_case.customer_quote is None
            or quote_case.quote_draft is None
            or quote_case.quote_approval is None
        ):
            raise QuoteRevisionTransitionError(
                "Quote case is not complete enough "
                "to create an operator revision."
            )

        current_approval_id = (
            quote_case.quote_approval.approval_id
        )

        if (
            current_approval_id
            != normalized_expected_approval
        ):
            raise QuoteRevisionTransitionError(
                "Quote revision is stale because "
                "the current approval has changed."
            )

        current_approval = approval_repository.get(
            current_approval_id
        )

        if current_approval is None:
            raise QuoteRevisionNotFoundError(
                "Current quote approval record was not found."
            )

        previous_customer_quote = quote_case.customer_quote
        previous_quote_draft = quote_case.quote_draft

        revised_customer_quote = previous_customer_quote

        if (
            final_price is not None
            and final_price
            != previous_customer_quote.final_price
        ):
            revised_customer_quote = (
                CustomerQuote.model_validate(
                    {
                        **previous_customer_quote.model_dump(),
                        "markup_type": "manual",
                        "markup_value": final_price,
                        "final_price": final_price,
                    }
                )
            )

        revised_quote_draft = QuoteDraft(
            subject=normalized_subject,
            body=body,
        )

        changed_fields: list[str] = []

        if (
            previous_quote_draft.subject
            != revised_quote_draft.subject
        ):
            changed_fields.append("subject")

        if (
            previous_quote_draft.body
            != revised_quote_draft.body
        ):
            changed_fields.append("body")

        if (
            previous_customer_quote.final_price
            != revised_customer_quote.final_price
        ):
            changed_fields.append("final_price")

        if not changed_fields:
            raise QuoteRevisionTransitionError(
                "Quote revision does not change "
                "the current customer email or price."
            )

        warnings = _build_consistency_warnings(
            quote_case=quote_case,
            revised_quote_draft=revised_quote_draft,
            revised_customer_quote=revised_customer_quote,
        )

        previous_approval = _invalidate_for_revision(
            current_approval,
            edited_by=normalized_operator,
            edited_at=now,
        )

        if previous_approval != current_approval:
            previous_approval = approval_repository.save(
                previous_approval
            )

        new_approval = QuoteApproval(
            quote_snapshot=QuoteApprovalSnapshot.from_quote(
                supplier_quote=quote_case.supplier_quote,
                customer_quote=revised_customer_quote,
                quote_draft=revised_quote_draft,
            )
        )

        new_approval = approval_repository.save(
            new_approval
        )

        new_send_safety = evaluate_quote_send_safety(
            approval=new_approval,
            supplier_quote=quote_case.supplier_quote,
            customer_quote=revised_customer_quote,
            quote_draft=revised_quote_draft,
            regulatory_compliance=(
                quote_case.regulatory_compliance
            ),
        )

        revision = QuoteRevision(
            revision_number=(
                len(quote_case.quote_revisions) + 1
            ),
            previous_approval_id=(
                current_approval.approval_id
            ),
            new_approval_id=new_approval.approval_id,
            previous_quote_draft=previous_quote_draft,
            revised_quote_draft=revised_quote_draft,
            previous_customer_quote=(
                previous_customer_quote
            ),
            revised_customer_quote=(
                revised_customer_quote
            ),
            changed_fields=changed_fields,
            consistency_warnings=warnings,
            operator_note=normalized_note,
            edited_by=normalized_operator,
            edited_at=now,
        )

        updated_case = quote_case.model_copy(
            update={
                "customer_quote": revised_customer_quote,
                "quote_draft": revised_quote_draft,
                "quote_approval": new_approval,
                "quote_send_safety": new_send_safety,
                "quote_revisions": [
                    *quote_case.quote_revisions,
                    revision,
                ],
                "updated_at": now,
            }
        )

        updated_case = quote_case_repository.save(
            QuoteCase.model_validate(
                updated_case.model_dump()
            )
        )

    return QuoteRevisionResult(
        quote_case=updated_case,
        revision=revision,
        previous_approval=previous_approval,
        new_approval=new_approval,
    )
