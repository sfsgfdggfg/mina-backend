from src.core.models import Shipment, EquipmentDecision, RiskAssessment, SupplierQuote, CustomerQuote, QuoteDraft


def _location_text(city: str | None, country: str | None) -> str:
    parts = [part.strip() for part in (city, country) if isinstance(part, str) and part.strip()]
    return ", ".join(parts) or "Belirtilmedi"


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

    weight_text = (
        f"{shipment.gross_weight_kg:g} kg"
        if shipment.gross_weight_kg is not None
        else "Belirtilmedi"
    )
    indicative_note = (
        "\n\nİNDİKATİF / BAĞLAYICI DEĞİLDİR: Bu rakam bütçe çalışması içindir. "
        "Gerçek yükleme tarihinde güncel navlun ve araç uygunluğu yeniden teyit edilecektir."
        if indicative
        else ""
    )

    commercial_lines = [
        f"Fiyat: {customer_quote.final_price} {customer_quote.currency}"
    ]
    if supplier_quote.transit_time:
        commercial_lines.append(f"Transit Süre: {supplier_quote.transit_time}")
    if supplier_quote.validity_date:
        commercial_lines.append(f"Teklif Geçerliliği: {supplier_quote.validity_date}")
    commercial_text = "\n".join(commercial_lines)

    body = f"""
Merhaba,

Aşağıdaki taşıma talebinize istinaden {'indikatif fiyatımızı' if indicative else 'teklifimizi'} bilgilerinize sunarız.

Yükleme: {_location_text(shipment.pickup_city, shipment.pickup_country)}
Teslimat: {_location_text(shipment.delivery_city, shipment.delivery_country)}
Yük: {shipment.commodity or 'Standart genel yük varsayımı'}
Brüt Ağırlık: {weight_text}
Servis Tipi: {shipment.service_type}
Araç Tipi: {equipment_decision.selected_equipment}

{commercial_text}

Saygılarımızla,
MINAI Freight OS
""".strip()

    body += indicative_note
    body += risk_note
    return QuoteDraft(subject=subject, body=body)
