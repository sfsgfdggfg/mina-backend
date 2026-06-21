import re
from typing import Optional, List
from pydantic import BaseModel, Field
from openai import OpenAI
from src.core.normalization import normalize_shipment
from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.core.models import Shipment, Package
from src.core.gtip import interpret_gtip_from_email

GENERIC_CUSTOMER_NAMES = {
    "",
    "-",
    "/",
    ".",
    ",",
    "unknown",
    "unknown customer",
    "none",
    "null",
    "müşteri",
    "firma",
    "şirket",
    "customer",
    "company",
    "client",
    "sender",
    "gönderen",
    "Test",
}


def clean_customer_name(customer_name: str | None, email_text: str) -> str:
    """
    AI parser bazen müşteri adı yokken generic/hayali değer döndürebilir.
    Bu fonksiyon müşteri adını deterministik olarak güvenli hale getirir.

    Kural:
    - Boş/generic değerler Unknown Customer olur.
    - Customer name email içinde açıkça geçmiyorsa ve çok genel görünüyorsa Unknown Customer olur.
    """

    if not customer_name:
        return "Unknown Customer"

    cleaned = customer_name.strip()

    if cleaned.lower() in GENERIC_CUSTOMER_NAMES:
        return "Unknown Customer"

    # Çok kısa ve anlamsız değerleri müşteri adı sayma
    if len(cleaned) <= 2:
        return "Unknown Customer"

    return cleaned

class ExtractedPackage(BaseModel):
    package_type: str = Field(default="unknown", description="Package type such as pallet, crate, machine, roll, loose")
    quantity: int = Field(default=1, description="Number of packages or pieces")
    length_cm: Optional[float] = Field(default=None, description="Length in centimeters")
    width_cm: Optional[float] = Field(default=None, description="Width in centimeters")
    height_cm: Optional[float] = Field(default=None, description="Height in centimeters")
    weight_kg: Optional[float] = Field(default=None, description="Weight per package or total package weight in kg")
    stackable: Optional[bool] = Field(default=None, description="Whether cargo is stackable")


class ShipmentExtraction(BaseModel):
    customer_name: str = Field(default="Unknown Customer", description="Customer name if known from the email")
    pickup_country: Optional[str] = Field(default=None, description="Pickup country")
    pickup_city: Optional[str] = Field(default=None, description="Pickup city")
    pickup_area: Optional[str] = Field(default=None, description="Pickup area, industrial zone, district")
    pickup_postcode: Optional[str] = Field(default=None, description="Pickup postcode if available")

    delivery_country: Optional[str] = Field(default=None, description="Delivery country")
    delivery_city: Optional[str] = Field(default=None, description="Delivery city")
    delivery_area: Optional[str] = Field(default=None, description="Delivery area, district")
    delivery_postcode: Optional[str] = Field(default=None, description="Delivery postcode if available")

    commodity: Optional[str] = Field(default=None, description="Cargo / product type")
    gross_weight_kg: Optional[float] = Field(default=None, description="Gross weight in kg")
    weight_is_approximate: bool = Field(default=True, description="Whether weight is approximate")

    service_type: str = Field(default="FTL", description="FTL or LTL. Default FTL unless partial is explicitly requested")
    equipment_type: Optional[str] = Field(default=None, description="Equipment requested by customer if explicitly stated")

    cargo_ready_date: Optional[str] = Field(default=None, description="Cargo ready date in YYYY-MM-DD format if possible")
    required_delivery_date: Optional[str] = Field(default=None, description="Required delivery date in YYYY-MM-DD format if possible")

    is_adr: bool = Field(default=False, description="Whether cargo is ADR / dangerous goods")
    adr_class: Optional[str] = Field(default=None, description="ADR class if mentioned")

    is_temperature_controlled: bool = Field(default=False, description="Whether temperature control is required")
    temperature_requirement: Optional[str] = Field(default=None, description="Temperature requirement such as +4C or -18C")

    is_high_value: bool = Field(default=False, description="Whether cargo appears high value or theft sensitive")
    special_notes: Optional[str] = Field(default=None, description="Other important operational notes")

    packages: List[ExtractedPackage] = Field(default_factory=list)


def parse_email_to_shipment(email_text: str) -> Shipment:
    """
    Mock parser.

    Scenario testleri için kalıyor.
    Gerçek AI parsing için parse_email_with_ai kullanılacak.
    """

    shipment = Shipment(
        customer_name="Demo Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        pickup_area="Adana Organize Sanayi Bölgesi",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        weight_is_approximate=True,
        service_type="FTL",
        cargo_ready_date="2026-06-15",
        packages=[
            Package(
                package_type="loose / textile",
                quantity=1,
                weight_kg=20000,
                stackable=None,
            )
        ],
        special_notes="Müşteri komple araç fiyat istemiştir.",
    )

    return shipment


COMMODITY_KEYWORD_OVERRIDES = [
    (r"\b(içecek|icecek|içecekler|icecekler|meşrubat|mesrubat|meşrubatlar|mesrubatlar)\b", "İçecek / Meşrubat"),
    (r"\b(trafo|trafolar|transformatör|transformator|transformer|transformers)\b", "Elektrik Transformatörü"),
    (r"\b(tekstil|textile|kumaş|kumas)\b", "Tekstil"),
    (r"\b(makine|makina|machine|machinery)\b", "Makine"),
]


def _apply_commodity_safety_overrides(shipment, email_text: str):
    """
    Raw email text can contain clear commodity signals.
    These deterministic overrides prevent the AI parser from returning
    overly generic commodity values such as "Gıda" when the email clearly says
    "içecek" or "meşrubat".
    """

    text = (email_text or "").lower()

    for pattern, canonical_commodity in COMMODITY_KEYWORD_OVERRIDES:
        if re.search(pattern, text):
            shipment.commodity = canonical_commodity
            break

    return shipment


def _apply_gtip_safety_overrides(shipment, email_text: str):
    """
    If the customer explicitly provides a GTIP / HS code, interpret it for
    operational commodity classification.

    MINAI does not assign legally binding GTIP codes. It only interprets
    customer-provided codes for freight operations.
    """

    gtip_info = interpret_gtip_from_email(email_text)

    shipment.gtip_code = gtip_info.get("gtip_code")
    shipment.hs_chapter = gtip_info.get("hs_chapter")
    shipment.hs_heading = gtip_info.get("hs_heading")
    shipment.hs_subheading = gtip_info.get("hs_subheading")
    shipment.gtip_detected_from_email = bool(gtip_info.get("gtip_detected_from_email"))

    commodity_match = gtip_info.get("commodity_match")

    if commodity_match:
        commodity_group = commodity_match.get("commodity_group")
        if commodity_group:
            shipment.commodity = commodity_group

        notes = commodity_match.get("notes") or []
        if notes:
            note_text = "[GTIP] " + " ".join(str(note) for note in notes)
            if shipment.special_notes:
                if note_text not in shipment.special_notes:
                    shipment.special_notes = shipment.special_notes + "\n" + note_text
            else:
                shipment.special_notes = note_text

    return shipment


def _apply_email_text_safety_overrides(shipment, email_text: str):
    """
    Critical logistics signals should not depend only on AI extraction.
    Raw email text overrides are deterministic and should have final priority.
    """

    text = (email_text or "").lower()

    adr_match = re.search(r"\\badr\\b[^0-9]{0,20}\\b(1|7)\b", text)
    class_match = re.search(r"\\bclass\\s*(1|7)\b", text)

    match = adr_match or class_match

    if match:
        adr_class = match.group(1)

        shipment.is_adr = True
        shipment.adr_class = adr_class

        if not shipment.commodity:
            shipment.commodity = f"ADR Class {adr_class}"

    shipment = _apply_commodity_safety_overrides(shipment, email_text)
    shipment = _apply_gtip_safety_overrides(shipment, email_text)

    return shipment


def parse_email_with_ai(email_text: str) -> Shipment:
    """
    OpenAI structured email parser.

    Düzensiz müşteri mailinden Shipment objesi üretir.
    """

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY bulunamadı. Lütfen .env dosyasını kontrol edin.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.beta.chat.completions.parse(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Sen uluslararası karayolu lojistiği ve freight forwarding operasyonlarında uzman bir asistansın. "
                    "Görevin müşteri emailinden shipment bilgilerini çıkarmaktır. "
                    "Bilgi mailde yoksa uydurma. "
                    "Müşteri parsiyel istemedikçe service_type değerini FTL kabul et. "
                    "Özel ekipman sadece açıkça belirtilmişse çıkar. "
                    "ADR, reefer, yüksek değerli yük gibi riskli bilgileri asla varsayma. "
                    "Tarihleri mümkünse YYYY-MM-DD formatına çevir. Emin değilsen null bırak."
                    "Ülke ve ürün adlarını mümkünse Türkçe canonical değerlerle çıkar: Türkiye, Almanya, Makine, Tekstil, Gıda gibi."
                ),
            },
            {
                "role": "user",
                "content": email_text,
            },
        ],
        response_format=ShipmentExtraction,
    )

    extracted = response.choices[0].message.parsed

    packages = [
        Package(
            package_type=p.package_type,
            quantity=p.quantity,
            length_cm=p.length_cm,
            width_cm=p.width_cm,
            height_cm=p.height_cm,
            weight_kg=p.weight_kg,
            stackable=p.stackable,
        )
        for p in extracted.packages
    ]
    shipment = Shipment(
        customer_name=clean_customer_name(
            customer_name=extracted.customer_name,
            email_text=email_text,
        ),
        pickup_country=extracted.pickup_country,
        pickup_city=extracted.pickup_city,
        pickup_area=extracted.pickup_area,
        pickup_postcode=extracted.pickup_postcode,
        delivery_country=extracted.delivery_country,
        delivery_city=extracted.delivery_city,
        delivery_area=extracted.delivery_area,
        delivery_postcode=extracted.delivery_postcode,
        commodity=extracted.commodity,
        gross_weight_kg=extracted.gross_weight_kg,
        weight_is_approximate=extracted.weight_is_approximate,
        service_type=extracted.service_type,
        equipment_type=extracted.equipment_type,
        cargo_ready_date=extracted.cargo_ready_date,
        required_delivery_date=extracted.required_delivery_date,
        is_adr=extracted.is_adr,
        adr_class=extracted.adr_class,
        is_temperature_controlled=extracted.is_temperature_controlled,
        temperature_requirement=extracted.temperature_requirement,
        is_high_value=extracted.is_high_value,
        special_notes=extracted.special_notes,
        packages=packages,
    )

    shipment = _apply_email_text_safety_overrides(shipment, email_text)
    return normalize_shipment(shipment)