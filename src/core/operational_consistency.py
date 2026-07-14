from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.supplier_capability_registry import (
    ADR_CAPABILITY,
    get_required_adr_class_capability,
)


SUPPLIER_CAPABILITY_PATH = Path("data/supplier_capabilities.json")


def _normalize(value: Optional[str]) -> str:
    if value is None:
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


def _get_attr(obj: Any, field_name: str, default: Any = None) -> Any:
    if obj is None:
        return default

    if isinstance(obj, dict):
        return obj.get(field_name, default)

    return getattr(obj, field_name, default)


def _get_selected_suppliers(
    supplier_selection: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    if not supplier_selection:
        return []

    selected = supplier_selection.get("selected_suppliers", [])

    if not isinstance(selected, list):
        return []

    return selected


def _get_first_selected_supplier_name(
    supplier_selection: Optional[Dict[str, Any]]
) -> Optional[str]:
    selected_suppliers = _get_selected_suppliers(supplier_selection)

    if not selected_suppliers:
        return None

    return selected_suppliers[0].get("supplier_name")


def _load_supplier_capabilities() -> List[Dict[str, Any]]:
    if not SUPPLIER_CAPABILITY_PATH.exists():
        return []

    try:
        raw_data = json.loads(SUPPLIER_CAPABILITY_PATH.read_text())
    except json.JSONDecodeError:
        return []

    if isinstance(raw_data, list):
        return [item for item in raw_data if isinstance(item, dict)]

    if isinstance(raw_data, dict):
        for key in ["suppliers", "supplier_capabilities", "data"]:
            value = raw_data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    return []


def _find_supplier_capability(
    supplier_name: Optional[str],
    capabilities: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    normalized_supplier_name = _normalize(supplier_name)

    if not normalized_supplier_name:
        return None

    for capability in capabilities:
        candidate_name = (
            capability.get("supplier_name")
            or capability.get("name")
            or capability.get("supplier")
        )

        if _normalize(candidate_name) == normalized_supplier_name:
            return capability

    return None


def _get_special_capabilities(
    supplier_capability: Optional[Dict[str, Any]]
) -> List[str]:
    if not supplier_capability:
        return []

    raw_capabilities = supplier_capability.get("special_capabilities") or []

    if not isinstance(raw_capabilities, list):
        return []

    return [_normalize(item) for item in raw_capabilities]


def _get_service_types(supplier_capability: Optional[Dict[str, Any]]) -> List[str]:
    if not supplier_capability:
        return []

    raw_service_types = (
        supplier_capability.get("service_types")
        or supplier_capability.get("services")
        or []
    )

    if not isinstance(raw_service_types, list):
        return []

    return [_normalize(service_type) for service_type in raw_service_types]


def _supplier_supports_service(
    supplier_capability: Optional[Dict[str, Any]],
    service_type: str,
) -> bool:
    normalized_service_type = _normalize(service_type)
    service_types = _get_service_types(supplier_capability)

    return normalized_service_type in service_types


def check_operational_consistency(
    shipment: Any,
    equipment_decision: Any,
    risk_assessment: Any,
    supplier_selection: Optional[Dict[str, Any]],
    supplier_quote: Any = None,
) -> Dict[str, Any]:
    warnings: List[str] = []
    errors: List[str] = []

    selected_suppliers = _get_selected_suppliers(supplier_selection)
    selected_supplier_name = _get_first_selected_supplier_name(supplier_selection)
    quote_supplier_name = _get_attr(supplier_quote, "supplier_name")

    supplier_capabilities = _load_supplier_capabilities()
    selected_supplier_capability = _find_supplier_capability(
        selected_supplier_name,
        supplier_capabilities,
    )

    pickup_country = _normalize(_get_attr(shipment, "pickup_country"))
    delivery_country = _normalize(_get_attr(shipment, "delivery_country"))
    service_type = _normalize(_get_attr(shipment, "service_type"))
    adr_class = _normalize(_get_attr(shipment, "adr_class"))
    is_adr = bool(_get_attr(shipment, "is_adr", False))

    selected_equipment = _normalize(_get_attr(equipment_decision, "selected_equipment"))
    risk_level = _normalize(_get_attr(risk_assessment, "risk_level"))

    special_notes = str(_get_attr(shipment, "special_notes", "") or "")

    if "GTIP CONSISTENCY WARNING" in special_notes:
        warnings.append(
            "GTIP kodu ile ürün açıklaması uyumsuz görünüyor. Lütfen müşteri veya gümrük müşaviri ile doğrulayın."
        )

    if is_adr and not adr_class:
        errors.append(
            "ADR sınıfı eksik. ADR sınıfı netleşmeden fiyat ve ekipman kararı tamamlanmamalıdır."
        )

        if "adr" not in selected_equipment:
            errors.append(
                "ADR sınıfı belirsiz yük için ekipman kararı ADR review durumunda olmalıdır."
            )

    if adr_class and not is_adr:
        errors.append(
            f"ADR Class {adr_class} mevcut ancak shipment is_adr=false."
        )

    if supplier_quote and not selected_suppliers:
        warnings.append(
            "Supplier Quote üretildi ancak Supplier Selection sonucu boş."
        )

    if selected_supplier_name and quote_supplier_name:
        if selected_supplier_name != quote_supplier_name:
            errors.append(
                "Supplier Selection ile Supplier Quote farklı supplier kullanıyor: "
                f"{selected_supplier_name} != {quote_supplier_name}"
            )

    if pickup_country in ["turkiye", "turkey"] and delivery_country in ["turkiye", "turkey"]:
        if selected_supplier_name and "domestic" not in _normalize(selected_supplier_name):
            warnings.append(
                "Yurtiçi taşıma için domestic supplier seçilmemiş görünüyor."
            )

    if is_adr and selected_supplier_name:
        supplier_special_capabilities = _get_special_capabilities(
            selected_supplier_capability
        )

        if selected_supplier_capability is None:
            errors.append(
                f"{selected_supplier_name} için capability datası bulunamadı; "
                "ADR yetkinliği doğrulanamadı."
            )
        elif ADR_CAPABILITY not in supplier_special_capabilities:
            errors.append(
                f"{selected_supplier_name} ADR yetkinliğine sahip görünmüyor."
            )
        else:
            required_class_capability = get_required_adr_class_capability(
                adr_class
            )

            if (
                required_class_capability
                and required_class_capability
                not in supplier_special_capabilities
            ):
                errors.append(
                    f"{selected_supplier_name} ADR Class {adr_class} "
                    "yetkinliğine sahip görünmüyor."
                )

    if is_adr and adr_class in ["1", "7"]:
        if risk_level != "red":
            errors.append(
                f"ADR Class {adr_class} için risk seviyesi red olmalıdır."
            )

        if "adr" not in selected_equipment:
            errors.append(
                f"ADR Class {adr_class} için Special ADR Equipment beklenir."
            )

    if "reefer" in selected_equipment:
        if selected_supplier_name and "coldchain" not in _normalize(selected_supplier_name):
            warnings.append(
                "Reefer taşıma için soğuk zincir uzmanı supplier seçilmemiş olabilir."
            )

    if service_type == "ltl":
        if not selected_supplier_name:
            warnings.append(
                "LTL / parsiyel taşıma için supplier seçimi bulunamadı."
            )
        elif selected_supplier_capability is None:
            warnings.append(
                f"{selected_supplier_name} için capability datası bulunamadı; "
                "LTL desteği doğrulanmalı."
            )
        elif not _supplier_supports_service(selected_supplier_capability, "LTL"):
            warnings.append(
                f"{selected_supplier_name} capability datasında LTL desteklemiyor görünüyor."
            )

    return {
        "passed": len(errors) == 0,
        "warnings": warnings,
        "errors": errors,
        "source": "operational_consistency_engine",
        "capability_data_source": str(SUPPLIER_CAPABILITY_PATH),
    }
