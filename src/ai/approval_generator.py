from src.core.models import Shipment, QuoteDraft, RiskAssessment


def generate_management_review_draft(
    shipment: Shipment,
    risk_assessment: RiskAssessment,
) -> QuoteDraft:
    """
    Management Review Draft Generator v1.

    RED risk durumlarında müşteriye quote üretmek yerine,
    iç onay / yönetici incelemesi için taslak üretir.
    """

    subject = "Yönetici Onayı Gereken Taşıma Talebi"

    risk_reasons_text = "\n".join(
        f"- {reason}" for reason in risk_assessment.risk_reasons
    )

    route_text = build_route_text(shipment)

    body = f"""
Aşağıdaki taşıma talebi RED risk seviyesinde değerlendirilmiştir.

{route_text}

Müşteri: {shipment.customer_name}
Yük: {shipment.commodity or "Belirtilmemiş"}
Brüt Ağırlık: {shipment.gross_weight_kg or "Belirtilmemiş"} kg
Servis Tipi: {shipment.service_type}

Risk nedenleri:
{risk_reasons_text}

Bu talep için müşteriye teklif hazırlanmadan önce yönetici / senior operasyon onayı gerekmektedir.

Önerilen aksiyon:
- Taşıma kabul kriterleri kontrol edilmeli
- Tedarikçi uygunluğu ayrıca doğrulanmalı
- Sigorta / mevzuat / özel izin gereklilikleri incelenmeli
- Müşteriye dönüş yapılmadan önce karar netleştirilmelidir

MINAI Freight OS
""".strip()

    return QuoteDraft(
        subject=subject,
        body=body,
    )


def build_route_text(shipment: Shipment) -> str:
    pickup = ", ".join(
        part for part in [
            shipment.pickup_city,
            shipment.pickup_country,
        ]
        if part
    )

    delivery = ", ".join(
        part for part in [
            shipment.delivery_city,
            shipment.delivery_country,
        ]
        if part
    )

    if pickup and delivery:
        return f"Güzergah: {pickup} → {delivery}"

    return "Güzergah bilgisi net değildir."