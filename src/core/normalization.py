from src.core.models import Shipment


NULL_LIKE_VALUES = {
    "",
    "/",
    "-",
    ",",
    ".",
    "n/a",
    "na",
    "none",
    "null",
    "unknown",
    "müşteri",
    "customer",
    "bilinmiyor",
    "belirtilmemiş",
}


COUNTRY_MAP = {
    "turkey": "Türkiye",
    "türkiye": "Türkiye",
    "tr": "Türkiye",

    "germany": "Almanya",
    "almanya": "Almanya",
    "de": "Almanya",

    "france": "Fransa",
    "fransa": "Fransa",

    "austria": "Avusturya",
    "avusturya": "Avusturya",

    "romania": "Romanya",
    "romanya": "Romanya",
}


COMMODITY_MAP = {
    "machine": "Makine",
    "machinery": "Makine",
    "makina": "Makine",
    "makine": "Makine",

    "textile": "Tekstil",
    "textiles": "Tekstil",
    "tekstil": "Tekstil",

    "food": "Gıda",
    "food product": "Gıda",
    "gıda": "Gıda",
    "gıda ürünü": "Gıda",

    "adr cargo": "ADR Yük",
    "adr yük": "ADR Yük",
}


PACKAGE_TYPE_MAP = {
    "machine": "machine",
    "machinery": "machine",
    "makine": "machine",
    "makina": "machine",

    "pallet": "pallet",
    "palet": "pallet",

    "crate": "crate",
    "sandık": "crate",

    "roll": "roll",
    "rulo": "roll",

    "loose": "loose",
}


SERVICE_TYPE_MAP = {
    "ftl": "FTL",
    "full truck": "FTL",
    "full truckload": "FTL",
    "komple": "FTL",
    "komple araç": "FTL",

    "ltl": "LTL",
    "partial": "LTL",
    "parsiyel": "LTL",
}


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned = str(value).strip()

    if cleaned.lower() in NULL_LIKE_VALUES:
        return None

    # Sadece noktalama işaretlerinden oluşuyorsa geçersiz say
    if all(char in ".,;:/\\|-_()[]{}" for char in cleaned):
        return None

    return cleaned


def map_value(value: str | None, mapping: dict[str, str]) -> str | None:
    cleaned = normalize_text(value)

    if cleaned is None:
        return None

    return mapping.get(cleaned.lower(), cleaned)


def normalize_shipment(shipment: Shipment) -> Shipment:
    """
    AI parser çıktısını operasyonel canonical değerlere dönüştürür.
    """

    customer_name = normalize_text(shipment.customer_name)
    shipment.customer_name = customer_name or "Unknown Customer"

    shipment.pickup_country = map_value(shipment.pickup_country, COUNTRY_MAP)
    shipment.pickup_city = normalize_text(shipment.pickup_city)
    shipment.pickup_area = normalize_text(shipment.pickup_area)
    shipment.pickup_postcode = normalize_text(shipment.pickup_postcode)

    shipment.delivery_country = map_value(shipment.delivery_country, COUNTRY_MAP)
    shipment.delivery_city = normalize_text(shipment.delivery_city)
    shipment.delivery_area = normalize_text(shipment.delivery_area)
    shipment.delivery_postcode = normalize_text(shipment.delivery_postcode)

    shipment.commodity = map_value(shipment.commodity, COMMODITY_MAP)

    shipment.service_type = map_value(shipment.service_type, SERVICE_TYPE_MAP) or "FTL"
    shipment.equipment_type = normalize_text(shipment.equipment_type)

    shipment.cargo_ready_date = normalize_text(shipment.cargo_ready_date)
    shipment.required_delivery_date = normalize_text(shipment.required_delivery_date)

    shipment.adr_class = normalize_text(shipment.adr_class)
    shipment.temperature_requirement = normalize_text(shipment.temperature_requirement)
    shipment.special_notes = normalize_text(shipment.special_notes)

    for package in shipment.packages:
        package.package_type = map_value(package.package_type, PACKAGE_TYPE_MAP) or "unknown"

    return shipment