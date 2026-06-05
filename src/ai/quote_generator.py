from src.core.models import Shipment, EquipmentDecision, RiskAssessment, SupplierQuote, CustomerQuote, QuoteDraft


def generate_quote_draft(
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    risk_assessment: RiskAssessment,
    supplier_quote: SupplierQuote,
    customer_quote: CustomerQuote,
) -> QuoteDraft:
    """
    Quote Draft Generator v1.

    Şimdilik template-based.
    İleride OpenAI ile müşteri stiline göre kişiselleştirilecek.
    """

    subject = "Taşıma Teklifimiz Hakkında"

    risk_note = ""
    if risk_assessment.risk_level != "green":
        risk_note = (
            "\n\nNot: Bu taşıma talebinde operasyonel dikkat gerektiren noktalar bulunmaktadır. "
            "Detaylar operasyon ekibimiz tarafından ayrıca kontrol edilecektir."
        )

    body = f"""
Merhaba,

Aşağıdaki taşıma talebinize istinaden teklifimizi bilgilerinize sunarız.

Yükleme: {shipment.pickup_city}, {shipment.pickup_country}
Teslimat: {shipment.delivery_city}, {shipment.delivery_country}
Yük: {shipment.commodity}
Brüt Ağırlık: {shipment.gross_weight_kg} kg
Servis Tipi: {shipment.service_type}
Araç Tipi: {equipment_decision.selected_equipment}

Fiyat: {customer_quote.final_price} {customer_quote.currency}
Transit Süre: {supplier_quote.transit_time}
Teklif Geçerliliği: Güncel araç durumuna bağlıdır.

Saygılarımızla,
MINAI Freight OS
""".strip()

    body += risk_note

    return QuoteDraft(
        subject=subject,
        body=body,
    )