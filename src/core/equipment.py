from src.core.models import Shipment, EquipmentDecision
from src.core.commodity_profile import get_commodity_operational_profile
from src.core.cargo_weight import assess_cargo_weight
from src.core.extraction_confirmation import require_operational_shipment
from src.core.road_dimensions import (
    MEGA_TRAILER_HEIGHT_TRIGGER_CM,
    PROJECT_CARGO_HEIGHT_CM,
    STANDARD_TRAILER_LENGTH_CM,
    STANDARD_TRAILER_WIDTH_CM,
)

def _normalize_equipment_request(value: str | None) -> str:
    normalized = (
        str(value or "")
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ç", "c")
        .replace("Ç", "c")
        .replace("ğ", "g")
        .replace("Ğ", "g")
    )
    for separator in ("/", "-", "_"):
        normalized = normalized.replace(separator, " ")
    return " ".join(normalized.split())


def is_standard_road_equipment_request(value: str | None) -> bool:
    """Return whether an explicit request stays inside the standard Tenteli pilot."""
    if value is None or not str(value).strip():
        return True
    return _normalize_equipment_request(value) in {
        "tenteli",
        "curtainsider",
        "curtain sider",
        "curtain",
        "tenteli curtainsider",
    }




def requires_open_trailer_loading(shipment: Shipment) -> bool:
    """Detect explicit top-loading / crane-loading requirements from shipment notes."""
    text = _normalize_equipment_request(getattr(shipment, "special_notes", None))
    if not text:
        return False
    signals = (
        "overhead crane",
        "tavan vinci",
        "crane loading",
        "ustten yukleme",
    )
    return any(signal in text for signal in signals)


def requires_bulk_or_liquid_equipment_review(shipment: Shipment) -> bool:
    """Detect explicit bulk/liquid cargo evidence that requires non-standard equipment review."""
    values = [
        getattr(shipment, "commodity", None),
        getattr(shipment, "special_notes", None),
        *(getattr(package, "package_type", None) for package in shipment.packages),
    ]
    text = _normalize_equipment_request(" ".join(str(value) for value in values if value))
    if not text:
        return False
    signals = (
        "dokme yuk",
        "dokme urun",
        "sivi yuk",
        "sivi urun",
        "bulk cargo",
        "bulk load",
        "liquid cargo",
        "liquid load",
        "tanker",
        "damper",
        "silobas",
    )
    return any(signal in text for signal in signals)

def _has_meaningful_text(value):
    if value is None:
        return False

    if not isinstance(value, str):
        return bool(value)

    normalized = value.strip().lower()

    null_like_values = {
        "",
        "null",
        "/null/",
        "none",
        "n/a",
        "na",
        "-",
        "belirtilmemiş",
        "unknown",
    }

    return normalized not in null_like_values


def decide_equipment(shipment: Shipment) -> EquipmentDecision:
    """
    Equipment Decision Engine v1.

    Default: Tenteli.
    Override rules apply if special conditions are detected.
    """

    require_operational_shipment(shipment)

    # Reefer trigger
    if shipment.is_temperature_controlled or _has_meaningful_text(shipment.temperature_requirement):
        return EquipmentDecision(
            selected_equipment="Reefer",
            reason="Sıcaklık kontrollü yük tespit edildi.",
            confidence=0.95,
            source="rule_engine",
            explanation=(
                "Email veya shipment verisinde sıcaklık kontrollü taşıma ihtiyacı tespit edildi. "
                "Tenteli araç sıcaklık kontrolü sağlayamayacağı için Reefer seçildi."
            ),
        )

    # ADR class must be known before final equipment selection
    if shipment.is_adr and not _has_meaningful_text(shipment.adr_class):
        return EquipmentDecision(
            selected_equipment="ADR Equipment Review",
            reason="ADR sınıfı belirtilmemiştir.",
            confidence=0.40,
            source="rule_engine",
            explanation=(
                "Yük ADR kapsamında belirtilmiştir ancak ADR sınıfı bilinmemektedir. "
                "ADR sınıfı netleşmeden standart veya özel ADR ekipmanı seçilmemelidir."
            ),
        )

    # ADR high-risk trigger
    if shipment.is_adr and shipment.adr_class in ["1", "7"]:
        return EquipmentDecision(
            selected_equipment="Special ADR Equipment",
            reason="ADR Class 1 veya 7 özel ekipman gerektirir.",
            confidence=0.95,
            source="rule_engine",
            explanation=(
                "Yük ADR Class 1 veya Class 7 kapsamında olduğu için standart ekipmanla ilerlenmez. "
                "Özel ADR ekipmanı ve yönetici / senior operasyon kontrolü gerekir."
            ),
        )

    # Other known ADR classes require ADR-capable equipment
    if shipment.is_adr and _has_meaningful_text(shipment.adr_class):
        return EquipmentDecision(
            selected_equipment="ADR-Capable Equipment",
            reason=f"ADR Class {shipment.adr_class} yük tespit edildi.",
            confidence=0.90,
            source="rule_engine",
            explanation=(
                f"Yük ADR Class {shipment.adr_class} kapsamında belirtilmiştir. "
                "Class 1 ve 7 dışındaki ADR yüklerinde de ADR uyumlu araç, "
                "sürücü ve taşıyıcı doğrulanmalıdır."
            ),
        )

    # Commodity profile reefer trigger
    commodity_profile = get_commodity_operational_profile(shipment.commodity)
    if commodity_profile.get("requires_reefer") or commodity_profile.get("default_equipment") == "Reefer":
        return EquipmentDecision(
            selected_equipment="Reefer",
            reason="Commodity operational profile reefer ekipman gerektiriyor.",
            confidence=0.90,
            source="commodity_operational_profile",
            explanation=(
                "Ürün grubu operasyonel profili reefer / sıcaklık kontrollü taşıma ihtiyacı gösteriyor. "
                "Bu nedenle Reefer seçildi."
            ),
        )

    # Package dimension triggers
    for package in shipment.packages:
        if package.length_cm and package.length_cm > STANDARD_TRAILER_LENGTH_CM:
            return EquipmentDecision(
                selected_equipment="Lowbed / Project Cargo",
                reason="Yük uzunluğu standart 13.60m dorse sınırını aşmaktadır.",
                confidence=0.90,
                source="rule_engine",
                explanation=(
                    f"Yük uzunluğu {package.length_cm} cm olarak tespit edildi. "
                    "Standart 13.60m tenteli dorse profilini aştığı için "
                    "Lowbed / Project Cargo değerlendirilmelidir."
                ),
            )

        if package.height_cm and package.height_cm > PROJECT_CARGO_HEIGHT_CM:
            return EquipmentDecision(
                selected_equipment="Lowbed / Project Cargo",
                reason="Yük yüksekliği 3.00m üzerindedir.",
                confidence=0.90,
                source="rule_engine",
                explanation=(
                    f"Yük yüksekliği {package.height_cm} cm olarak tespit edildi. "
                    "Bu yükseklik Mega dorse sınırını da aşabileceği için Lowbed / Project Cargo değerlendirilmelidir."
                ),
            )

        if package.height_cm and package.height_cm > MEGA_TRAILER_HEIGHT_TRIGGER_CM:
            return EquipmentDecision(
                selected_equipment="Mega Trailer",
                reason="Yük yüksekliği 2.85m üzerindedir.",
                confidence=0.85,
                source="rule_engine",
                explanation=(
                    f"Yük yüksekliği {package.height_cm} cm olarak tespit edildi. "
                    "Standart tenteli araç iç yüksekliği için riskli olduğundan Mega Trailer seçildi."
                ),
            )

        if package.width_cm and package.width_cm > STANDARD_TRAILER_WIDTH_CM:
            return EquipmentDecision(
                selected_equipment="Platform / Lowbed",
                reason="Yük genişliği 2.50m üzerindedir.",
                confidence=0.90,
                source="rule_engine",
                explanation=(
                    f"Yük genişliği {package.width_cm} cm olarak tespit edildi. "
                    "Standart dorse genişlik sınırını aşabileceği için Platform / Lowbed değerlendirilmelidir."
                ),
            )

    cargo_weight = assess_cargo_weight(shipment)

    if cargo_weight.is_confirmed_heavy_single_piece:
        return EquipmentDecision(
            selected_equipment="Lowbed / Heavy Haul",
            reason="Teyit edilebilir tek parça yük 26 ton veya üzerindedir.",
            confidence=0.90,
            source="rule_engine",
            explanation=(
                "Tek parça ağırlık "
                f"{cargo_weight.confirmed_single_piece_weight_kg} kg olarak "
                "tespit edildi. Standart tenteli araç için ağır yük "
                "riski olduğundan Lowbed / Heavy Haul değerlendirilmelidir."
            ),
        )

    if cargo_weight.requires_clarification:
        return EquipmentDecision(
            selected_equipment="Heavy Cargo Equipment Review",
            reason="Tek parça ve toplam ağırlık ayrımı net değildir.",
            confidence=0.35,
            source="rule_engine",
            explanation=(
                "Mevcut ağırlık bilgisi tek parça ağırlığı ile "
                "shipment brüt veya package-line toplam ağırlığını "
                "güvenle ayırmıyor. Ekipman atanmadan önce paket adedi ve "
                "parça başı ağırlıklar netleştirilmelidir."
            ),
        )

    # Bulk / liquid cargo requires equipment review before ordinary Tenteli handling.
    if (
        requires_bulk_or_liquid_equipment_review(shipment)
        and is_standard_road_equipment_request(shipment.equipment_type)
    ):
        return EquipmentDecision(
            selected_equipment="Bulk / Liquid Equipment Review",
            reason="Dökme veya sıvı yük için özel ekipman değerlendirmesi gerekir.",
            confidence=0.85,
            source="rule_engine",
            explanation=(
                "Shipment verisinde dökme/sıvı yük veya Tanker/Damper/Silobas ihtiyacı "
                "gösteren açık bir sinyal bulundu. Uygun ekipman tipi netleştirilmeden "
                "standart Tenteli atanmamalıdır."
            ),
        )

    # Explicit top-loading / crane-loading requirement
    if (
        requires_open_trailer_loading(shipment)
        and is_standard_road_equipment_request(shipment.equipment_type)
    ):
        return EquipmentDecision(
            selected_equipment="Open Trailer / Platform",
            reason="Üstten / vinç ile yükleme gereksinimi tespit edildi.",
            confidence=0.90,
            source="rule_engine",
            explanation=(
                "Shipment notlarında overhead crane / tavan vinci / crane loading / "
                "üstten yükleme gereksinimi bulundu. Standart Tenteli yerine "
                "Open Trailer / Platform değerlendirilmelidir."
            ),
        )

    # Customer memory / explicit equipment preference
    if shipment.equipment_type:
        return EquipmentDecision(
            selected_equipment=shipment.equipment_type,
            reason="Ekipman tipi müşteri hafızası veya müşteri talebi üzerinden belirlendi.",
            confidence=0.85,
            source="customer_memory_or_customer_request",
            explanation=(
                f"Shipment üzerinde ekipman tipi '{shipment.equipment_type}' olarak geldi. "
                "Bu bilgi müşteri hafızasından veya müşteri talebinden geldiği için ekipman kararı bu değere göre verildi."
            ),
        )

    # Default
    return EquipmentDecision(
        selected_equipment="Tenteli / Curtainsider",
        reason="Özel ekipman gereksinimi tespit edilmedi. Varsayılan road ekipmanı kullanıldı.",
        confidence=0.80,
        source="default_rule",
        explanation=(
            "Sıcaklık kontrollü taşıma, ADR özel sınıf, gabari dışı ölçü, ağır yük veya yüksek değerli yük gibi "
            "özel ekipman gerektiren bir durum tespit edilmedi. Bu nedenle varsayılan karayolu ekipmanı olarak "
            "Tenteli / Curtainsider seçildi."
        ),
    )
