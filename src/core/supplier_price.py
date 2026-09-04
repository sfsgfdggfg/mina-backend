from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import NAMESPACE_URL, uuid4, uuid5
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.models import Shipment
from src.core.supplier_commercial_safety import equipment_matches
from src.core.supplier_rfq import SupplierPricingBasis, SupplierRFQResponse


SupplierFixedRateEvidenceSource = Literal[
    "agreement", "email", "phone", "whatsapp", "portal", "excel", "manual"
]
SupplierPriceSource = Literal[
    "rfq_email", "rfq_portal", "rfq_api", "rfq_manual",
    "email", "phone", "whatsapp", "portal", "api", "manual", "fixed_rate",
]
TransportMode = Literal["road", "rail", "sea", "air", "multimodal"]
ISTANBUL = ZoneInfo("Europe/Istanbul")


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _normalize_optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


class SupplierFixedRate(BaseModel):
    rate_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    supplier_name: str = Field(min_length=1, max_length=200)
    origin_country: str = Field(min_length=1, max_length=100)
    destination_country: str = Field(min_length=1, max_length=100)
    origin_city: Optional[str] = Field(default=None, max_length=120)
    destination_city: Optional[str] = Field(default=None, max_length=120)
    origin_region: Optional[str] = Field(default=None, max_length=120)
    destination_region: Optional[str] = Field(default=None, max_length=120)
    transport_mode: Optional[TransportMode] = None
    service_type: Optional[str] = Field(default=None, max_length=80)
    equipment_type: Optional[str] = Field(default=None, max_length=120)

    cost: float = Field(gt=0)
    currency: str = "EUR"
    transit_time: Optional[str] = Field(default=None, max_length=120)
    pricing_basis: Optional[SupplierPricingBasis] = None
    included_costs: Optional[list[str]] = None
    excluded_costs: Optional[list[str]] = None

    valid_from: date
    valid_to: date
    evidence_source: SupplierFixedRateEvidenceSource
    evidence_reference: Optional[str] = Field(default=None, max_length=300)
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: Optional[str] = Field(default=None, max_length=200)
    updated_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=2000)
    active: bool = True

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Fixed rate currency must be a 3-letter code.")
        return normalized

    @field_validator(
        "supplier_name", "origin_country", "destination_country",
        "origin_city", "destination_city", "origin_region", "destination_region",
        "service_type", "equipment_type", "transit_time", "evidence_reference",
        "recorded_by", "updated_by", "notes",
        mode="before",
    )
    @classmethod
    def normalize_text_fields(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("recorded_at", "updated_at")
    @classmethod
    def require_aware_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Fixed rate timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_validity(self):
        if self.valid_to < self.valid_from:
            raise ValueError("Fixed rate valid_to cannot precede valid_from.")
        return self


class SupplierFixedRateApplicability(BaseModel):
    rate_id: str
    applicable: bool
    reasons: list[str] = Field(default_factory=list)
    source: str = "supplier_fixed_rate_applicability"


class SupplierPriceOffer(BaseModel):
    offer_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    mina_job_id: str = Field(min_length=1, max_length=300)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    supplier_name: str = Field(min_length=1, max_length=200)
    source_type: SupplierPriceSource
    source_reference_id: Optional[str] = Field(default=None, max_length=300)
    rfq_id: Optional[str] = Field(default=None, max_length=300)
    fixed_rate_id: Optional[str] = Field(default=None, max_length=300)

    cost: float = Field(gt=0)
    currency: str = "EUR"
    transit_time: Optional[str] = Field(default=None, max_length=120)
    validity_date: Optional[str] = Field(default=None, max_length=80)
    vehicle_available_date: Optional[str] = Field(default=None, max_length=80)
    equipment_type: Optional[str] = Field(default=None, max_length=120)
    pricing_basis: Optional[SupplierPricingBasis] = None
    included_costs: Optional[list[str]] = None
    excluded_costs: Optional[list[str]] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    recorded_by: Optional[str] = Field(default=None, max_length=200)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("currency")
    @classmethod
    def normalize_offer_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Supplier price offer currency must be a 3-letter code.")
        return normalized

    @field_validator("recorded_at")
    @classmethod
    def require_offer_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Supplier price offer recorded_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_source_provenance(self):
        if self.source_type == "fixed_rate":
            if not self.fixed_rate_id or self.rfq_id is not None:
                raise ValueError("Fixed-rate offers require fixed_rate_id and cannot carry rfq_id.")
        elif self.source_type.startswith("rfq_"):
            if not self.rfq_id or self.fixed_rate_id is not None:
                raise ValueError("RFQ-derived offers require rfq_id and cannot carry fixed_rate_id.")
        elif self.rfq_id is not None or self.fixed_rate_id is not None:
            raise ValueError("Direct supplier price offers cannot carry RFQ/fixed-rate identity.")
        return self

    @property
    def is_price_usable(self) -> bool:
        return self.cost > 0 and bool(self.currency)


def evaluate_fixed_rate_applicability(
    *, rate: SupplierFixedRate, shipment: Shipment, as_of: date | None = None,
) -> SupplierFixedRateApplicability:
    reasons: list[str] = []
    reference_date = as_of or datetime.now(ISTANBUL).date()
    if not rate.active:
        reasons.append("fixed_rate_inactive")
    if reference_date < rate.valid_from:
        reasons.append("fixed_rate_not_yet_valid")
    if reference_date > rate.valid_to:
        reasons.append("fixed_rate_expired")
    if _normalize_text(rate.origin_country) != _normalize_text(shipment.pickup_country):
        reasons.append("fixed_rate_origin_country_mismatch")
    if _normalize_text(rate.destination_country) != _normalize_text(shipment.delivery_country):
        reasons.append("fixed_rate_destination_country_mismatch")
    if rate.origin_city and _normalize_text(rate.origin_city) != _normalize_text(shipment.pickup_city):
        reasons.append("fixed_rate_origin_city_mismatch")
    if rate.destination_city and _normalize_text(rate.destination_city) != _normalize_text(shipment.delivery_city):
        reasons.append("fixed_rate_destination_city_mismatch")
    if rate.origin_region and _normalize_text(rate.origin_region) != _normalize_text(shipment.pickup_area):
        reasons.append("fixed_rate_origin_region_mismatch")
    if rate.destination_region and _normalize_text(rate.destination_region) != _normalize_text(shipment.delivery_area):
        reasons.append("fixed_rate_destination_region_mismatch")
    if rate.transport_mode and rate.transport_mode != shipment.transport_mode:
        reasons.append("fixed_rate_transport_mode_mismatch")
    if rate.service_type and _normalize_text(rate.service_type) != _normalize_text(shipment.service_type):
        reasons.append("fixed_rate_service_type_mismatch")
    if rate.equipment_type:
        if not shipment.equipment_type or not equipment_matches(rate.equipment_type, shipment.equipment_type):
            reasons.append("fixed_rate_equipment_mismatch")
    return SupplierFixedRateApplicability(
        rate_id=rate.rate_id, applicable=not reasons, reasons=reasons
    )


def offer_from_fixed_rate(
    *, rate: SupplierFixedRate, job_id: str, mina_code: str, entry_id: str,
    recorded_by: str, recorded_at: datetime | None = None,
) -> SupplierPriceOffer:
    timestamp = recorded_at or datetime.now(timezone.utc)
    return SupplierPriceOffer(
        entry_id=entry_id, mina_job_id=job_id, mina_code=mina_code,
        supplier_name=rate.supplier_name, source_type="fixed_rate",
        source_reference_id=rate.rate_id, fixed_rate_id=rate.rate_id,
        cost=rate.cost, currency=rate.currency, transit_time=rate.transit_time,
        validity_date=rate.valid_to.isoformat(), equipment_type=rate.equipment_type,
        pricing_basis=rate.pricing_basis, included_costs=rate.included_costs,
        excluded_costs=rate.excluded_costs, notes=rate.notes,
        recorded_by=recorded_by, recorded_at=timestamp,
    )


def offer_from_rfq_response(
    *, response: SupplierRFQResponse, job_id: str, mina_code: str,
) -> SupplierPriceOffer:
    if not response.is_price_usable:
        raise ValueError("Only usable quoted RFQ responses can become price offers.")
    source_map = {
        "email": "rfq_email", "portal": "rfq_portal",
        "api": "rfq_api", "manual": "rfq_manual", "simulation": "rfq_manual",
    }
    entry_id = f"rfq:{response.rfq_id}:{response.received_at.isoformat()}"
    return SupplierPriceOffer(
        offer_id=str(uuid5(NAMESPACE_URL, entry_id)), entry_id=entry_id,
        mina_job_id=job_id, mina_code=mina_code, supplier_name=response.supplier_name,
        source_type=source_map[response.source], source_reference_id=response.rfq_id,
        rfq_id=response.rfq_id, cost=float(response.cost), currency=response.currency,
        transit_time=response.transit_time, validity_date=response.validity_date,
        vehicle_available_date=response.vehicle_available_date,
        equipment_type=response.equipment_type, pricing_basis=response.pricing_basis,
        included_costs=response.included_costs, excluded_costs=response.excluded_costs,
        notes=response.notes, recorded_by=response.recorded_by,
        recorded_at=(response.received_at if response.received_at.tzinfo else response.received_at.replace(tzinfo=timezone.utc)),
    )
