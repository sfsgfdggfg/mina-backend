from src.core.models import Shipment, EquipmentDecision

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

    # Package dimension triggers
    for package in shipment.packages:
        if package.height_cm and package.height_cm > 300:
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

        if package.height_cm and package.height_cm > 285:
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

        if package.width_cm and package.width_cm > 250:
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

        if package.weight_kg and package.weight_kg >= 26000:
            return EquipmentDecision(
                selected_equipment="Lowbed / Heavy Haul",
                reason="Tek parça yük 26 ton veya üzerindedir.",
                confidence=0.90,
                source="rule_engine",
                explanation=(
                    f"Tek parça ağırlık {package.weight_kg} kg olarak tespit edildi. "
                    "Standart tenteli araç için ağır yük riski olduğundan Lowbed / Heavy Haul değerlendirilmelidir."
                ),
            )

    # High value cargo
    if shipment.is_high_value:
        return EquipmentDecision(
            selected_equipment="Box Trailer",
            reason="Yüksek değerli yük için kapalı kasa önerilir.",
            confidence=0.75,
            source="rule_engine",
            explanation=(
                "Yük yüksek değerli veya hırsızlık riski taşıyan kargo olarak işaretlendi. "
                "Bu nedenle sert duvarlı kapalı kasa ekipman önerildi."
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