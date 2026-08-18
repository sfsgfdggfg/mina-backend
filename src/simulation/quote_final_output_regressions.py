from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

import src.api as controlled_api
from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    Shipment,
    SupplierQuote,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import (
    QuoteApproval,
    QuoteApprovalSnapshot,
)
from src.core.quote_approval_service import approve_quote
from src.core.quote_case import QuoteCase
from src.core.quote_final_output import (
    QuoteFinalOutputTransitionError,
    build_quote_final_output,
)
from src.core.quote_revision_service import revise_quote_case
from src.core.sqlite_repositories import (
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
)


def evaluate_quote_final_output_regressions() -> dict:
    failures: list[str] = []

    if not route_allowed(
        "GET",
        "/quote-cases/case-1/final-output",
    ):
        failures.append(
            "controlled pilot final-output route is not allowed"
        )

    route_paths = {
        route.path
        for route in controlled_api.app.routes
        if hasattr(route, "path")
    }
    if (
        "/quote-cases/{case_id}/final-output"
        not in route_paths
    ):
        failures.append(
            "final-output API route is not exposed"
        )

    with TemporaryDirectory(
        prefix="minai-final-quote-output-"
    ) as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"

        store = SQLitePilotStore(
            db_path,
            run_id="quote-final-output-a",
        )
        approvals = SQLiteQuoteApprovalRepository(store)
        cases = SQLiteQuoteCaseRepository(store)

        supplier_quote = SupplierQuote(
            supplier_name="Final Output Carrier",
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
                "Merhaba, Hamburg taşımanız için "
                "teklifimiz 2300 EUR."
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
            shipment=Shipment(
                customer_name="Final Output Customer"
            ),
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
            quote_approval=approval,
        )

        approvals.save(approval)
        cases.save(quote_case)

        with (
            patch.object(
                controlled_api,
                "quote_case_repository",
                cases,
            ),
            patch.object(
                controlled_api,
                "quote_approval_repository",
                approvals,
            ),
        ):
            try:
                controlled_api.get_quote_case_final_output(
                    "missing-case"
                )
            except HTTPException as exc:
                if exc.status_code != 404:
                    failures.append(
                        "missing final-output case did not return 404"
                    )
            else:
                failures.append(
                    "missing final-output case was accepted"
                )

            try:
                controlled_api.get_quote_case_final_output(
                    quote_case.case_id
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    failures.append(
                        "pending final-output API did not return 409"
                    )
            else:
                failures.append(
                    "pending final-output API was accepted"
                )

        try:
            build_quote_final_output(
                quote_case_repository=cases,
                approval_repository=approvals,
                case_id=quote_case.case_id,
            )
        except QuoteFinalOutputTransitionError:
            pass
        else:
            failures.append(
                "pending approval produced final output"
            )

        approved = approve_quote(
            repository=approvals,
            approval_id=approval.approval_id,
            approved_by="Pilot Operator One",
        )

        first_output = build_quote_final_output(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
        )

        with (
            patch.object(
                controlled_api,
                "quote_case_repository",
                cases,
            ),
            patch.object(
                controlled_api,
                "quote_approval_repository",
                approvals,
            ),
        ):
            api_output = (
                controlled_api.get_quote_case_final_output(
                    quote_case.case_id
                )
            )

        if api_output != first_output.model_dump():
            failures.append(
                "approved API output differs from service output"
            )

        if first_output.approval_id != approved.approval_id:
            failures.append(
                "final output did not use current approval"
            )

        if first_output.approved_by != "Pilot Operator One":
            failures.append(
                "final output lost approval operator identity"
            )

        if first_output.approved_at != approved.approved_at:
            failures.append(
                "final output lost approval timestamp"
            )

        if first_output.subject != quote_draft.subject:
            failures.append(
                "final output subject differs from current case"
            )

        if first_output.body != quote_draft.body:
            failures.append(
                "final output body differs from current case"
            )

        if first_output.final_price != 2300:
            failures.append(
                "final output price differs from current case"
            )

        if first_output.currency != "EUR":
            failures.append(
                "final output currency differs from current case"
            )

        if (
            first_output.delivery_mode
            != "manual_external_operation"
        ):
            failures.append(
                "final output delivery mode is not manual"
            )

        if first_output.automated_send_performed is not False:
            failures.append(
                "final output claims automated delivery"
            )

        revised = revise_quote_case(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
            expected_approval_id=approved.approval_id,
            subject="Hamburg - güncel teklif",
            body=(
                "Merhaba, Hamburg taşımanız için "
                "güncel teklifimiz 2250 EUR."
            ),
            final_price=2250,
            edited_by="Pilot Operator One",
            operator_note="Commercial revision.",
        )

        old_approval = approvals.get(approved.approval_id)

        if (
            old_approval is None
            or old_approval.approval_status
            != "invalidated"
        ):
            failures.append(
                "revision did not invalidate old approval authority"
            )

        try:
            build_quote_final_output(
                quote_case_repository=cases,
                approval_repository=approvals,
                case_id=quote_case.case_id,
            )
        except QuoteFinalOutputTransitionError:
            pass
        else:
            failures.append(
                "revised quote produced output before fresh approval"
            )

        with (
            patch.object(
                controlled_api,
                "quote_case_repository",
                cases,
            ),
            patch.object(
                controlled_api,
                "quote_approval_repository",
                approvals,
            ),
        ):
            try:
                controlled_api.get_quote_case_final_output(
                    quote_case.case_id
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    failures.append(
                        "revised pending API did not return 409"
                    )
            else:
                failures.append(
                    "revised pending API produced final output"
                )

        fresh_approval = approve_quote(
            repository=approvals,
            approval_id=revised.new_approval.approval_id,
            approved_by="Pilot Operator Two",
        )

        revised_output = build_quote_final_output(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=quote_case.case_id,
        )

        with (
            patch.object(
                controlled_api,
                "quote_case_repository",
                cases,
            ),
            patch.object(
                controlled_api,
                "quote_approval_repository",
                approvals,
            ),
        ):
            revised_api_output = (
                controlled_api.get_quote_case_final_output(
                    quote_case.case_id
                )
            )

        if (
            revised_api_output
            != revised_output.model_dump()
        ):
            failures.append(
                "fresh approved API output is not current revision"
            )

        if (
            revised_output.approval_id
            != fresh_approval.approval_id
        ):
            failures.append(
                "revised output used stale approval"
            )

        if revised_output.approved_by != "Pilot Operator Two":
            failures.append(
                "revised output lost fresh approver identity"
            )

        if revised_output.revision_number != 1:
            failures.append(
                "final output revision number is incorrect"
            )

        if (
            revised_output.subject
            != "Hamburg - güncel teklif"
        ):
            failures.append(
                "revised final subject is not current"
            )

        if (
            revised_output.body
            != (
                "Merhaba, Hamburg taşımanız için "
                "güncel teklifimiz 2250 EUR."
            )
        ):
            failures.append(
                "revised final body is not current"
            )

        if revised_output.final_price != 2250:
            failures.append(
                "revised final price is not current"
            )

        restarted_store = SQLitePilotStore(
            db_path,
            run_id="quote-final-output-b",
        )
        restarted_approvals = (
            SQLiteQuoteApprovalRepository(
                restarted_store
            )
        )
        restarted_cases = SQLiteQuoteCaseRepository(
            restarted_store
        )

        durable_output = build_quote_final_output(
            quote_case_repository=restarted_cases,
            approval_repository=restarted_approvals,
            case_id=quote_case.case_id,
        )

        if (
            durable_output.model_dump()
            != revised_output.model_dump()
        ):
            failures.append(
                "final approved output changed after restart"
            )

    return {
        "name": "Approved final customer quote output",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_quote_final_output_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
