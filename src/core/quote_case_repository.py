from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, Protocol

from src.core.quote_case import QuoteCase


class QuoteCaseRepository(Protocol):
    def save(
        self,
        quote_case: QuoteCase,
    ) -> QuoteCase:
        ...

    def save_many(
        self,
        quote_cases: Iterable[QuoteCase],
    ) -> list[QuoteCase]:
        ...

    def get(
        self,
        case_id: str,
    ) -> Optional[QuoteCase]:
        ...

    def list_all(self) -> list[QuoteCase]:
        ...


class InMemoryQuoteCaseRepository:
    def __init__(self) -> None:
        self._cases: dict[str, QuoteCase] = {}

    def save(
        self,
        quote_case: QuoteCase,
    ) -> QuoteCase:
        self._cases[quote_case.case_id] = quote_case
        return quote_case

    def save_many(
        self,
        quote_cases: Iterable[QuoteCase],
    ) -> list[QuoteCase]:
        saved = []

        for quote_case in quote_cases:
            saved.append(self.save(quote_case))

        return saved

    def get(
        self,
        case_id: str,
    ) -> Optional[QuoteCase]:
        return self._cases.get(case_id)

    def list_all(self) -> list[QuoteCase]:
        return list(self._cases.values())
