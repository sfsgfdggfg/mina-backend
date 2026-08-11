import json
import re
from pathlib import Path
from typing import Optional
from openai import OpenAI
from src.core.normalization import normalize_shipment
from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.core.models import Shipment, Package
from src.core.gtip import interpret_gtip_from_email
from src.core.commodity_profile import apply_commodity_profile_to_shipment
from src.ai.extraction_models import ShipmentExtraction
from src.ai.extraction_mapping import shipment_from_extraction
from src.core.extraction_confirmation import ShipmentProposalSnapshot

GENERIC_CUSTOMER_NAMES = {
    "",
    "-",
    "/",
    ".",
    ",",
    "unknown",
    "unknown customer",
    "none",
    "null",
    "müşteri",
    "firma",
    "şirket",
    "customer",
    "company",
    "client",
    "sender",
    "gönderen",
    "Test",
}


def clean_customer_name(customer_name: str | None, email_text: str) -> str:
    """
    AI parser bazen müşteri adı yokken generic/hayali değer döndürebilir.
    Bu fonksiyon müşteri adını deterministik olarak güvenli hale getirir.

    Kural:
    - Boş/generic değerler Unknown Customer olur.
    - Customer name email içinde açıkça geçmiyorsa ve çok genel görünüyorsa Unknown Customer olur.
    """

    if not customer_name:
        return "Unknown Customer"

    cleaned = customer_name.strip()

    if cleaned.lower() in GENERIC_CUSTOMER_NAMES:
        return "Unknown Customer"

    # Çok kısa ve anlamsız değerleri müşteri adı sayma
    if len(cleaned) <= 2:
        return "Unknown Customer"

    return cleaned

def parse_email_to_shipment(email_text: str) -> Shipment:
    """
    Mock parser.

    Scenario testleri için kalıyor.
    Gerçek AI parsing için parse_email_with_ai kullanılacak.
    """

    shipment = Shipment(
        customer_name="Demo Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        pickup_area="Adana Organize Sanayi Bölgesi",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        weight_is_approximate=True,
        service_type="FTL",
        cargo_ready_date="2026-06-15",
        packages=[
            Package(
                package_type="loose / textile",
                quantity=1,
                weight_kg=20000,
                stackable=None,
            )
        ],
        special_notes="Müşteri komple araç fiyat istemiştir.",
    )

    return shipment


COMMODITY_DICTIONARY_PATH = Path("data/commodity_dictionary.json")


def _load_commodity_dictionary() -> list[dict]:
    if not COMMODITY_DICTIONARY_PATH.exists():
        return []

    try:
        raw_data = json.loads(COMMODITY_DICTIONARY_PATH.read_text())
    except json.JSONDecodeError:
        return []

    if not isinstance(raw_data, list):
        return []

    return [item for item in raw_data if isinstance(item, dict)]


def _keyword_matches(text: str, keyword: str) -> bool:
    if not keyword:
        return False

    pattern = r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _apply_commodity_safety_overrides(shipment, email_text: str):
    """
    Raw email text can contain clear commodity signals.
    Keyword to canonical commodity mapping is loaded from
    data/commodity_dictionary.json instead of being hard-coded in Python.
    """

    text = (email_text or "").lower()
    commodity_dictionary = _load_commodity_dictionary()

    for item in commodity_dictionary:
        canonical_commodity = item.get("canonical_commodity")
        keywords = item.get("keywords", [])

        if not canonical_commodity or not isinstance(keywords, list):
            continue

        for keyword in keywords:
            if _keyword_matches(text, str(keyword)):
                shipment.commodity = canonical_commodity
                return shipment

    return shipment


GTIP_COMPATIBLE_COMMODITIES = {
    "İçecek / Meşrubat": ["İçecek / Meşrubat", "Gıda"],
    "Elektrik Transformatörü": [
        "Elektrik Transformatörü",
        "Elektrikli Makine / Ekipman",
        "Makine",
    ],
    "Elektrikli Makine / Ekipman": [
        "Elektrikli Makine / Ekipman",
        "Elektrik Transformatörü",
        "Makine",
    ],
    "Tekstil / Hazır Giyim": ["Tekstil / Hazır Giyim", "Tekstil"],
    "Makine": ["Makine", "Elektrikli Makine / Ekipman"],
}


def _normalize_commodity_text(value: str | None) -> str:
    if not value:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ç", "c")
        .replace("Ç", "c")
    )


def _append_special_note(shipment, note: str):
    if not note:
        return shipment

    existing_notes = getattr(shipment, "special_notes", None)

    null_like_notes = {
        "",
        "none",
        "null",
        "/null/",
        "n/a",
        "na",
        "-",
    }

    if isinstance(existing_notes, str) and existing_notes.strip().lower() in null_like_notes:
        existing_notes = None

    if existing_notes:
        if note not in existing_notes:
            shipment.special_notes = existing_notes + "\n" + note
    else:
        shipment.special_notes = note

    return shipment
def _is_gtip_commodity_conflict(email_commodity: str | None, gtip_commodity: str | None) -> bool:
    if not email_commodity or not gtip_commodity:
        return False

    normalized_email_commodity = _normalize_commodity_text(email_commodity)
    normalized_gtip_commodity = _normalize_commodity_text(gtip_commodity)

    if normalized_email_commodity == normalized_gtip_commodity:
        return False

    compatible_values = GTIP_COMPATIBLE_COMMODITIES.get(gtip_commodity, [])
    normalized_compatible_values = {
        _normalize_commodity_text(value)
        for value in compatible_values
    }

    if normalized_email_commodity in normalized_compatible_values:
        return False

    generic_values = {
        "",
        "urun",
        "yuk",
        "cargo",
        "goods",
        "gida",
        "makine",
        "unknown",
        "unknown commodity",
    }

    if normalized_email_commodity in generic_values:
        return False

    return True


def _apply_gtip_safety_overrides(shipment, email_text: str):
    """
    If the customer explicitly provides a GTIP / HS code, interpret it for
    operational commodity classification.

    MINAI does not assign legally binding GTIP codes. It only interprets
    customer-provided codes for freight operations.
    """

    gtip_info = interpret_gtip_from_email(email_text)

    shipment.gtip_code = gtip_info.get("gtip_code")
    shipment.hs_chapter = gtip_info.get("hs_chapter")
    shipment.hs_heading = gtip_info.get("hs_heading")
    shipment.hs_subheading = gtip_info.get("hs_subheading")
    shipment.gtip_detected_from_email = bool(gtip_info.get("gtip_detected_from_email"))

    commodity_match = gtip_info.get("commodity_match")

    if commodity_match:
        commodity_group = commodity_match.get("commodity_group")

        if commodity_group:
            email_commodity_before_gtip = shipment.commodity

            if _is_gtip_commodity_conflict(email_commodity_before_gtip, commodity_group):
                warning = (
                    "[GTIP CONSISTENCY WARNING] GTIP kodu ile ürün açıklaması "
                    "uyumsuz görünüyor. "
                    f"Email commodity: {email_commodity_before_gtip}; "
                    f"GTIP commodity: {commodity_group}."
                )
                shipment = _append_special_note(shipment, warning)
            else:
                shipment.commodity = commodity_group

        notes = commodity_match.get("notes") or []
        if notes:
            note_text = "[GTIP] " + " ".join(str(note) for note in notes)
            shipment = _append_special_note(shipment, note_text)

    return shipment


def _explicit_adr_state(email_text: str) -> tuple[bool | None, str | None]:
    text = (email_text or "").lower()
    adr_negated = any(
        re.search(pattern, text)
        for pattern in [
            r"\bnon[\s-]?adr\b",
            r"\badr\s+(?:değil|degil|değildir|degildir|yok)\b",
            r"\badr\s+kapsam(?:ı|i)nda\s+(?:değil|degil|değildir|degildir)\b",
            r"\badr\s+kapsam(?:ı|i)\s+dış(?:ı|i)nda\b",
            r"\bnot\s+(?:subject\s+to\s+)?adr\b",
        ]
    )

    adr_mentioned = bool(re.search(r"\badr\b", text))
    adr_class_match = re.search(
        r"\badr\b\s*(?:class|sınıf(?:ı)?|sinif(?:i)?)"
        r"\s*[:\-]?\s*([1-9](?:\.[1-3])?)\b",
        text,
    )

    if adr_negated:
        return False, None
    if adr_class_match:
        return True, adr_class_match.group(1)
    if adr_mentioned:
        return True, None
    return None, None


def _apply_email_text_safety_overrides(shipment, email_text: str):
    """
    Critical logistics signals should not depend only on AI extraction.
    Explicit raw email ADR signals have final priority. Absence is unknown at
    the proposal boundary and must not overwrite an extracted positive fact.
    """

    adr_state, adr_class = _explicit_adr_state(email_text)

    if adr_state is False:
        shipment.is_adr = False
        shipment.adr_class = None
        shipment.commodity_attributes["adr status"] = False
    elif adr_state is True and adr_class:
        shipment.is_adr = True
        shipment.adr_class = adr_class
        shipment.commodity_attributes["adr status"] = True

        if not shipment.commodity:
            shipment.commodity = f"ADR Class {shipment.adr_class}"
    elif adr_state is True:
        shipment.is_adr = True
        shipment.adr_class = None
        shipment.commodity_attributes["adr status"] = True

    shipment = _apply_commodity_safety_overrides(shipment, email_text)
    shipment = _apply_gtip_safety_overrides(shipment, email_text)
    shipment = apply_commodity_profile_to_shipment(shipment)

    return shipment


def build_shipment_from_extraction(
    extracted: ShipmentExtraction,
    email_text: str,
) -> ShipmentProposalSnapshot:
    """Convert structured extraction into a non-authoritative proposal."""

    shipment = shipment_from_extraction(extracted)
    shipment.customer_name = clean_customer_name(
        customer_name=extracted.customer_name,
        email_text=email_text,
    )

    shipment = _apply_email_text_safety_overrides(shipment, email_text)
    shipment = normalize_shipment(shipment)

    explicit_adr, explicit_adr_class = _explicit_adr_state(email_text)
    proposed_adr = explicit_adr
    if proposed_adr is None:
        proposed_adr = extracted.is_adr
    if proposed_adr is None and extracted.adr_class:
        proposed_adr = True

    proposed_temperature = extracted.is_temperature_controlled
    if proposed_temperature is None and shipment.is_temperature_controlled:
        proposed_temperature = True

    proposed_high_value = extracted.is_high_value
    if proposed_high_value is None and shipment.is_high_value:
        proposed_high_value = True

    proposal_data = shipment.model_dump()
    proposal_data.update(
        {
            "is_adr": proposed_adr,
            "adr_class": (
                explicit_adr_class
                if explicit_adr_class is not None
                else shipment.adr_class
            ),
            "is_temperature_controlled": proposed_temperature,
            "is_high_value": proposed_high_value,
        }
    )
    return ShipmentProposalSnapshot.model_validate(proposal_data)


def parse_email_with_ai(email_text: str) -> ShipmentProposalSnapshot:
    """
    OpenAI structured email parser returning a non-authoritative proposal.

    Düzensiz müşteri mailinden Shipment objesi üretir.
    """

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY bulunamadı. Lütfen .env dosyasını kontrol edin.")

    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.beta.chat.completions.parse(
        model=OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Sen uluslararası karayolu lojistiği ve freight forwarding operasyonlarında uzman bir asistansın. "
                    "Görevin müşteri emailinden shipment bilgilerini çıkarmaktır. "
                    "Bilgi mailde yoksa uydurma. "
                    "Müşteri parsiyel istemedikçe service_type değerini FTL kabul et. "
                    "Özel ekipman sadece açıkça belirtilmişse çıkar. "
                    "ADR, reefer, yüksek değerli yük gibi riskli bilgileri asla varsayma. "
                    "Commodity-specific bilgiler mailde açıkça varsa "
                    "commodity_attributes alanında yalnızca schema'daki canonical key'leri kullan. "
                    "Açık false / hayır cevabını false olarak sakla; eksik bilgi için key oluşturma. "
                    "Tarihleri mümkünse YYYY-MM-DD formatına çevir. Emin değilsen null bırak."
                    "Ülke ve ürün adlarını mümkünse Türkçe canonical değerlerle çıkar: Türkiye, Almanya, Makine, Tekstil, Gıda gibi."
                ),
            },
            {
                "role": "user",
                "content": email_text,
            },
        ],
        response_format=ShipmentExtraction,
    )

    extracted = response.choices[0].message.parsed
    return build_shipment_from_extraction(extracted, email_text)
