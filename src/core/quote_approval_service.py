from __future__ import annotations

from datetime import datetime
from typing import Optional

from src.core.quote_approval import QuoteApproval
from src.core.quote_approval_repository import (
    QuoteApprovalRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction


class QuoteApprovalNotFoundError(ValueError):
    pass


class QuoteApprovalTransitionError(ValueError):
    pass


def _load_approval(
    repository: QuoteApprovalRepository,
    approval_id: str,
) -> QuoteApproval:
    approval = repository.get(approval_id)

    if approval is None:
        raise QuoteApprovalNotFoundError(
            f"Quote approval not found: {approval_id}"
        )

    return approval


def approve_quote(
    repository: QuoteApprovalRepository,
    approval_id: str,
    approved_by: str,
    approved_at: Optional[datetime] = None,
) -> QuoteApproval:
    with atomic_repository_transaction(repository):
        approval = _load_approval(repository, approval_id)

        if approval.approval_status != "pending":
            raise QuoteApprovalTransitionError(
                "Only pending approval can be approved."
            )

        normalized_approved_by = approved_by.strip()

        if not normalized_approved_by:
            raise ValueError("approved_by must not be empty.")

        updated = approval.model_copy(
            update={
                "approval_status": "approved",
                "approved_by": normalized_approved_by,
                "approved_at": approved_at or datetime.utcnow(),
                "rejection_reason": None,
            }
        )

        updated = QuoteApproval.model_validate(updated.model_dump())
        return repository.save(updated)


def reject_quote(
    repository: QuoteApprovalRepository,
    approval_id: str,
    rejection_reason: str,
    rejected_by: str,
    rejected_at: Optional[datetime] = None,
) -> QuoteApproval:
    with atomic_repository_transaction(repository):
        approval = _load_approval(repository, approval_id)

        if approval.approval_status != "pending":
            raise QuoteApprovalTransitionError(
                "Only pending approval can be rejected."
            )

        normalized_reason = rejection_reason.strip()
        normalized_rejected_by = rejected_by.strip()

        if not normalized_reason:
            raise ValueError(
                "rejection_reason must not be empty."
            )

        if not normalized_rejected_by:
            raise ValueError("rejected_by must not be empty.")

        updated = approval.model_copy(
            update={
                "approval_status": "rejected",
                "approved_by": None,
                "approved_at": None,
                "rejected_by": normalized_rejected_by,
                "rejected_at": rejected_at or datetime.utcnow(),
                "rejection_reason": normalized_reason,
                "invalidated_by": None,
                "invalidated_at": None,
            }
        )

        updated = QuoteApproval.model_validate(updated.model_dump())
        return repository.save(updated)


def invalidate_quote_approval(
    repository: QuoteApprovalRepository,
    approval_id: str,
    invalidated_by: str,
    invalidated_at: Optional[datetime] = None,
) -> QuoteApproval:
    with atomic_repository_transaction(repository):
        approval = _load_approval(repository, approval_id)

        if approval.approval_status not in {
            "pending",
            "approved",
        }:
            raise QuoteApprovalTransitionError(
                "Only pending or approved approval can be invalidated."
            )

        normalized_invalidated_by = invalidated_by.strip()

        if not normalized_invalidated_by:
            raise ValueError("invalidated_by must not be empty.")

        updated = approval.model_copy(
            update={
                "approval_status": "invalidated",
                "approved_by": None,
                "approved_at": None,
                "rejected_by": None,
                "rejected_at": None,
                "rejection_reason": None,
                "invalidated_by": normalized_invalidated_by,
                "invalidated_at": invalidated_at or datetime.utcnow(),
            }
        )

        updated = QuoteApproval.model_validate(updated.model_dump())
        return repository.save(updated)
