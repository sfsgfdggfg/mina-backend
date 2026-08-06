from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Protocol

from src.core.quote_approval import QuoteApproval


class QuoteApprovalRepository(Protocol):
    def save(
        self,
        approval: QuoteApproval,
    ) -> QuoteApproval:
        ...

    def save_many(
        self,
        approvals: Iterable[QuoteApproval],
    ) -> list[QuoteApproval]:
        ...

    def get(
        self,
        approval_id: str,
    ) -> Optional[QuoteApproval]:
        ...

    def list_all(self) -> list[QuoteApproval]:
        ...


class InMemoryQuoteApprovalRepository:
    def __init__(self) -> None:
        self._approvals: dict[str, QuoteApproval] = {}

    def save(
        self,
        approval: QuoteApproval,
    ) -> QuoteApproval:
        self._approvals[approval.approval_id] = approval
        return approval

    def save_many(
        self,
        approvals: Iterable[QuoteApproval],
    ) -> list[QuoteApproval]:
        saved = []

        for approval in approvals:
            saved.append(self.save(approval))

        return saved

    def get(
        self,
        approval_id: str,
    ) -> Optional[QuoteApproval]:
        return self._approvals.get(approval_id)

    def list_all(self) -> list[QuoteApproval]:
        return list(self._approvals.values())
