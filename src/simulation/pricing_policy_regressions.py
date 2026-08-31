from __future__ import annotations

import os
from unittest.mock import patch

from src.core.customer_memory import CustomerMemoryProfile
from src.core.pricing_policy import (
    AGENCY_PRICING_POLICY_ENV,
    PricingFormula,
    resolve_pricing_policy,
)
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import attach_supplier_rfq_response
from src.simulation.human_operational_flow_regressions import _setup
from src.simulation.pricing_policy_fixture import (
    SYNTHETIC_AGENCY_PRICING_POLICY_JSON,
)
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow


def _quoted_setup():
    repo, workflow, draft, _ = _setup()
    attach_supplier_rfq_response(
        repo,
        SupplierRFQResponse(
            rfq_id=draft.rfq_id,
            supplier_name=draft.supplier_name,
            rfq_priority=draft.priority,
            status="quoted",
            cost=2400,
            currency="EUR",
            transit_time="5-7 gün",
            source="simulation",
        ),
    )
    return repo, workflow


def evaluate_pricing_policy_regressions() -> dict:
    failures: list[str] = []

    agency_env = {
        AGENCY_PRICING_POLICY_ENV: SYNTHETIC_AGENCY_PRICING_POLICY_JSON
    }
    customer_formula = PricingFormula(method="fixed_profit", value=200)
    quote_formula = PricingFormula(method="fixed_profit", value=300)

    customer_resolution = resolve_pricing_policy(
        currency="EUR",
        customer_pricing_policy=customer_formula,
        environ=agency_env,
    )
    if (
        customer_resolution.policy_source != "customer_policy"
        or customer_resolution.formula != customer_formula
    ):
        failures.append("customer pricing policy did not override agency default")

    quote_resolution = resolve_pricing_policy(
        currency="EUR",
        customer_pricing_policy=customer_formula,
        quote_override=quote_formula,
        environ=agency_env,
    )
    if (
        quote_resolution.policy_source != "quote_override"
        or quote_resolution.formula != quote_formula
    ):
        failures.append("quote pricing override did not override customer policy")

    profile = CustomerMemoryProfile(
        customer_name="Pricing Customer",
        pricing_policy=customer_formula,
    )
    if profile.pricing_policy != customer_formula:
        failures.append("customer memory did not preserve pricing policy")

    invalid = resolve_pricing_policy(
        currency="EUR",
        environ={AGENCY_PRICING_POLICY_ENV: "{not-json"},
    )
    if invalid.status != "invalid" or invalid.resolved:
        failures.append("invalid agency pricing config did not fail closed")

    repo, workflow = _quoted_setup()
    with patch.dict(os.environ, {}, clear=True):
        blocked = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repo,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
        )
    if (
        blocked.get("result_type") != "pricing_policy_required"
        or blocked.get("quote_case") is not None
        or blocked.get("customer_quote") is not None
    ):
        failures.append("missing pricing policy did not block customer quote creation")

    repo, workflow = _quoted_setup()
    with patch.dict(os.environ, agency_env, clear=False):
        agency_quote = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repo,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
        )
    customer_quote = agency_quote.get("customer_quote")
    quote_approval = agency_quote.get("quote_approval")
    if (
        customer_quote is None
        or customer_quote.final_price != 2760
        or customer_quote.pricing_policy is None
        or customer_quote.pricing_policy.policy_source != "agency_default"
        or quote_approval is None
        or quote_approval.quote_snapshot.pricing_policy
        != customer_quote.pricing_policy
    ):
        failures.append("agency pricing policy did not produce auditable quote")

    repo, workflow = _quoted_setup()
    with patch.dict(os.environ, {}, clear=True):
        overridden = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repo,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
            quote_pricing_override=quote_formula,
        )
    customer_quote = overridden.get("customer_quote")
    if (
        customer_quote is None
        or customer_quote.final_price != 2700
        or customer_quote.pricing_policy is None
        or customer_quote.pricing_policy.policy_source != "quote_override"
    ):
        failures.append("quote override did not independently resolve pricing")

    return {
        "name": "Pricing policy resolution",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pricing_policy_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
