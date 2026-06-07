from src.core.models import Shipment, EquipmentDecision


def decide_equipment(shipment: Shipment) -> EquipmentDecision:
    """
    Equipment Decision Engine v1.
    Default: Tenteli.
    Override rules apply if special conditions are detected.
    """

    # Reefer trigger
    if shipment.is_temperature_controlled or shipment.temperature_requirement:
        return EquipmentDecision(
            selected_equipment="Reefer",
            reason="Sıcaklık kontrollü yük tespit edildi.",
            confidence=0.95,
        )

    # ADR high-risk trigger
    if shipment.is_adr and shipment.adr_class in ["1", "7"]:
        return EquipmentDecision(
            selected_equipment="Special ADR Equipment",
            reason="ADR Class 1 veya 7 özel ekipman gerektirir.",
            confidence=0.95,
        )

    # Package dimension triggers
    for package in shipment.packages:
        if package.height_cm and package.height_cm > 300:
            return EquipmentDecision(
                selected_equipment="Lowbed / Project Cargo",
                reason="Yük yüksekliği 3.00m üzerindedir.",
                confidence=0.90,
            )

        if package.height_cm and package.height_cm > 285:
            return EquipmentDecision(
                selected_equipment="Mega Trailer",
                reason="Yük yüksekliği 2.85m üzerindedir.",
                confidence=0.85,
            )

        if package.width_cm and package.width_cm > 250:
            return EquipmentDecision(
                selected_equipment="Platform / Lowbed",
                reason="Yük genişliği 2.50m üzerindedir.",
                confidence=0.90,
            )

        if package.weight_kg and package.weight_kg >= 26000:
            return EquipmentDecision(
                selected_equipment="Lowbed / Heavy Haul",
                reason="Tek parça yük 26 ton veya üzerindedir.",
                confidence=0.90,
            )

    # High value cargo
    if shipment.is_high_value:
        return EquipmentDecision(
            selected_equipment="Box Trailer",
            reason="Yüksek değerli yük için kapalı kasa önerilir.",
            confidence=0.75,
        )
    
    # Customer memory / explicit equipment preference
    if shipment.equipment_type:
        return EquipmentDecision(
            selected_equipment=shipment.equipment_type,
            reason="Ekipman tipi müşteri hafızası veya müşteri talebi üzerinden belirlendi.",
            confidence=0.85,
        )

    # Default
    return EquipmentDecision(
        selected_equipment="Tenteli / Curtainsider",
        reason="Özel ekipman gereksinimi tespit edilmedi. Varsayılan road ekipmanı kullanıldı.",
        confidence=0.80,
    )