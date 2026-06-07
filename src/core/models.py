from pydantic import BaseModel, Field
from typing import Optional, List


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
    gross_weight_kg: Optional[float] = None
    weight_is_approximate: bool = True

    service_type: str = "FTL"
    equipment_type: Optional[str] = None

    cargo_ready_date: Optional[str] = None
    required_delivery_date: Optional[str] = None

    is_adr: bool = False
    adr_class: Optional[str] = None

    is_temperature_controlled: bool = False
    temperature_requirement: Optional[str] = None

    is_high_value: bool = False
    special_notes: Optional[str] = None

    packages: List[Package] = Field(default_factory=list)


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
    notes: Optional[str] = None


class CustomerQuote(BaseModel):
    supplier_cost: float
    margin_type: str
    margin_value: float
    final_price: float
    currency: str = "EUR"


class QuoteDraft(BaseModel):
    subject: str
    body: str