from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.supplier_capability_registry import (
    ADR_CAPABILITY,
    get_required_adr_class_capability,
)


def _get_primary_contact_email(raw_supplier: Dict[str, Any]) -> Optional[str]:
    contacts = raw_supplier.get("contacts") or []

    if not isinstance(contacts, list):
        return None

    active_contacts = [
        contact
        for contact in contacts
        if isinstance(contact, dict)
        and contact.get("active", True)
        and contact.get("email")
    ]

    for contact in active_contacts:
        if contact.get("is_primary", False):
            return str(contact["email"]).strip()

    if active_contacts:
        return str(active_contacts[0]["email"]).strip()

    return None


def _normalize(value: Optional[str]) -> str:
    if value is None:
        return ""

    value = str(value).strip().lower()
    value = value.replace("ı", "i").replace("İ", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value


SUPPLIER_CAPABILITIES_PATH = Path(__file__).resolve().parents[2] / "data" / "supplier_capabilities.json"


def _load_supplier_profiles(path: Path = SUPPLIER_CAPABILITIES_PATH) -> List[Dict[str, Any]]:
    if not path.exists():
        return []

    raw_suppliers = json.loads(path.read_text(encoding="utf-8"))

    profiles: List[Dict[str, Any]] = []

    for raw in raw_suppliers:
        if not raw.get("active", True):
            continue

        profiles.append(
            {
                "supplier_name": raw["supplier_name"],
                "recipient_email": _get_primary_contact_email(raw),
                "active": raw.get("active", True),
                "role": raw.get("role", "backup"),
                "supported_countries": [
                    _normalize(country)
                    for country in raw.get("countries", [])
                ],
                "supported_equipment": raw.get("equipment_types", []),
                "supported_service_types": raw.get("service_types", []),
                "special_capabilities": raw.get("special_capabilities", []),
                "route_regions": [
                    _normalize(region)
                    for region in raw.get("route_regions", [])
                ],
                "priority_routes": raw.get("priority_routes", []),
                "reliability_score": raw.get("reliability_score", 0.70),
                "price_score": raw.get("price_score", 0.70),
                "speed_score": raw.get("speed_score", 0.70),
                "notes": raw.get("notes", ""),
            }
        )

    return profiles


SUPPLIER_PROFILES: List[Dict[str, Any]] = _load_supplier_profiles()


def _get_equipment_text(shipment: Any, equipment_decision: Optional[Any]) -> str:
    if equipment_decision:
        if isinstance(equipment_decision, dict):
            selected = equipment_decision.get("selected_equipment")
        else:
            selected = getattr(equipment_decision, "selected_equipment", None)

        if selected:
            return _normalize(selected)

    equipment_type = getattr(shipment, "equipment_type", None)
    return _normalize(equipment_type)


def _get_risk_level(risk_assessment: Optional[Any]) -> str:
    if not risk_assessment:
        return "green"

    if isinstance(risk_assessment, dict):
        return _normalize(risk_assessment.get("risk_level", "green"))

    return _normalize(getattr(risk_assessment, "risk_level", "green"))


def _score_route(supplier: Dict[str, Any], shipment: Any) -> float:
    delivery_country = _normalize(getattr(shipment, "delivery_country", None))
    pickup_country = _normalize(getattr(shipment, "pickup_country", None))

    if not pickup_country or not delivery_country:
        return 0.0

    supported_countries = supplier["supported_countries"]
    route_regions = set(supplier.get("route_regions", []))
    priority_routes = {
        tuple(
            _normalize(route_part)
            for route_part in str(route).split("-", maxsplit=1)
        )
        for route in supplier.get("priority_routes", [])
        if "-" in str(route)
    }
    requested_route = (pickup_country, delivery_country)
    is_domestic = pickup_country == delivery_country
    is_domestic_only = route_regions == {"domestic"}

    if requested_route in priority_routes:
        return 1.0

    if is_domestic:
        if (
            "domestic" in route_regions
            and delivery_country in supported_countries
        ):
            return 0.95
        return 0.0

    if is_domestic_only:
        return 0.0

    if (
        pickup_country in supported_countries
        and delivery_country in supported_countries
    ):
        return 0.95

    if (
        delivery_country in supported_countries
        and any(region != "domestic" for region in route_regions)
    ):
        return 0.85

    return 0.0


def _supports_service(supplier: Dict[str, Any], service_type: str) -> bool:
    supported_services = [
        _normalize(item)
        for item in supplier["supported_service_types"]
    ]
    return _normalize(service_type) in supported_services


def _score_equipment(supplier: Dict[str, Any], equipment_text: str) -> float:
    supported_equipment = [_normalize(item) for item in supplier["supported_equipment"]]

    if not equipment_text:
        return 0.65

    if any(
        item in equipment_text or equipment_text in item
        for item in supported_equipment
    ):
        return 1.0

    return 0.0


def _score_risk_fit(supplier: Dict[str, Any], risk_level: str, equipment_text: str) -> float:
    reliability = supplier["reliability_score"]
    supplier_equipment = " ".join(supplier["supported_equipment"])
    supplier_equipment = _normalize(supplier_equipment)

    if risk_level == "red":
        if "adr" in equipment_text and "adr" in supplier_equipment:
            return 1.0
        if "lowbed" in equipment_text and "lowbed" in supplier_equipment:
            return 0.95
        return reliability

    if risk_level == "yellow":
        return (reliability * 0.85) + 0.15

    return 0.75


def _build_reason(
    supplier: Dict[str, Any],
    route_score: float,
    equipment_score: float,
    risk_score: float,
    service_type: str,
) -> str:
    reasons = []

    if route_score >= 1:
        reasons.append("güzergah uygun")
    elif route_score > 0:
        reasons.append("güzergah kısmen uygun")

    if equipment_score >= 0.9:
        reasons.append("ekipman / servis tipi uygun")

    if risk_score >= 0.9:
        reasons.append("risk profiline uygun ve güven skoru yüksek")

    reasons.append(supplier["notes"])

    return "; ".join(reasons)


def select_suppliers_for_shipment(
    shipment: Any,
    equipment_decision: Optional[Dict[str, Any]] = None,
    risk_assessment: Optional[Dict[str, Any]] = None,
    max_suppliers: int = 3,
) -> Dict[str, Any]:
    equipment_text = _get_equipment_text(shipment, equipment_decision)
    risk_level = _get_risk_level(risk_assessment)
    service_type = getattr(shipment, "service_type", "FTL") or "FTL"
    is_adr = bool(getattr(shipment, "is_adr", False))
    adr_class = _normalize(getattr(shipment, "adr_class", None))

    scored_suppliers = []
    rejected_suppliers = []

    for supplier in SUPPLIER_PROFILES:
        supplier_capabilities = [
            _normalize(item)
            for item in supplier.get("special_capabilities", [])
        ]

        if is_adr and ADR_CAPABILITY not in supplier_capabilities:
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": "ADR yetkinliği bulunmadığı için elendi.",
                }
            )
            continue

        required_class_capability = get_required_adr_class_capability(adr_class)

        if (
            is_adr
            and required_class_capability
            and required_class_capability not in supplier_capabilities
        ):
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": (
                        f"ADR Class {adr_class} yetkinliği bulunmadığı için elendi."
                    ),
                }
            )
            continue

        if not _supports_service(supplier, service_type):
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": (
                        f"{service_type} servis tipi desteklenmediği için elendi."
                    ),
                }
            )
            continue

        route_score = _score_route(supplier, shipment)
        equipment_score = _score_equipment(supplier, equipment_text)
        risk_score = _score_risk_fit(supplier, risk_level, equipment_text)

        if route_score <= 0:
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": (
                        "Talep edilen origin-destination güzergahı capability "
                        "datası tarafından desteklenmediği için elendi."
                    ),
                }
            )
            continue

        if equipment_score <= 0:
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": (
                        f"Zorunlu ekipman '{equipment_text}' capability "
                        "datasında desteklenmediği için elendi."
                    ),
                }
            )
            continue

        total_score = (
            route_score * 0.35
            + equipment_score * 0.25
            + risk_score * 0.25
            + supplier["price_score"] * 0.10
            + supplier["speed_score"] * 0.05
        )

        scored_suppliers.append(
            {
                "supplier_name": supplier["supplier_name"],
                "recipient_email": supplier.get("recipient_email"),
                "priority": 0,
                "total_score": round(total_score, 3),
                "route_score": round(route_score, 3),
                "equipment_score": round(equipment_score, 3),
                "risk_score": round(risk_score, 3),
                "price_score": supplier["price_score"],
                "speed_score": supplier["speed_score"],
                "reason": _build_reason(
                    supplier=supplier,
                    route_score=route_score,
                    equipment_score=equipment_score,
                    risk_score=risk_score,
                    service_type=service_type,
                ),
            }
        )

    scored_suppliers.sort(key=lambda item: item["total_score"], reverse=True)

    selected = scored_suppliers[:max_suppliers]

    for index, supplier in enumerate(selected, start=1):
        supplier["priority"] = index

    return {
        "selected_suppliers": selected,
        "rejected_suppliers": rejected_suppliers,
        "selection_strategy": (
            "strict route + service + equipment eligibility, then risk + "
            "price + speed weighted scoring"
        ),
        "source": "supplier_selection_engine",
        "data_source": "data/supplier_capabilities.json",
    }
