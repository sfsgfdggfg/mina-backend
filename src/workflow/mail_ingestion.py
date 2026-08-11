from __future__ import annotations

from collections.abc import Callable

from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.pipeline import process_shipment


def process_customer_inquiry_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable[[str], Shipment],
    rfq_repository: SupplierRFQRepository | None = None,
    approval_repository: QuoteApprovalRepository | None = None,
    quote_case_repository: QuoteCaseRepository | None = None,
) -> dict:
    """Map normalized customer mail into the unchanged shipment workflow."""

    shipment = shipment_parser(mail.body_text)
    return process_shipment(
        shipment=shipment,
        email_text=mail.body_text,
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
    )
