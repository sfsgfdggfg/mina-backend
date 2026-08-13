from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictBool, field_validator

from src.core.clarification_requirements import (
    ClarificationAnswerValue,
    get_all_clarification_requirements,
    normalize_clarification_answers,
)


def _commodity_attribute_description() -> str:
    requirement_details = "; ".join(
        (
            f"{requirement.key} [{requirement.value_type}]: "
            f"{requirement.question}"
        )
        for requirement in sorted(
            get_all_clarification_requirements().values(),
            key=lambda item: item.key,
        )
    )
    return (
        "Commodity-specific answers explicitly present in the email. "
        "Do not infer or default answers. Use only these canonical keys: "
        f"{requirement_details}"
    )


class ExtractedPackage(BaseModel):
    package_type: str = Field(
        default="unknown",
        description=(
            "Package type such as pallet, crate, machine, roll, loose"
        ),
    )
    quantity: int = Field(
        default=1,
        description="Number of packages or pieces",
    )
    length_cm: Optional[float] = Field(
        default=None,
        description="Length in centimeters",
    )
    width_cm: Optional[float] = Field(
        default=None,
        description="Width in centimeters",
    )
    height_cm: Optional[float] = Field(
        default=None,
        description="Height in centimeters",
    )
    weight_kg: Optional[float] = Field(
        default=None,
        description=(
            "Weight stated for this package line in kg. For quantity 1 it "
            "is single-piece weight; for quantity greater than 1 preserve "
            "the stated value without assuming per-piece versus line-total."
        ),
    )
    stackable: Optional[bool] = Field(
        default=None,
        description="Whether cargo is stackable",
    )


class ShipmentExtraction(BaseModel):
    customer_name: str = Field(
        default="Unknown Customer",
        description="Customer name if known from the email",
    )
    pickup_country: Optional[str] = None
    pickup_city: Optional[str] = None
    pickup_area: Optional[str] = None
    pickup_postcode: Optional[str] = None

    delivery_country: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_area: Optional[str] = None
    delivery_postcode: Optional[str] = None

    commodity: Optional[str] = Field(
        default=None,
        description="Cargo / product type",
    )
    gross_weight_kg: Optional[float] = Field(
        default=None,
        description="Total gross shipment weight in kg",
    )
    weight_is_approximate: bool = True

    service_type: str = Field(
        default="FTL",
        description=(
            "FTL or LTL. Default FTL unless partial is explicitly requested"
        ),
    )
    transport_mode: Optional[
        Literal["road", "rail", "sea", "air", "multimodal"]
    ] = Field(
        default=None,
        description=(
            "Explicit transport mode. Use road, rail, sea, air, or multimodal; "
            "leave null when the email does not establish the mode."
        ),
    )
    equipment_type: Optional[str] = None

    cargo_ready_date: Optional[str] = None
    required_delivery_date: Optional[str] = None

    is_adr: Optional[StrictBool] = Field(
        default=None,
        description=(
            "Whether the email explicitly states ADR status. Null means the "
            "email did not establish ADR status."
        ),
    )
    adr_class: Optional[str] = None

    is_temperature_controlled: Optional[StrictBool] = Field(
        default=None,
        description=(
            "Whether temperature control is explicitly established. Null "
            "means unknown, not false."
        ),
    )
    temperature_requirement: Optional[str] = None

    is_high_value: Optional[StrictBool] = Field(
        default=None,
        description=(
            "Whether high-value status is explicitly established. Null means "
            "unknown, not false."
        ),
    )
    special_notes: Optional[str] = None

    commodity_attributes: Dict[
        str, ClarificationAnswerValue
    ] = Field(
        default_factory=dict,
        description=_commodity_attribute_description(),
    )

    packages: List[ExtractedPackage] = Field(default_factory=list)

    @field_validator("commodity_attributes")
    @classmethod
    def validate_commodity_attributes(
        cls,
        value: Dict[str, ClarificationAnswerValue],
    ) -> Dict[str, ClarificationAnswerValue]:
        return normalize_clarification_answers(value)
