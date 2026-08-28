from src.core.models import Shipment, RiskAssessment
from src.core.commodity_profile import get_commodity_operational_profile
from src.core.cargo_weight import assess_cargo_weight
from src.core.extraction_confirmation import require_operational_shipment


def assess_risk(shipment: Shipment, customer_memory=None) -> RiskAssessment:
    """
    Operational Risk Engine v1.
    """

    require_operational_shipment(shipment)
    risk_reasons = []
    requires_human_review = False
    requires_management_review = False

    # New/unknown customer
    unknown_customer_values = {
        "",
        "unknown customer",
        "unknown",
        "none",
        "null",
        "müşteri",
        "customer",
        "-",
        "/",
    }

    customer_name = (shipment.customer_name or "").strip().lower()

    if customer_name in unknown_customer_values:
        risk_reasons.append("Yeni veya tanınmayan müşteri.")
        requires_human_review = True

    # Customer sensitivity from memory
    if customer_memory and customer_memory.matched and customer_memory.profile:
        profile = customer_memory.profile

        if profile.time_sensitivity == "high":
            risk_reasons.append(
                "[Customer Memory → Risk Engine] Müşteri süre hassasiyetine sahip. Transit süre ve termin ayrıca kontrol edilmeli."
            )
            requires_human_review = True

        if profile.price_sensitivity == "high":
            risk_reasons.append(
                "[Customer Memory → Risk Engine] Müşteri fiyat hassasiyetine sahip. Piyasa fiyatı ve marj ayrıca kontrol edilmeli."
            )
            requires_human_review = True

    # ADR risk
    if shipment.is_adr and not shipment.adr_class:
        risk_reasons.append(
            "Yük ADR kapsamında belirtilmiş ancak ADR sınıfı eksik."
        )
        requires_human_review = True

    elif shipment.is_adr and shipment.adr_class in ["1", "7"]:
        risk_reasons.append("Yüksek riskli ADR sınıfı.")
        requires_management_review = True
        requires_human_review = True

    elif shipment.is_adr:
        risk_reasons.append(
            f"ADR Class {shipment.adr_class} yük. ADR taşıma şartları ayrıca kontrol edilmeli."
        )
        requires_human_review = True

    # Temperature controlled cargo
    if shipment.is_temperature_controlled or shipment.temperature_requirement:
        risk_reasons.append(
            "Sıcaklık kontrollü yük. Reefer uygunluğu ve sıcaklık gereksinimi ayrıca kontrol edilmeli."
        )
        requires_human_review = True

    # High-value cargo is a review signal, not an automatic scope block.
    if shipment.is_high_value:
        risk_reasons.append(
            "Yük yüksek değerli olarak teyit edildi. Taşıyıcı sorumluluk limiti, "
            "gerekirse ek emtia sigortası ve güvenlik/taşıyıcı kabul şartları kontrol edilmeli."
        )
        requires_human_review = True

    # Commodity operational profile
    commodity_profile = get_commodity_operational_profile(shipment.commodity)
    if commodity_profile.get("requires_human_review"):
        risk_reasons.append(
            commodity_profile.get("risk_reason")
            or "Commodity operational profile requires human review."
        )
        requires_human_review = True

    if commodity_profile.get("requires_management_review"):
        requires_management_review = True
        requires_human_review = True

    # Heavy / oversize
    cargo_weight = assess_cargo_weight(shipment)

    if cargo_weight.is_confirmed_heavy_single_piece:
        risk_reasons.append("Teyit edilebilir tek parça ağır yük.")
        requires_human_review = True
    elif cargo_weight.requires_clarification:
        risk_reasons.append(
            "Tek parça ve toplam ağırlık ayrımı net değil."
        )
        requires_human_review = True

    for package in shipment.packages:
        if package.height_cm and package.height_cm > 300:
            risk_reasons.append("Gabari dışı yük yüksekliği.")
            requires_human_review = True

        if package.width_cm and package.width_cm > 250:
            risk_reasons.append("Gabari dışı yük genişliği.")
            requires_human_review = True

    # Missing dimensions for machine cargo
    if shipment.commodity and "makine" in shipment.commodity.lower():
        has_dimensions = any(
            p.length_cm and p.width_cm and p.height_cm
            for p in shipment.packages
        )
        if not has_dimensions:
            risk_reasons.append("Makine yükünde ölçü bilgisi eksik.")
            requires_human_review = True

    if requires_management_review:
        risk_level = "red"
    elif requires_human_review:
        risk_level = "yellow"
    else:
        risk_level = "green"

    return RiskAssessment(
        risk_level=risk_level,
        risk_reasons=risk_reasons,
        requires_human_review=requires_human_review,
        requires_management_review=requires_management_review,
    )
