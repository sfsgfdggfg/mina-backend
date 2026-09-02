from __future__ import annotations

from typing import Protocol

from src.core.operational_shift_close_receipt import OperationalShiftCloseReceipt


class OperationalShiftCloseReceiptRepository(Protocol):
    def save_if_absent(self, receipt: OperationalShiftCloseReceipt) -> OperationalShiftCloseReceipt: ...
    def get(self, receipt_id: str) -> OperationalShiftCloseReceipt | None: ...
    def list_all(self) -> list[OperationalShiftCloseReceipt]: ...


class InMemoryOperationalShiftCloseReceiptRepository:
    def __init__(self) -> None:
        self._receipts: dict[str, OperationalShiftCloseReceipt] = {}

    def save_if_absent(self, receipt: OperationalShiftCloseReceipt) -> OperationalShiftCloseReceipt:
        existing = self._receipts.get(receipt.receipt_id)
        if existing is not None:
            return existing.model_copy(deep=True)
        stored = receipt.model_copy(deep=True)
        self._receipts[receipt.receipt_id] = stored
        return stored.model_copy(deep=True)

    def get(self, receipt_id: str) -> OperationalShiftCloseReceipt | None:
        receipt = self._receipts.get(receipt_id)
        return None if receipt is None else receipt.model_copy(deep=True)

    def list_all(self) -> list[OperationalShiftCloseReceipt]:
        return [item.model_copy(deep=True) for item in self._receipts.values()]
