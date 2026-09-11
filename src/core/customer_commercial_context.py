from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from src.core.customer_preference_policy import build_customer_preference_policy
from src.core.customer_quote_acceptance_policy import (
    ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
    ACCEPTED_MARKUP_MEDIAN_KEY,
    build_customer_quote_acceptance_policy,
)
from src.core.customer_quote_context import customer_quote_context_key
from src.core.customer_quote_reason_policy import (
    CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
    build_customer_quote_reason_policy,
)
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.supplier_customer_context import resolve_customer_master_profile

if TYPE_CHECKING:
    from src.core.quote_case import QuoteCase


class AdvisoryValue(BaseModel):
    value: str | float
    unit: str | None = None
    fact_id: str


class ContextualMarkupAdvisory(AdvisoryValue):
    markup_type: str


class CustomerCommercialContext(BaseModel):
    accepted_quote_currency_advisory: AdvisoryValue | None = None
    observed_acceptance_rate: AdvisoryValue | None = None
    observed_negotiation_rate: AdvisoryValue | None = None
    customer_stated_price_objection_rate: AdvisoryValue | None = None
    customer_stated_transit_time_objection_rate: AdvisoryValue | None = None
    accepted_final_price_median: AdvisoryValue | None = None
    accepted_markup_median: ContextualMarkupAdvisory | None = None
    customer_stated_target_price_median: AdvisoryValue | None = None

    advisory_only: bool = True
    pricing_authority: bool = False
    margin_authority: bool = False
    supplier_selection_authority: bool = False
    supplier_negotiation_authority: bool = False
    automation_authority: bool = False
    quote_send_authority: bool = False
    dispatch_authority: bool = False
    causal_explanation_created: bool = False
    win_probability_created: bool = False
    willingness_to_pay_created: bool = False
    current_customer_target_created: bool = False
    source: str = "customer_commercial_context_v1"


def _metric(value: float | None, unit: str, fact_id: str | None) -> AdvisoryValue | None:
    if value is None or fact_id is None:
        return None
    return AdvisoryValue(value=value, unit=unit, fact_id=fact_id)


def _find_contextual(items: list[Any], *, fact_key: str, context_key: str | None):
    if context_key is None:
        return None
    return next(
        (
            item for item in items
            if item.fact_key == fact_key
            and item.context_key == context_key
            and item.effect == "advisory"
        ),
        None,
    )


def build_customer_commercial_context(
    *,
    quote_case: QuoteCase | None,
    master_data_repository: MasterDataRepository | None,
    learning_fact_repository: LearningFactRepository | None,
    as_of: datetime | None = None,
) -> CustomerCommercialContext | None:
    """Build privacy-minimal, read-only commercial history for a durable quote.

    Customer display text is used only as input to the authoritative active Customer
    Master resolver. Missing/ambiguous identity or a missing durable customer quote
    fails closed. Contextual observations are exact-key matches; no route, equipment,
    currency, or markup fallback is performed.
    """

    if quote_case is None or quote_case.customer_quote is None:
        return None
    customer = resolve_customer_master_profile(
        customer_name=quote_case.shipment.customer_name,
        master_repository=master_data_repository,
    )
    if customer is None:
        return None

    quote = quote_case.customer_quote
    currency = str(quote.currency).strip().upper()
    base_context = customer_quote_context_key(
        quote_case.shipment,
        currency=currency,
    )
    markup_context = customer_quote_context_key(
        quote_case.shipment,
        currency=currency,
        markup_type=quote.markup_type,
    )

    preference = build_customer_preference_policy(
        customer_id=customer.customer_id,
        learning_repository=learning_fact_repository,
        as_of=as_of,
    )
    acceptance = build_customer_quote_acceptance_policy(
        customer_id=customer.customer_id,
        learning_repository=learning_fact_repository,
        as_of=as_of,
    )
    reasons = build_customer_quote_reason_policy(
        customer_id=customer.customer_id,
        learning_repository=learning_fact_repository,
        as_of=as_of,
    )

    accepted_price = _find_contextual(
        acceptance.contextual_advisories,
        fact_key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
        context_key=base_context,
    )
    accepted_markup = _find_contextual(
        acceptance.contextual_advisories,
        fact_key=ACCEPTED_MARKUP_MEDIAN_KEY,
        context_key=markup_context,
    )
    target_price = _find_contextual(
        reasons.target_price_advisories,
        fact_key=CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
        context_key=base_context,
    )

    # Currency-bearing observations must agree with the durable quote even if a
    # malformed repository record somehow survived normal fact validation.
    if accepted_price is not None and accepted_price.value_unit.upper() != currency:
        accepted_price = None
    if target_price is not None and target_price.value_unit.upper() != currency:
        target_price = None

    return CustomerCommercialContext(
        accepted_quote_currency_advisory=(
            None
            if preference.accepted_quote_currency_advisory is None
            or preference.accepted_quote_currency_fact_id is None
            else AdvisoryValue(
                value=preference.accepted_quote_currency_advisory,
                fact_id=preference.accepted_quote_currency_fact_id,
            )
        ),
        observed_acceptance_rate=_metric(
            acceptance.overall_acceptance_rate_percent,
            "percent",
            acceptance.overall_acceptance_rate_fact_id,
        ),
        observed_negotiation_rate=_metric(
            acceptance.negotiation_rate_percent,
            "percent",
            acceptance.negotiation_rate_fact_id,
        ),
        customer_stated_price_objection_rate=_metric(
            reasons.price_objection_rate_percent,
            "percent",
            reasons.price_objection_rate_fact_id,
        ),
        customer_stated_transit_time_objection_rate=_metric(
            reasons.transit_time_objection_rate_percent,
            "percent",
            reasons.transit_time_objection_rate_fact_id,
        ),
        accepted_final_price_median=(
            None
            if accepted_price is None
            else AdvisoryValue(
                value=accepted_price.value,
                unit=currency,
                fact_id=accepted_price.fact_id,
            )
        ),
        accepted_markup_median=(
            None
            if accepted_markup is None
            else ContextualMarkupAdvisory(
                value=accepted_markup.value,
                unit=accepted_markup.value_unit,
                fact_id=accepted_markup.fact_id,
                markup_type=quote.markup_type,
            )
        ),
        customer_stated_target_price_median=(
            None
            if target_price is None
            else AdvisoryValue(
                value=target_price.value,
                unit=currency,
                fact_id=target_price.fact_id,
            )
        ),
    )
