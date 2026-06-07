from src.core.models import Shipment, RiskAssessment


def assess_risk(shipment: Shipment, customer_memory=None) -> RiskAssessment:
    """
    Operational Risk Engine v1.
    """

    risk_reasons = []
    requires_human_review = False
    requires_management_review = False

    # New/unknown customer
    if shipment.customer_name == "Unknown Customer":
        risk_reasons.append("Yeni veya tanınmayan müşteri.")
        requires_human_review = True

    # Customer sensitivity from memory
    if customer_memory and customer_memory.matched and customer_memory.profile:
        profile = customer_memory.profile

        if profile.time_sensitivity == "high":
            risk_reasons.append(
                "Müşteri süre hassasiyetine sahip. Transit süre ve termin ayrıca kontrol edilmeli."
            )
            requires_human_review = True

        if profile.price_sensitivity == "high":
            risk_reasons.append(
                "Müşteri fiyat hassasiyetine sahip. Piyasa fiyatı ve marj ayrıca kontrol edilmeli."
            )
            requires_human_review = True

    # ADR high-risk
    if shipment.is_adr and shipment.adr_class in ["1", "7"]:
        risk_reasons.append("Yüksek riskli ADR sınıfı.")
        requires_management_review = True
        requires_human_review = True

    # Heavy / oversize
    for package in shipment.packages:
        if package.weight_kg and package.weight_kg >= 26000:
            risk_reasons.append("Tek parça ağır yük.")
            requires_human_review = True

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