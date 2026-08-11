from __future__ import annotations

from typing import Protocol

from src.core.supplier_response_ingestion import (
    InboundSupplierReply,
    SupplierResponseExtraction,
)


class SupplierResponseParser(Protocol):
    """Extract commercial fields only; never select or mutate an RFQ."""

    def parse(
        self,
        reply: InboundSupplierReply,
    ) -> SupplierResponseExtraction:
        ...
