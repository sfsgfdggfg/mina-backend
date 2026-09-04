from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Any, Literal, Optional, List
from src.core.pricing_policy import PricingPolicyResolution

from src.core.clarification_requirements import (
    ClarificationAnswerValue,
    normalize_clarification_answers,
)
from src.core.regulatory_compliance import (
    RegulatoryExceptionReview,
    validate_regulatory_exception_reviews,
)


class Package(BaseModel):
    package_type: str = "pallet"
    quantity: int
    length_cm: Optional[float] = None
    width_cm: Optional[float] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    stackable: Optional[bool] = None


class Shipment(BaseModel):
    customer_name: str = "Unknown Customer"

    pickup_country: Optional[str] = None
    pickup_city: Optional[str] = None
    pickup_area: Optional[str] = None
    pickup_postcode: Optional[str] = None

    delivery_country: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_area: Optional[str] = None
    delivery_postcode: Optional[str] = None

    commodity: Optional[str] = None
    gtip_code: Optional[str] = None
    hs_chapter: Optional[str] = None
    hs_heading: Optional[str] = None
    hs_subheading: Optional[str] = None
    gtip_detected_from_email: bool = False
    gross_weight_kg: Optional[float] = None
    weight_is_approximate: bool = True

    service_type: str = "FTL"
    quote_mode: Literal["firm", "indicative"] = "firm"
    transport_mode: Optional[
        Literal["road", "rail", "sea", "air", "multimodal"]
    ] = None
    equipment_type: Optional[str] = None

    cargo_ready_date: Optional[str] = None
    required_delivery_date: Optional[str] = None
    customer_quote_deadline_at: Optional[datetime] = None

    is_adr: Optional[bool] = None
    adr_class: Optional[str] = None

    is_temperature_controlled: Optional[bool] = None
    temperature_requirement: Optional[str] = None

    is_high_value: Optional[bool] = None
    special_notes: Optional[str] = None

    commodity_attributes: dict[
        str, ClarificationAnswerValue
    ] = Field(default_factory=dict)
    regulatory_exception_reviews: dict[
        str, RegulatoryExceptionReview
    ] = Field(default_factory=dict)

    packages: List[Package] = Field(default_factory=list)

    @field_validator("customer_quote_deadline_at")
    @classmethod
    def validate_customer_quote_deadline_at(
        cls, value: Optional[datetime]
    ) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Customer quote deadline must include timezone evidence.")
        return value

    @field_validator("commodity_attributes")
    @classmethod
    def validate_commodity_attributes(
        cls,
        value: dict[str, ClarificationAnswerValue],
    ) -> dict[str, ClarificationAnswerValue]:
        return normalize_clarification_answers(value)

    @model_validator(mode="after")
    def validate_regulatory_reviews(self):
        validate_regulatory_exception_reviews(
            commodity=self.commodity,
            commodity_attributes=self.commodity_attributes,
            reviews=self.regulatory_exception_reviews,
        )
        return self


class EquipmentDecision(BaseModel):
    selected_equipment: str
    reason: str
    confidence: float
    source: str = "rule_engine"
    explanation: Optional[str] = None


class RiskAssessment(BaseModel):
    risk_level: str
    risk_reasons: List[str] = Field(default_factory=list)
    requires_human_review: bool = False
    requires_management_review: bool = False


class SupplierQuote(BaseModel):
    supplier_name: str
    cost: float
    currency: str = "EUR"
    transit_time: Optional[str] = None
    validity_date: Optional[str] = None
    vehicle_available_date: Optional[str] = None
    equipment_type: Optional[str] = None
    pricing_basis: Optional[
        Literal["all_in", "base_freight_plus_extras"]
    ] = None
    included_costs: Optional[List[str]] = None
    excluded_costs: Optional[List[str]] = None
    notes: Optional[str] = None
    price_offer_id: Optional[str] = None
    price_source: Optional[str] = None
    price_source_reference: Optional[str] = None


class CustomerQuote(BaseModel):
    supplier_cost: float
    markup_type: str
    markup_value: float
    final_price: float
    currency: str = "EUR"
    pricing_policy: Optional[PricingPolicyResolution] = None

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_margin_names(cls, data: Any) -> Any:
        """Accept old constructor keys while emitting accurate markup names."""

        if not isinstance(data, dict):
            return data

        normalized_data = dict(data)

        if "markup_type" not in normalized_data and "margin_type" in normalized_data:
            normalized_data["markup_type"] = normalized_data["margin_type"]

        if "markup_value" not in normalized_data and "margin_value" in normalized_data:
            normalized_data["markup_value"] = normalized_data["margin_value"]

        normalized_data.pop("margin_type", None)
        normalized_data.pop("margin_value", None)
        return normalized_data

    @property
    def margin_type(self) -> str:
        """Deprecated compatibility alias for markup_type."""

        return self.markup_type

    @property
    def margin_value(self) -> float:
        """Deprecated compatibility alias for markup_value."""

        return self.markup_value


class QuoteDraft(BaseModel):
    subject: str
    body: str
