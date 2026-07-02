from src.core.models import Shipment, QuoteDraft
from src.core.missing_info import MissingInfoResult


def generate_clarification_draft(
    shipment: Shipment,
    missing_info: MissingInfoResult,
) -> QuoteDraft:
    """
    Clarification Email Generator v1.

    Kritik eksik bilgi varsa müşteriye gönderilecek bilgi talep maili taslağını üretir.
    Şimdilik template-based çalışır.
    İleride OpenAI ile müşteri stiline göre kişiselleştirilecek.
    """

    subject = "Taşıma Talebiniz Hakkında Eksik Bilgiler"

    translated_missing_fields = [
        translate_missing_field(field)
        for field in missing_info.missing_fields
    ]

    missing_fields_text = "\n".join(
        f"- {field}" for field in translated_missing_fields
    )

    route_text = build_route_text(shipment)

    body = f"""
Merhaba,

Taşıma talebiniz için teklif çalışmamızı başlatabilmemiz adına aşağıdaki bilgileri paylaşabilir misiniz?

{route_text}

Eksik bilgiler:
{missing_fields_text}

Bilgilerinizi aldıktan sonra teklifimizi en kısa sürede paylaşacağız.

Teşekkür ederiz.

Saygılarımızla,
MINAI Freight OS
""".strip()

    return QuoteDraft(
        subject=subject,
        body=body,
    )


def translate_missing_field(field: str) -> str:
    """
    Internal missing field code -> customer friendly Turkish text
    """

    mapping = {
        "pickup location": "Yükleme adresi / yükleme bölgesi",
        "delivery location": "Teslimat adresi / teslimat bölgesi",
        "commodity": "Ürün cinsi",
        "cargo ready date": "Yük hazır tarihi",
        "machine dimensions": "Makine ölçüleri (en / boy / yükseklik)",
        "msds/sds document": "MSDS/SDS belgesi",
        "adr status": "Yükün ADR kapsamında olup olmadığı",
        "chemical packaging type": "Kimyasal ürünün ambalaj tipi ve ambalaj uygunluğu",
        "frozen temperature requirement": "Dondurulmuş ürün için gerekli sıcaklık derecesi",
        "reefer confirmation": "Reefer araç gereksiniminin teyidi",
        "cold chain sensitivity": "Ürünün soğuk zincir hassasiyeti",
        "pharma temperature requirement": "İlaç / pharma yükü için sıcaklık gereksinimi",
        "pharma compliance document": "İlaç / pharma uygunluk veya ruhsat belgeleri",
        "pharma special transport requirements": "İlaç / pharma özel taşıma şartları",
        "medical product type": "Medikal ürün tipi ve kullanım amacı",
        "medical compliance document": "Medikal ürün uygunluk / belge gereklilikleri",
        "medical temperature sensitivity": "Medikal ürünün sıcaklık hassasiyeti olup olmadığı",
        "fragile packaging type": "Kırılabilir ürün ambalaj tipi",
        "fragile stackability": "Ürünün istiflenebilir olup olmadığı",
        "fragile lashing requirement": "Sabitleme / lashing gerekip gerekmediği",
        "electronic cargo value": "Elektronik ürün yaklaşık değeri",
        "electronic packaging sensitivity": "Elektronik ürün ambalajı ve darbe hassasiyeti",
        "secure transport requirement": "Güvenli taşıma / kapalı kasa ihtiyacı",
    }

    return mapping.get(field, field)


def build_route_text(shipment: Shipment) -> str:
    pickup = ", ".join(
        part for part in [
            shipment.pickup_area,
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
        return f"Anladığımız taşıma güzergahı: {pickup} → {delivery}"

    return "Taşıma güzergahı bilgisi henüz net değildir."