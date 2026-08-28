from src.core.models import Shipment, EquipmentDecision, RiskAssessment, SupplierQuote, CustomerQuote, QuoteDraft


def generate_quote_draft(
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    risk_assessment: RiskAssessment,
    supplier_quote: SupplierQuote,
    customer_quote: CustomerQuote,
) -> QuoteDraft:
    """Generate firm or explicitly non-binding indicative customer quote."""

    indicative = getattr(shipment, "quote_mode", "firm") == "indicative"
    subject = (
        "İndikatif Taşıma Fiyatı"
        if indicative
        else "Taşıma Teklifimiz Hakkında"
    )
    risk_note = ""
    if risk_assessment.risk_level != "green":
        risk_note = (
            "\n\nNot: Bu taşıma talebinde operasyonel dikkat gerektiren noktalar bulunmaktadır. "
            "Detaylar operasyon ekibimiz tarafından ayrıca kontrol edilecektir."
        )

    validity_text = supplier_quote.validity_date or "Belirtilmedi"
    weight_text = (
        f"{shipment.gross_weight_kg:g} kg"
        if shipment.gross_weight_kg is not None
        else "Belirtilmedi"
    )
    transit_text = supplier_quote.transit_time or "Belirtilmedi"
    indicative_note = (
        "\n\nİNDİKATİF / BAĞLAYICI DEĞİLDİR: Bu rakam bütçe çalışması içindir. "
        "Gerçek yükleme tarihinde güncel navlun ve araç uygunluğu yeniden teyit edilecektir."
        if indicative
        else ""
    )

    body = f"""
Merhaba,

Aşağıdaki taşıma talebinize istinaden {'indikatif fiyatımızı' if indicative else 'teklifimizi'} bilgilerinize sunarız.

Yükleme: {shipment.pickup_city or '-'}, {shipment.pickup_country or '-'}
Teslimat: {shipment.delivery_city or '-'}, {shipment.delivery_country or '-'}
Yük: {shipment.commodity or 'Standart genel yük varsayımı'}
Brüt Ağırlık: {weight_text}
Servis Tipi: {shipment.service_type}
Araç Tipi: {equipment_decision.selected_equipment}

Fiyat: {customer_quote.final_price} {customer_quote.currency}
Transit Süre: {transit_text}
Teklif Geçerliliği: {validity_text}

Saygılarımızla,
MINAI Freight OS
""".strip()

    body += indicative_note
    body += risk_note
    return QuoteDraft(subject=subject, body=body)
