from __future__ import annotations

from typing import Protocol

from src.core.operational_shift_open_acceptance_receipt import OperationalShiftOpenAcceptanceReceipt


class OperationalShiftOpenAcceptanceReceiptRepository(Protocol):
    def save_if_absent(self, receipt: OperationalShiftOpenAcceptanceReceipt) -> OperationalShiftOpenAcceptanceReceipt: ...
    def get(self, receipt_id: str) -> OperationalShiftOpenAcceptanceReceipt | None: ...
    def list_all(self) -> list[OperationalShiftOpenAcceptanceReceipt]: ...


class InMemoryOperationalShiftOpenAcceptanceReceiptRepository:
    def __init__(self) -> None:
        self._receipts: dict[str, OperationalShiftOpenAcceptanceReceipt] = {}

    def save_if_absent(self, receipt: OperationalShiftOpenAcceptanceReceipt) -> OperationalShiftOpenAcceptanceReceipt:
        existing = self._receipts.get(receipt.receipt_id)
        if existing is not None:
            return existing.model_copy(deep=True)
        stored = receipt.model_copy(deep=True)
        self._receipts[receipt.receipt_id] = stored
        return stored.model_copy(deep=True)

    def get(self, receipt_id: str) -> OperationalShiftOpenAcceptanceReceipt | None:
        receipt = self._receipts.get(receipt_id)
        return None if receipt is None else receipt.model_copy(deep=True)

    def list_all(self) -> list[OperationalShiftOpenAcceptanceReceipt]:
        return [item.model_copy(deep=True) for item in self._receipts.values()]
