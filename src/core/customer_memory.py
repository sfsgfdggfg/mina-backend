from pydantic import BaseModel, Field
from typing import Optional, List

from src.core.models import Shipment


class CustomerMemoryProfile(BaseModel):
    customer_name: str
    aliases: List[str] = Field(default_factory=list)

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None

    default_pickup_city: Optional[str] = None
    default_pickup_area: Optional[str] = None
    default_pickup_country: Optional[str] = None

    default_delivery_city: Optional[str] = None
    default_delivery_country: Optional[str] = None

    operational_notes: List[str] = Field(default_factory=list)


CUSTOMER_MEMORY = [
    CustomerMemoryProfile(
        customer_name="Oğuz Gıda",
        aliases=["oguz gida", "oğuz gıda", "oguz", "oğuz"],
        default_commodity="Meşrubat",
        default_equipment_type="Kapalı Kasa / Box Trailer",
        price_sensitivity="medium",
        time_sensitivity="medium",
        default_pickup_city="Adana",
        default_pickup_area="Adana Organize Sanayi Bölgesi",
        default_pickup_country="Türkiye",
        operational_notes=[
            "Müşteri genellikle meşrubat taşır.",
            "Meşrubat yüklerinde kapalı kasa tercih edilir.",
            "Ürün ölçüleri ve yükleme düzeni genellikle standarttır.",
        ],
    ),
    CustomerMemoryProfile(
        customer_name="Beta Enerji",
        aliases=["beta enerji", "beta", "beta energy"],
        default_commodity="Elektrik Transformatörü",
        default_equipment_type="Tenteli / Curtainsider",
        price_sensitivity="medium",
        time_sensitivity="medium",
        default_pickup_country="Türkiye",
        operational_notes=[
            "Müşteri elektrik transformatörü üretir.",
            "Trafo / makine yüklerinde ölçü ve ağırlık bilgisi önemlidir.",
            "Uygun ölçülerde tenteli araçla taşınabilir.",
        ],
    ),
    CustomerMemoryProfile(
        customer_name="Temsa",
        aliases=["temsa", "temsa otomotiv"],
        default_commodity="Otomotiv Parçası",
        default_equipment_type="Tenteli / Curtainsider",
        price_sensitivity="medium",
        time_sensitivity="high",
        default_pickup_city="Adana",
        default_pickup_country="Türkiye",
        operational_notes=[
            "Otomotiv müşterisi olduğu için süre hassasiyeti yüksek olabilir.",
            "İthalat operasyonlarında süre hassasiyeti artar.",
            "İhracat operasyonlarında fiyat hassasiyeti daha belirgin olabilir.",
        ],
    ),
]


class CustomerMemoryResult(BaseModel):
    matched: bool = False
    profile: Optional[CustomerMemoryProfile] = None
    notes_applied: List[str] = Field(default_factory=list)


def find_customer_profile(customer_name: Optional[str]) -> Optional[CustomerMemoryProfile]:
    if not customer_name:
        return None

    normalized_name = customer_name.strip().lower()

    if normalized_name in ["unknown customer", "", "none", "null"]:
        return None

    for profile in CUSTOMER_MEMORY:
        names_to_check = [profile.customer_name.lower()] + [
            alias.lower() for alias in profile.aliases
        ]

        if normalized_name in names_to_check:
            return profile

    return None

def find_customer_profile_in_text(text: Optional[str]) -> Optional[CustomerMemoryProfile]:
    if not text:
        return None

    normalized_text = text.lower()

    for profile in CUSTOMER_MEMORY:
        names_to_check = [profile.customer_name.lower()] + [
            alias.lower() for alias in profile.aliases
        ]

        for name in names_to_check:
            if name in normalized_text:
                return profile

    return None

def enrich_shipment_with_customer_memory(
    shipment: Shipment,
    email_text: Optional[str] = None,
) -> CustomerMemoryResult:
    """
    Customer Memory v1.

    Eşleşme sırası:
    1. shipment.customer_name
    2. raw email text içinde customer alias/name arama

    İleride email sender, domain, signature ve historical context ile güçlenecek.
    """

    profile = find_customer_profile(shipment.customer_name)

    if not profile and email_text:
        profile = find_customer_profile_in_text(email_text)

    if not profile:
        return CustomerMemoryResult(
            matched=False,
            profile=None,
            notes_applied=[],
        )

    notes_applied = []

    shipment.customer_name = profile.customer_name

    if not shipment.commodity and profile.default_commodity:
        shipment.commodity = profile.default_commodity
        notes_applied.append(f"Ürün müşteri hafızasından tamamlandı: {profile.default_commodity}")

    if not shipment.equipment_type and profile.default_equipment_type:
        shipment.equipment_type = profile.default_equipment_type
        notes_applied.append(f"Varsayılan ekipman müşteri hafızasından geldi: {profile.default_equipment_type}")

    if not shipment.pickup_city and profile.default_pickup_city:
        shipment.pickup_city = profile.default_pickup_city
        notes_applied.append(f"Yükleme şehri müşteri hafızasından tamamlandı: {profile.default_pickup_city}")

    if not shipment.pickup_area and profile.default_pickup_area:
        shipment.pickup_area = profile.default_pickup_area
        notes_applied.append(f"Yükleme bölgesi müşteri hafızasından tamamlandı: {profile.default_pickup_area}")

    if not shipment.pickup_country and profile.default_pickup_country:
        shipment.pickup_country = profile.default_pickup_country
        notes_applied.append(f"Yükleme ülkesi müşteri hafızasından tamamlandı: {profile.default_pickup_country}")

    if not shipment.delivery_city and profile.default_delivery_city:
        shipment.delivery_city = profile.default_delivery_city
        notes_applied.append(f"Teslim şehri müşteri hafızasından tamamlandı: {profile.default_delivery_city}")

    if not shipment.delivery_country and profile.default_delivery_country:
        shipment.delivery_country = profile.default_delivery_country
        notes_applied.append(f"Teslim ülkesi müşteri hafızasından tamamlandı: {profile.default_delivery_country}")

    notes_applied.extend(profile.operational_notes)

    return CustomerMemoryResult(
        matched=True,
        profile=profile,
        notes_applied=notes_applied,
    )