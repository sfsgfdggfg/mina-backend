from __future__ import annotations

from pydantic import BaseModel

from src.core.master_data_repository import MasterDataRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository


class CustomerQuoteRecipientAuthority(BaseModel):
    case_id: str
    allowed_recipient_emails: list[str]
    default_recipient_email: str | None = None
    source: str = "customer_quote_recipient_authority"

    def allows(self, email: str) -> bool:
        return email.strip().casefold() in set(self.allowed_recipient_emails)


def build_customer_quote_recipient_authority(
    *,
    quote_case_repository: QuoteCaseRepository,
    supplier_repository: SupplierRFQRepository,
    master_repository: MasterDataRepository | None,
    case_id: str,
) -> CustomerQuoteRecipientAuthority:
    quote_case = quote_case_repository.get(case_id)
    if quote_case is None:
        raise LookupError(f"Quote case not found: {case_id}")

    ordered: list[str] = []

    def add(value: str | None) -> None:
        normalized = (value or "").strip().casefold()
        if normalized and "@" in normalized and normalized not in ordered:
            ordered.append(normalized)

    if quote_case.supplier_rfq_workflow_id:
        workflow = supplier_repository.get_workflow(
            quote_case.supplier_rfq_workflow_id
        )
        if workflow is not None:
            add(workflow.sender_address)

    profile = None
    if master_repository is not None and quote_case.shipment.customer_name:
        profile = master_repository.find_customer_by_name(
            quote_case.shipment.customer_name
        )
    if profile is not None and profile.active:
        for contact in profile.contacts:
            if contact.active:
                add(contact.email)
        for address in profile.trusted_sender_addresses:
            add(address)

    return CustomerQuoteRecipientAuthority(
        case_id=quote_case.case_id,
        allowed_recipient_emails=ordered,
        default_recipient_email=(ordered[0] if ordered else None),
    )
