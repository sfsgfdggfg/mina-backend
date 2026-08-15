from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.models import CustomerQuote, QuoteDraft, Shipment, SupplierQuote
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_service import approve_quote, reject_quote
from src.core.quote_case import QuoteCase
from src.core.quote_revision_service import (
    QuoteRevisionTransitionError,
    revise_quote_case,
)
from src.core.sqlite_repositories import (
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
)


def evaluate_quote_revision_regressions() -> dict:
    failures: list[str] = []

    if not route_allowed("POST", "/quote-cases/case-1/revise"):
        failures.append("controlled pilot revision route is not allowed")

    with TemporaryDirectory(prefix="minai-quote-revision-") as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"
        store = SQLitePilotStore(db_path, run_id="quote-revision-a")
        approvals = SQLiteQuoteApprovalRepository(store)
        cases = SQLiteQuoteCaseRepository(store)

        supplier_quote = SupplierQuote(
            supplier_name="Revision Carrier",
            cost=2000,
            currency="EUR",
            transit_time="5-7 days",
            equipment_type="Tenteli",
        )
        customer_quote = CustomerQuote(
            supplier_cost=2000,
            markup_type="percentage",
            markup_value=15,
            final_price=2300,
            currency="EUR",
        )
        quote_draft = QuoteDraft(
            subject="Hamburg navlun teklifimiz",
            body=(
                "Merhaba Ahmet Bey, 2300 EUR. "
                "Transit: 5-7 days. Ekipman: Tenteli."
            ),
        )
        approval = QuoteApproval(
            quote_snapshot=QuoteApprovalSnapshot.from_quote(
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            )
        )
        quote_case = QuoteCase(
            shipment=Shipment(customer_name="Revision Customer"),
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
            quote_approval=approval,
        )
        approvals.save(approval)
        cases.save(quote_case)

        friendly_body = (
            "Ahmet selam, Hamburg isi icin 2300 EUR ile ilerleyebiliriz. "
            "Transit: 5-7 days. Ekipman: Tenteli."
        )
        first = revise_quote_case(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
            expected_approval_id=approval.approval_id,
            subject="Ahmet selam - Hamburg isi",
            body=friendly_body,
            edited_by="Pilot Operator One",
        )
        if first.quote_case.quote_draft.body != friendly_body:
            failures.append("full-body operator edit was not preserved")
        if first.previous_approval.approval_status != "invalidated":
            failures.append("pending approval was not invalidated")
        if first.new_approval.approval_status != "pending":
            failures.append("revision did not create a fresh pending approval")
        if first.revision.consistency_warnings:
            failures.append("tone-only edit produced commercial warnings")

        approved = approve_quote(
            repository=approvals,
            approval_id=first.new_approval.approval_id,
            approved_by="Pilot Operator One",
        )
        second = revise_quote_case(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
            expected_approval_id=approved.approval_id,
            subject="Hamburg - guncel teklif",
            body=(
                "Ahmet selam, Hamburg isi icin 2200 EUR yaziyorum. "
                "Transit: 5-7 days. Ekipman: Tenteli."
            ),
            final_price=2250,
            edited_by="Pilot Operator One",
        )
        if second.previous_approval.approval_status != "invalidated":
            failures.append("approved quote remained approved after edit")
        if second.quote_case.customer_quote.final_price != 2250:
            failures.append("manual sales price was not persisted")
        if second.quote_case.customer_quote.markup_type != "manual":
            failures.append("manual sales price did not use manual markup mode")
        if not any(
            "does not contain the current structured customer price" in warning
            for warning in second.revision.consistency_warnings
        ):
            failures.append("text/structured price mismatch was not warned")
        if second.quote_case.quote_send_safety.can_send:
            failures.append("revised quote was sendable before fresh approval")

        try:
            revise_quote_case(
                quote_case_repository=cases,
                approval_repository=approvals,
                case_id=quote_case.case_id,
                expected_approval_id=first.new_approval.approval_id,
                subject="Stale edit",
                body="Stale edit body",
                edited_by="Pilot Operator One",
            )
        except QuoteRevisionTransitionError:
            pass
        else:
            failures.append("stale revision was accepted")

        rejected = reject_quote(
            repository=approvals,
            approval_id=second.new_approval.approval_id,
            rejection_reason="Rewrite customer wording.",
            rejected_by="Pilot Operator One",
        )
        third = revise_quote_case(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
            expected_approval_id=rejected.approval_id,
            subject="Hamburg - son teklif",
            body=(
                "Ahmet selam, son haliyle teklifimiz 2.250 EUR. "
                "Transit: 5-7 days. Ekipman: Tenteli."
            ),
            edited_by="Pilot Operator One",
        )
        if third.previous_approval.approval_status != "rejected":
            failures.append("rejected decision history was rewritten")
        if third.new_approval.approval_status != "pending":
            failures.append("rejected quote could not start a new revision")

        restarted = SQLitePilotStore(db_path, run_id="quote-revision-b")
        durable_case = SQLiteQuoteCaseRepository(restarted).get(quote_case.case_id)
        if durable_case is None or len(durable_case.quote_revisions) != 3:
            failures.append("revision history did not survive restart")
        elif durable_case.quote_draft.body != third.quote_case.quote_draft.body:
            failures.append("latest revised email did not survive restart")

    return {
        "name": "Editable customer quote revisions",
        "passed": len(failures) == 0,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_quote_revision_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
