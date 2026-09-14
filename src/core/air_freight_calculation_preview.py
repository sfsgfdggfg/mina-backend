from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository


class AirFreightCalculationPreviewError(ValueError):
    pass


class AirFreightCalculationOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weight_break: str
    threshold_kg: Decimal
    rate_per_kg: Decimal
    billed_weight_kg: Decimal
    base_freight: Decimal
    minimum_applied: bool = False
    is_pivot_option: bool = False


class AirFreightCalculationPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str
    candidate_id: str
    source_id: str
    destination_label: str
    destination_code: Optional[str] = None
    currency: str
    actual_weight_kg: Decimal
    volumetric_weight_kg: Decimal
    volumetric_source: str
    volumetric_divisor: Optional[Decimal] = None
    chargeable_weight_kg: Decimal
    minimum_charge: Optional[Decimal] = None
    options: list[AirFreightCalculationOption] = Field(min_length=1, max_length=20)
    recommended_break: str
    recommended_billed_weight_kg: Decimal
    recommended_base_freight: Decimal
    pivot_applied: bool
    rounding_review_id: Optional[str] = None
    rounding_mode: Optional[Literal["none", "ceiling"]] = None
    rounding_increment_kg: Optional[Decimal] = None
    rounded_chargeable_weight_kg: Optional[Decimal] = None
    rounding_applied: bool = False
    surcharges_included: bool = False
    capacity_confirmed: bool = False
    runtime_authoritative: bool = False
    customer_quote_eligible: bool = False

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()


def _positive_decimal(value, *, label: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except Exception as exc:
        raise AirFreightCalculationPreviewError(f"{label} must be a decimal value.") from exc
    if not decimal.is_finite() or decimal <= 0 or decimal > Decimal("1000000000"):
        raise AirFreightCalculationPreviewError(f"{label} must be a finite positive bounded value.")
    return decimal


def _confirmed_divisor(source_id: str, repository: AirRateStructureReviewRepository) -> Decimal:
    review = repository.find_by_source(source_id)
    if review is None or review.status != "completed":
        raise AirFreightCalculationPreviewError("air_rate_structure_review_must_be_completed")
    values = {
        item.value for item in review.candidates
        if item.kind == "volumetric_divisor" and item.status == "confirmed"
    }
    if len(values) != 1:
        raise AirFreightCalculationPreviewError("air_rate_requires_one_confirmed_volumetric_divisor")
    return _positive_decimal(next(iter(values)), label="volumetric divisor")


def build_air_freight_calculation_preview(
    *,
    review_id: str,
    candidate_id: str,
    actual_weight_kg,
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
    rounding_repository: AirRateWeightRoundingReviewRepository | None = None,
    volumetric_weight_kg=None,
    total_volume_cm3=None,
) -> AirFreightCalculationPreview:
    review = table_repository.get(review_id)
    if review is None:
        raise AirFreightCalculationPreviewError("air_rate_table_review_not_found")
    row = next((item for item in review.candidates if item.candidate_id == candidate_id), None)
    if row is None:
        raise AirFreightCalculationPreviewError("air_rate_table_row_not_found")
    if row.status != "confirmed":
        raise AirFreightCalculationPreviewError("air_rate_table_row_must_be_confirmed")
    if not row.currency:
        raise AirFreightCalculationPreviewError("air_rate_table_row_currency_required")
    if (volumetric_weight_kg is None) == (total_volume_cm3 is None):
        raise AirFreightCalculationPreviewError("provide_exactly_one_volumetric_input")

    actual = _positive_decimal(actual_weight_kg, label="actual weight")
    divisor = None
    if total_volume_cm3 is not None:
        volume = _positive_decimal(total_volume_cm3, label="total volume")
        divisor = _confirmed_divisor(review.source_id, structure_repository)
        volumetric = volume / divisor
        volumetric_source = "confirmed_divisor_from_total_volume"
    else:
        volumetric = _positive_decimal(volumetric_weight_kg, label="volumetric weight")
        volumetric_source = "operator_supplied_volumetric_weight"

    chargeable = max(actual, volumetric)
    rounding_review = None
    effective_chargeable = chargeable
    rounding_applied = False
    if rounding_repository is not None:
        rounding_review = rounding_repository.get_by_source(review.source_id)
        if rounding_review is not None:
            if rounding_review.source_sha256 != review.source_sha256:
                raise AirFreightCalculationPreviewError("air_rate_weight_rounding_source_mismatch")
            if rounding_review.rounding_mode == "ceiling":
                increment = rounding_review.increment_kg
                if increment is None:
                    raise AirFreightCalculationPreviewError("air_rate_weight_rounding_increment_required")
                units = (chargeable / increment).to_integral_value(rounding=ROUND_CEILING)
                effective_chargeable = units * increment
                rounding_applied = True

    minimum = row.rates.get("MIN")
    plus_rates: list[tuple[str, Decimal, Decimal]] = []
    for key, rate in row.rates.items():
        if key.startswith("+") and key[1:].isdigit():
            plus_rates.append((key, Decimal(key[1:]), rate))
    if not plus_rates:
        raise AirFreightCalculationPreviewError("air_rate_row_requires_weight_break_rate")

    options: list[AirFreightCalculationOption] = []
    for key, threshold, rate in sorted(plus_rates, key=lambda item: item[1]):
        billed = max(effective_chargeable, threshold)
        raw_freight = billed * rate
        minimum_applied = minimum is not None and minimum > raw_freight
        freight = minimum if minimum_applied else raw_freight
        options.append(AirFreightCalculationOption(
            weight_break=key,
            threshold_kg=threshold,
            rate_per_kg=rate,
            billed_weight_kg=billed,
            base_freight=freight,
            minimum_applied=minimum_applied,
            is_pivot_option=threshold > effective_chargeable,
        ))

    best = min(options, key=lambda item: (item.base_freight, item.billed_weight_kg, item.threshold_kg))
    return AirFreightCalculationPreview(
        review_id=review.review_id,
        candidate_id=row.candidate_id,
        source_id=review.source_id,
        destination_label=row.destination_label,
        destination_code=row.destination_code,
        currency=row.currency,
        actual_weight_kg=actual,
        volumetric_weight_kg=volumetric,
        volumetric_source=volumetric_source,
        volumetric_divisor=divisor,
        chargeable_weight_kg=chargeable,
        minimum_charge=minimum,
        options=options,
        recommended_break=best.weight_break,
        recommended_billed_weight_kg=best.billed_weight_kg,
        recommended_base_freight=best.base_freight,
        pivot_applied=best.is_pivot_option,
        rounding_review_id=None if rounding_review is None else rounding_review.review_id,
        rounding_mode=None if rounding_review is None else rounding_review.rounding_mode,
        rounding_increment_kg=None if rounding_review is None else rounding_review.increment_kg,
        rounded_chargeable_weight_kg=(
            None if rounding_review is None else effective_chargeable
        ),
        rounding_applied=rounding_applied,
    )
