from src.core.models import Shipment


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

    cleaned = value.strip()

    if cleaned == "":
        return None

    return cleaned


def map_value(value: str | None, mapping: dict[str, str]) -> str | None:
    cleaned = normalize_text(value)

    if cleaned is None:
        return None

    key = cleaned.lower()

    return mapping.get(key, cleaned)


def normalize_shipment(shipment: Shipment) -> Shipment:
    """
    AI parser çıktısını operasyonel canonical değerlere dönüştürür.

    Bu katman çok kritik:
    AI farklı dillerde veya farklı terimlerle alanları çıkarabilir.
    Workflow motoru ise standart değerlerle çalışmalıdır.
    """

    shipment.customer_name = (
        shipment.customer_name.strip()
        if shipment.customer_name and shipment.customer_name.strip()
        else "Unknown Customer"
    )

    shipment.pickup_country = map_value(shipment.pickup_country, COUNTRY_MAP)
    shipment.delivery_country = map_value(shipment.delivery_country, COUNTRY_MAP)

    shipment.commodity = map_value(shipment.commodity, COMMODITY_MAP)

    shipment.service_type = map_value(shipment.service_type, SERVICE_TYPE_MAP) or "FTL"

    for package in shipment.packages:
        package.package_type = map_value(package.package_type, PACKAGE_TYPE_MAP) or "unknown"

    return shipment