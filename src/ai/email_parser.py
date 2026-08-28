import json
import re
from pathlib import Path
from typing import Optional
from openai import APIError, OpenAI
from src.core.normalization import normalize_shipment
from src.config import OPENAI_API_KEY, OPENAI_MODEL
from src.paths import data_path
from src.core.models import Shipment, Package
from src.core.gtip import interpret_gtip_from_email
from src.core.commodity_profile import apply_commodity_profile_to_shipment
from src.ai.extraction_models import (
    OpenAIShipmentExtraction,
    ShipmentExtraction,
)
from src.ai.extraction_mapping import shipment_from_extraction
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.privacy import PrivacyBoundaryError, PrivacySafeText


OPENAI_REQUEST_TIMEOUT_SECONDS = 30.0
OPENAI_MAX_RETRIES = 1


class EmailParserUnavailableError(RuntimeError):
    pass


def _build_openai_client() -> OpenAI:
    return OpenAI(
        api_key=OPENAI_API_KEY,
        timeout=OPENAI_REQUEST_TIMEOUT_SECONDS,
        max_retries=OPENAI_MAX_RETRIES,
    )


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


COMMODITY_DICTIONARY_PATH = data_path("commodity_dictionary.json")


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
            r"\badr\s*[:=\-]\s*(?:no|hayır|hayir|false|yok)\b",
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

    if adr_negated and adr_class_match:
        # Conflicting explicit safety signals must remain unresolved.
        return None, None
    if adr_negated:
        return False, None
    if adr_class_match:
        return True, adr_class_match.group(1)
    if adr_mentioned:
        return True, None
    return None, None


def _explicit_temperature_control_state(email_text: str) -> bool | None:
    text = (email_text or "").lower()
    negative = any(re.search(pattern, text) for pattern in [
        r"\btemperature\s+control\s*[:=\-]?\s*(?:not\s+required|no|false)\b",
        r"\btemperature[-\s]?controlled\s*[:=\-]?\s*(?:no|false)\b",
        r"\breefer\s*[:=\-]?\s*(?:not\s+required|no|false)\b",
        r"\bsıcaklık\s+kontrollü\s+(?:değil|degil)\b",
        r"\b(?:ısı|isı)\s+kontrollü\s+(?:değil|degil|değildir|degildir)\b",
        r"\bisi\s+kontrollu\s+(?:degil|degildir)\b",
        r"\b(?:ısı|isı)\s+kontrolü\s+(?:gerekmez|gerekmiyor|gerektirmez)\b",
        r"\bisi\s+kontrolu\s+(?:gerekmez|gerekmiyor|gerektirmez)\b",
    ])
    return False if negative else None


def _explicit_stackable_state(email_text: str) -> bool | None:
    text = (email_text or "").lower()
    negative = any(re.search(pattern, text) for pattern in [
        r"\bnon[-\s]?stackable\b", r"\bnot\s+stackable\b",
        r"\bstackable\s*[:=\-]\s*(?:no|false)\b", r"\bistiflenemez\b",
    ])
    if negative:
        return False

    positive = any(re.search(pattern, text) for pattern in [
        r"\bstackable\s*[:=\-]\s*(?:yes|true)\b", r"\bistiflenebilir\b",
    ])
    return True if positive else None


def _source_has_explicit_per_piece_weight(email_text: str) -> bool:
    text = (email_text or "").lower()
    patterns = [
        r"\b\d+(?:[.,]\d+)?\s*kg\s*(?:/|per\s+)(?:pallet|piece|package|box|crate|palet|koli|adet|parça)\b",
        r"\b(?:per|her)\s+(?:pallet|piece|package|box|crate|palet|koli|adet|parça|biri)\b[^.\n;]{0,40}\b\d+(?:[.,]\d+)?\s*kg\b",
        r"\b(?:pallet|piece|package|box|crate|palet|koli|adet|parça)\s+başına\b[^.\n;]{0,20}\b\d+(?:[.,]\d+)?\s*kg\b",
        r"\beach\b[^.\n;]{0,40}\b\d+(?:[.,]\d+)?\s*kg\b",
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _apply_package_source_truth_overrides(shipment, email_text: str):
    stackable_state = _explicit_stackable_state(email_text)
    explicit_per_piece_weight = _source_has_explicit_per_piece_weight(email_text)
    single_package_line = len(shipment.packages) == 1

    for package in shipment.packages:
        package.stackable = stackable_state

        safe_single_piece_total = single_package_line and package.quantity == 1
        safe_explicit_per_piece = single_package_line and explicit_per_piece_weight

        if package.weight_kg is not None and not (
            safe_single_piece_total or safe_explicit_per_piece
        ):
            package.weight_kg = None

    return shipment

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

    temperature_state = _explicit_temperature_control_state(email_text)
    if temperature_state is False:
        shipment.is_temperature_controlled = False
        shipment.temperature_requirement = None

    shipment = _apply_package_source_truth_overrides(shipment, email_text)
    shipment = _apply_commodity_safety_overrides(shipment, email_text)
    shipment = _apply_gtip_safety_overrides(shipment, email_text)
    shipment = apply_commodity_profile_to_shipment(shipment)

    return shipment


def _has_directional_quote_signal(email_text: str, direction: str) -> bool:
    text = (email_text or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    if direction == "export":
        direction_terms = ("ihracat", "export")
    elif direction == "import":
        direction_terms = ("ithalat", "import")
    else:
        raise ValueError(f"Unsupported trade direction: {direction}")

    request_terms = (
        "teklif", "fiyat", "navlun", "taşıma", "tasima", "yük", "yuk",
        "quote", "rate", "freight", "shipment", "load",
    )
    direction_group = "(?:" + "|".join(direction_terms) + ")"
    request_group = "(?:" + "|".join(request_terms) + ")"
    patterns = (
        rf"\b{direction_group}\b[^\n.;]{{0,60}}\b{request_group}\b",
        rf"\b{request_group}\b[^\n.;]{{0,60}}\b{direction_group}\b",
    )
    return any(re.search(pattern, text) for pattern in patterns)


def _is_turkiye_country(value: str | None) -> bool:
    normalized = (str(value or "").strip().lower().replace("ü", "u"))
    return normalized in {"turkiye", "turkey"}


def _apply_indicative_quote_inference(shipment, email_text: str):
    text = (email_text or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    if not re.search(r"(?<!\w)(?:indikatif|indicative)(?!\w)", text):
        return shipment

    shipment.quote_mode = "indicative"

    outbound = bool(re.search(
        r"(?<!\w)(?:gider|gidis|ihracat|export)(?!\w)", text
    ))
    inbound = bool(re.search(
        r"(?<!\w)(?:gelir|gelis|ithalat|import)(?!\w)", text
    ))
    if outbound != inbound:
        if outbound and not shipment.pickup_country:
            if not _is_turkiye_country(shipment.delivery_country):
                shipment.pickup_country = "Türkiye"
        elif inbound and not shipment.delivery_country:
            if not _is_turkiye_country(shipment.pickup_country):
                shipment.delivery_country = "Türkiye"

    return shipment


def _apply_trade_direction_country_inference(shipment, email_text: str):
    """Infer only the Turkish endpoint established by an explicit trade direction."""
    export_signal = _has_directional_quote_signal(email_text, "export")
    import_signal = _has_directional_quote_signal(email_text, "import")

    # Conflicting direction language (for example a company name containing both
    # "ithalat" and "ihracat") is not sufficient evidence for an endpoint default.
    if export_signal == import_signal:
        return shipment

    if export_signal and not shipment.pickup_country:
        if _is_turkiye_country(shipment.delivery_country):
            return shipment
        shipment.pickup_country = "Türkiye"

    if import_signal and not shipment.delivery_country:
        if _is_turkiye_country(shipment.pickup_country):
            return shipment
        shipment.delivery_country = "Türkiye"

    return shipment


def _apply_explicit_road_mode_inference(shipment, email_text: str):
    if shipment.transport_mode is not None:
        return shipment

    text = (email_text or "").replace("İ", "i").replace("I", "i").lower().replace("ı", "i")
    road_patterns = (
        r"(?<!\w)tenteli(?!\w)",
        r"(?<!\w)curtain\s*sider(?!\w)",
        r"(?<!\w)komple\s+araç(?!\w)",
        r"(?<!\w)karayolu(?!\w)",
        r"(?<!\w)road\s+(?:freight|transport)(?!\w)",
        r"(?<!\w)(?:tır|tir|kamyon|truck|dorse)(?!\w)",
        r"(?<!\w)(?:ftl|ltl|parsiyel)(?!\w)",
        r"(?<!\w)partial\s+(?:load|truckload)(?!\w)",
    )
    conflicting_mode_patterns = (
        r"(?<!\w)(?:denizyolu|deniz\s+yolu)(?!\w)",
        r"(?<!\w)(?:sea|ocean)\s+freight(?!\w)",
        r"(?<!\w)(?:havayolu|hava\s+yolu)(?!\w)",
        r"(?<!\w)air\s+freight(?!\w)",
        r"(?<!\w)(?:demiryolu|demir\s+yolu)(?!\w)",
        r"(?<!\w)rail\s+freight(?!\w)",
    )
    has_road = any(re.search(pattern, text) for pattern in road_patterns)
    has_conflict = any(
        re.search(pattern, text) for pattern in conflicting_mode_patterns
    )
    if has_road and not has_conflict:
        shipment.transport_mode = "road"

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

    shipment = _apply_explicit_road_mode_inference(shipment, email_text)
    shipment = _apply_indicative_quote_inference(shipment, email_text)
    shipment = _apply_trade_direction_country_inference(shipment, email_text)
    shipment = _apply_email_text_safety_overrides(shipment, email_text)
    shipment = normalize_shipment(shipment)

    explicit_adr, explicit_adr_class = _explicit_adr_state(email_text)
    proposed_adr = explicit_adr
    if proposed_adr is None and (
        extracted.is_adr is True or extracted.adr_class
    ):
        # AI may conservatively raise a safety flag, but it cannot establish
        # a negative safety fact when the source text did not establish one.
        proposed_adr = True

    explicit_temperature = _explicit_temperature_control_state(email_text)
    proposed_temperature = explicit_temperature
    if proposed_temperature is None and (
        extracted.is_temperature_controlled is True
        or shipment.is_temperature_controlled is True
    ):
        proposed_temperature = True

    proposed_high_value = (
        True
        if (
            extracted.is_high_value is True
            or shipment.is_high_value
        )
        else None
    )

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


def parse_email_with_ai(
    email_text: PrivacySafeText,
) -> ShipmentProposalSnapshot:
    """
    OpenAI structured email parser returning a non-authoritative proposal.

    Düzensiz müşteri mailinden Shipment objesi üretir.
    """

    if not isinstance(email_text, PrivacySafeText):
        raise PrivacyBoundaryError(
            "AI email parsing requires privacy-transformed input."
        )

    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY bulunamadı. Lütfen .env dosyasını kontrol edin.")

    client = _build_openai_client()

    try:
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
                    "Taşıma modu açıkça belirtilmediyse transport_mode alanını null bırak. "
                    "Özel ekipman sadece açıkça belirtilmişse çıkar. "
                    "ADR, reefer, yüksek değerli yük gibi riskli bilgileri asla varsayma. "
                    "Commodity-specific bilgiler mailde açıkça varsa "
                    "commodity_attributes alanında yalnızca schema'daki canonical key'leri "
                    "key/value nesneleri olarak kullan. "
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
            response_format=OpenAIShipmentExtraction,
        )
    except APIError as exc:
        raise EmailParserUnavailableError(
            "AI email parser is temporarily unavailable."
        ) from exc

    wire_extraction = response.choices[0].message.parsed

    if wire_extraction is None:
        raise EmailParserUnavailableError(
            "AI email parser returned no structured result."
        )

    extracted = wire_extraction.to_internal()

    return build_shipment_from_extraction(
        extracted,
        email_text,
    )
