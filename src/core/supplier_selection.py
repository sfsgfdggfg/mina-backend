from __future__ import annotations

import unicodedata
from typing import Any, Dict, List, Optional


SUPPLIER_PROFILES: List[Dict[str, Any]] = [
    {
        "supplier_name": "Anatolia Road",
        "supported_countries": ["almanya", "avusturya", "belcika", "hollanda", "fransa"],
        "supported_equipment": ["tenteli", "curtainsider", "mega", "box"],
        "supported_service_types": ["FTL"],
        "reliability_score": 0.90,
        "price_score": 0.76,
        "speed_score": 0.84,
        "notes": "Türkiye - Batı Avrupa hattında güçlü genel karayolu tedarikçisi.",
    },
    {
        "supplier_name": "EuroBridge Logistics",
        "supported_countries": ["almanya", "romanya", "fransa", "belcika", "hollanda"],
        "supported_equipment": ["tenteli", "curtainsider", "mega"],
        "supported_service_types": ["FTL", "LTL"],
        "reliability_score": 0.80,
        "price_score": 0.90,
        "speed_score": 0.78,
        "notes": "Fiyat rekabeti güçlü, Avrupa geneli alternatif tedarikçi.",
    },
    {
        "supplier_name": "Balkan Express",
        "supported_countries": ["romanya", "bulgaristan", "macaristan", "avusturya"],
        "supported_equipment": ["tenteli", "curtainsider", "mega", "lowbed"],
        "supported_service_types": ["FTL"],
        "reliability_score": 0.84,
        "price_score": 0.82,
        "speed_score": 0.80,
        "notes": "Balkan ve Doğu Avrupa hattında güçlü.",
    },
    {
        "supplier_name": "ColdChain Europe",
        "supported_countries": ["almanya", "avusturya", "belcika", "hollanda", "fransa"],
        "supported_equipment": ["reefer", "frigo", "coldchain"],
        "supported_service_types": ["FTL", "LTL"],
        "reliability_score": 0.88,
        "price_score": 0.70,
        "speed_score": 0.82,
        "notes": "Sıcaklık kontrollü taşımalarda uzman.",
    },
    {
        "supplier_name": "ADR Secure Logistics",
        "supported_countries": ["almanya", "avusturya", "romanya", "fransa", "belcika"],
        "supported_equipment": ["adr", "special adr equipment", "tenteli"],
        "supported_service_types": ["FTL"],
        "reliability_score": 0.93,
        "price_score": 0.62,
        "speed_score": 0.76,
        "notes": "ADR ve yüksek riskli yüklerde uzman tedarikçi.",
    },
    {
        "supplier_name": "Project Heavy Haul",
        "supported_countries": ["almanya", "avusturya", "romanya", "fransa", "belcika", "hollanda"],
        "supported_equipment": ["lowbed", "project", "heavy", "mega"],
        "supported_service_types": ["FTL"],
        "reliability_score": 0.91,
        "price_score": 0.58,
        "speed_score": 0.72,
        "notes": "Lowbed, ağır yük ve proje tipi taşımalarda uygun.",
    },
    {
        "supplier_name": "Local LTL Network",
        "supported_countries": ["almanya", "avusturya", "romanya", "fransa", "belcika", "hollanda", "turkiye"],
        "supported_equipment": ["ltl", "partial", "parsiyel", "tenteli", "curtainsider"],
        "supported_service_types": ["LTL"],
        "reliability_score": 0.78,
        "price_score": 0.88,
        "speed_score": 0.74,
        "notes": "Parsiyel / LTL talepler için demo network.",
    },
]


def _normalize(value: Optional[str]) -> str:
    if value is None:
        return ""

    value = str(value).strip().lower()
    value = value.replace("ı", "i").replace("İ", "i")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value


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

    supported = supplier["supported_countries"]

    if delivery_country in supported:
        return 1.0

    if pickup_country in supported:
        return 0.65

    return 0.0


def _score_equipment(supplier: Dict[str, Any], equipment_text: str, service_type: str) -> float:
    supported_equipment = [_normalize(item) for item in supplier["supported_equipment"]]
    supported_services = [_normalize(item) for item in supplier["supported_service_types"]]

    service_score = 1.0 if _normalize(service_type) in supported_services else 0.55

    if not equipment_text:
        equipment_score = 0.65
    elif any(item in equipment_text or equipment_text in item for item in supported_equipment):
        equipment_score = 1.0
    elif "ltl" in _normalize(service_type) and any(item in supported_equipment for item in ["ltl", "partial", "parsiyel"]):
        equipment_score = 1.0
    else:
        equipment_score = 0.0

    return equipment_score * service_score


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

    scored_suppliers = []
    rejected_suppliers = []

    for supplier in SUPPLIER_PROFILES:
        route_score = _score_route(supplier, shipment)
        equipment_score = _score_equipment(supplier, equipment_text, service_type)
        risk_score = _score_risk_fit(supplier, risk_level, equipment_text)

        if route_score <= 0 or equipment_score <= 0:
            rejected_suppliers.append(
                {
                    "supplier_name": supplier["supplier_name"],
                    "reason": "Güzergah veya ekipman uyumsuzluğu nedeniyle elendi.",
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
        "selection_strategy": "route + equipment + risk + price + speed weighted scoring",
        "source": "supplier_selection_engine",
    }
