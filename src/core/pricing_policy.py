from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


AGENCY_PRICING_POLICY_ENV = "MINAI_AGENCY_PRICING_POLICY_JSON"

PricingMethod = Literal[
    "cost_markup_percentage",
    "gross_margin_percentage",
    "fixed_profit",
    "manual_sell_price",
]
PricingPolicySource = Literal[
    "quote_override",
    "customer_policy",
    "agency_default",
    "operator_revision",
]
RoundingMode = Literal["none", "up", "nearest"]


class PricingFormula(BaseModel):
    method: PricingMethod
    value: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_formula(self):
        if self.method == "gross_margin_percentage" and self.value >= 100:
            raise ValueError("Gross margin percentage must be below 100.")
        if self.method == "manual_sell_price" and self.value <= 0:
            raise ValueError("Manual sell price must be positive.")
        return self


class PricingRoundingRule(BaseModel):
    mode: RoundingMode = "none"
    increment: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_rounding(self):
        if self.mode == "none" and self.increment is not None:
            raise ValueError("Rounding increment must be omitted when mode is none.")
        if self.mode != "none" and self.increment is None:
            raise ValueError("Rounding increment is required for active rounding.")
        return self


class AgencyPricingPolicy(BaseModel):
    default_formula: Optional[PricingFormula] = None
    default_rounding: PricingRoundingRule = Field(
        default_factory=PricingRoundingRule
    )
    currency_rounding: dict[str, PricingRoundingRule] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def normalize_currency_keys(self):
        normalized = {
            str(key).strip().upper(): value
            for key, value in self.currency_rounding.items()
            if str(key).strip()
        }
        object.__setattr__(self, "currency_rounding", normalized)
        return self


class PricingPolicyResolution(BaseModel):
    status: Literal["resolved", "missing", "invalid"]
    policy_source: Optional[PricingPolicySource] = None
    formula: Optional[PricingFormula] = None
    rounding: PricingRoundingRule = Field(default_factory=PricingRoundingRule)
    currency: str
    reason: Optional[str] = None
    agency_policy_configured: bool = False
    source: str = "pricing_policy_resolver"

    @property
    def resolved(self) -> bool:
        return self.status == "resolved" and self.formula is not None


def _load_agency_policy(
    environ: Mapping[str, str],
) -> tuple[AgencyPricingPolicy | None, str | None]:
    raw = (environ.get(AGENCY_PRICING_POLICY_ENV) or "").strip()
    if not raw:
        return None, None
    try:
        payload = json.loads(raw)
        return AgencyPricingPolicy.model_validate(payload), None
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return None, f"Agency pricing policy configuration is invalid: {exc}"


def resolve_pricing_policy(
    *,
    currency: str,
    customer_pricing_policy: PricingFormula | None = None,
    quote_override: PricingFormula | None = None,
    environ: Mapping[str, str] | None = None,
) -> PricingPolicyResolution:
    env = environ if environ is not None else os.environ
    normalized_currency = (currency or "").strip().upper()
    agency_policy, configuration_error = _load_agency_policy(env)

    if configuration_error:
        return PricingPolicyResolution(
            status="invalid",
            currency=normalized_currency,
            reason=configuration_error,
            agency_policy_configured=True,
        )

    if quote_override is not None:
        formula = quote_override
        policy_source: PricingPolicySource = "quote_override"
    elif customer_pricing_policy is not None:
        formula = customer_pricing_policy
        policy_source = "customer_policy"
    elif agency_policy is not None and agency_policy.default_formula is not None:
        formula = agency_policy.default_formula
        policy_source = "agency_default"
    else:
        return PricingPolicyResolution(
            status="missing",
            currency=normalized_currency,
            reason=(
                "No quote override, verified customer pricing policy, or agency "
                "default pricing formula is configured."
            ),
            agency_policy_configured=agency_policy is not None,
        )

    rounding = PricingRoundingRule()
    if formula.method != "manual_sell_price" and agency_policy is not None:
        rounding = agency_policy.currency_rounding.get(
            normalized_currency, agency_policy.default_rounding
        )

    return PricingPolicyResolution(
        status="resolved",
        policy_source=policy_source,
        formula=formula,
        rounding=rounding,
        currency=normalized_currency,
        agency_policy_configured=agency_policy is not None,
    )


def build_operator_revision_pricing_policy(
    *,
    final_price: float,
    currency: str,
    agency_policy_configured: bool = False,
) -> PricingPolicyResolution:
    return PricingPolicyResolution(
        status="resolved",
        policy_source="operator_revision",
        formula=PricingFormula(
            method="manual_sell_price",
            value=final_price,
        ),
        rounding=PricingRoundingRule(),
        currency=currency.strip().upper(),
        agency_policy_configured=agency_policy_configured,
    )
