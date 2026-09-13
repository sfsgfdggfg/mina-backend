from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository


class AirShadowCalculationError(ValueError):
    pass


class AirShadowPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: int = Field(ge=1, le=10000)
    length_cm: Decimal = Field(gt=0, le=Decimal("1000"))
    width_cm: Decimal = Field(gt=0, le=Decimal("1000"))
    height_cm: Decimal = Field(gt=0, le=Decimal("1000"))

    @field_validator("length_cm", "width_cm", "height_cm")
    @classmethod
    def finite_dimension(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("Air shadow package dimensions must be finite.")
        return value


class AirShadowFreightOption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_kind: str
    rate_break: str
    billed_weight_kg: Decimal
    rate_per_kg: Optional[Decimal] = None
    freight_amount: Decimal
    currency: str
    pivoted_up: bool = False


class AirShadowCalculationPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    candidate_id: str
    destination_label: str
    destination_code: Optional[str] = None
    currency: str
    divisor: int
    divisor_source: str = "confirmed_tariff_structure"
    actual_weight_kg: Decimal
    volumetric_weight_kg: Decimal
    chargeable_weight_kg_unrounded: Decimal
    standard_option: AirShadowFreightOption
    pivot_options: list[AirShadowFreightOption] = Field(default_factory=list)
    lowest_math_option: AirShadowFreightOption
    weight_rounding_applied: bool = False
    surcharges_included: bool = False
    pickup_included: bool = False
    door_delivery_included: bool = False
    capacity_confirmed: bool = False
    schedule_confirmed: bool = False
    quote_authority: bool = False
    runtime_authoritative: bool = False

    @model_validator(mode="after")
    def preserve_shadow_boundary(self):
        if any((self.weight_rounding_applied, self.surcharges_included, self.pickup_included,
                self.door_delivery_included, self.capacity_confirmed, self.schedule_confirmed,
                self.quote_authority, self.runtime_authoritative)):
            raise ValueError("Air shadow calculation preview cannot carry execution authority.")
        return self


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _weight(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def build_air_shadow_calculation_preview(
    *,
    review_id: str,
    candidate_id: str,
    actual_weight_kg: Decimal,
    packages: list[AirShadowPackage],
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
) -> AirShadowCalculationPreview:
    if not actual_weight_kg.is_finite() or actual_weight_kg <= 0 or actual_weight_kg > Decimal("1000000"):
        raise AirShadowCalculationError("air_shadow_actual_weight_invalid")
    if not packages:
        raise AirShadowCalculationError("air_shadow_packages_required")

    table_review = table_repository.get(review_id)
    if table_review is None:
        raise AirShadowCalculationError("air_shadow_table_review_not_found")
    row = next((item for item in table_review.candidates if item.candidate_id == candidate_id), None)
    if row is None:
        raise AirShadowCalculationError("air_shadow_rate_row_not_found")
    if row.status != "confirmed":
        raise AirShadowCalculationError("air_shadow_rate_row_must_be_confirmed")
    if not row.currency:
        raise AirShadowCalculationError("air_shadow_rate_row_currency_required")
    if "MIN" not in row.rates:
        raise AirShadowCalculationError("air_shadow_rate_row_min_required")

    structure = structure_repository.get(table_review.structure_review_id)
    if structure is None or structure.source_id != table_review.source_id:
        raise AirShadowCalculationError("air_shadow_structure_review_not_found")
    divisors = {
        int(item.value)
        for item in structure.candidates
        if item.kind == "volumetric_divisor" and item.status == "confirmed" and item.value.isdigit()
    }
    if len(divisors) != 1:
        raise AirShadowCalculationError("air_shadow_requires_one_confirmed_volumetric_divisor")
    divisor = next(iter(divisors))
    if divisor < 4000 or divisor > 7000:
        raise AirShadowCalculationError("air_shadow_volumetric_divisor_out_of_bounds")

    volumetric = sum(
        Decimal(package.quantity) * package.length_cm * package.width_cm * package.height_cm / Decimal(divisor)
        for package in packages
    )
    chargeable = max(actual_weight_kg, volumetric)

    numeric_breaks = sorted(
        (int(key[1:]), key, amount)
        for key, amount in row.rates.items()
        if key.startswith("+") and key[1:].isdigit()
    )
    if not numeric_breaks:
        raise AirShadowCalculationError("air_shadow_rate_row_weight_break_required")

    min_charge = row.rates["MIN"]
    applicable = [item for item in numeric_breaks if Decimal(item[0]) <= chargeable]
    if applicable:
        threshold, break_key, rate = applicable[-1]
        billed = chargeable
        standard_amount = max(min_charge, billed * rate)
        standard = AirShadowFreightOption(
            option_kind="standard",
            rate_break=break_key,
            billed_weight_kg=_weight(billed),
            rate_per_kg=rate,
            freight_amount=_money(standard_amount),
            currency=row.currency,
            pivoted_up=False,
        )
    else:
        standard = AirShadowFreightOption(
            option_kind="standard_minimum",
            rate_break="MIN",
            billed_weight_kg=_weight(chargeable),
            rate_per_kg=None,
            freight_amount=_money(min_charge),
            currency=row.currency,
            pivoted_up=False,
        )

    pivots: list[AirShadowFreightOption] = []
    for threshold, break_key, rate in numeric_breaks:
        threshold_weight = Decimal(threshold)
        if threshold_weight <= chargeable:
            continue
        amount = max(min_charge, threshold_weight * rate)
        pivots.append(AirShadowFreightOption(
            option_kind="pivot",
            rate_break=break_key,
            billed_weight_kg=_weight(threshold_weight),
            rate_per_kg=rate,
            freight_amount=_money(amount),
            currency=row.currency,
            pivoted_up=True,
        ))
    lowest = min([standard, *pivots], key=lambda item: (item.freight_amount, item.billed_weight_kg))

    return AirShadowCalculationPreview(
        review_id=review_id,
        candidate_id=candidate_id,
        destination_label=row.destination_label,
        destination_code=row.destination_code,
        currency=row.currency,
        divisor=divisor,
        actual_weight_kg=_weight(actual_weight_kg),
        volumetric_weight_kg=_weight(volumetric),
        chargeable_weight_kg_unrounded=_weight(chargeable),
        standard_option=standard,
        pivot_options=pivots,
        lowest_math_option=lowest,
    )
