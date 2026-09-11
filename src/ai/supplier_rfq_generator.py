from __future__ import annotations

from typing import Any, List
from uuid import uuid4

from src.core.models import EquipmentDecision, Shipment
from src.core.extraction_confirmation import (
    require_operational_shipment,
)
from src.core.missing_info import check_missing_information
from src.core.road_rfq_readiness import (
    apply_road_rfq_readiness,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierSelectionExplanation,
    build_supplier_rfq_reference,
)


def _location(
    *,
    area: str | None,
    city: str | None,
    postcode: str | None,
    country: str | None,
) -> str:
    return ", ".join(
        str(value)
        for value in (
            area,
            city,
            postcode,
            country,
        )
        if value
    )


def _external_special_notes(value: str | None) -> str | None:
    if not value:
        return None

    external_lines = [
        line.strip()
        for line in value.splitlines()
        if line.strip()
        and not line.strip().startswith("[COMMODITY PROFILE]")
    ]
    return "\n".join(external_lines) or None


def _package_summary(shipment: Shipment) -> str:
    parts: list[str] = []

    for package in shipment.packages:
        dimensions = (
            f"{package.length_cm:g} × "
            f"{package.width_cm:g} × "
            f"{package.height_cm:g} cm"
        )

        weight = (
            f", {package.weight_kg:g} kg/adet"
            if package.weight_kg is not None
            else ""
        )

        parts.append(
            f"{package.quantity} × {package.package_type}: "
            f"{dimensions}{weight}"
        )

    return "; ".join(parts)




def _selection_explanation(
    supplier: dict[str, Any], supplier_selection: dict[str, Any],
) -> SupplierSelectionExplanation | None:
    required = (
        "priority", "base_total_score", "total_score", "route_score",
        "equipment_score", "risk_score", "price_score", "speed_score",
    )
    if any(supplier.get(key) is None for key in required):
        return None
    return SupplierSelectionExplanation(
        selection_rank=int(supplier["priority"]),
        base_total_score=float(supplier["base_total_score"]),
        total_score=float(supplier["total_score"]),
        route_score=float(supplier["route_score"]),
        equipment_score=float(supplier["equipment_score"]),
        risk_score=float(supplier["risk_score"]),
        price_score=float(supplier["price_score"]),
        speed_score=float(supplier["speed_score"]),
        global_learning_adjustment=float(supplier.get("global_learning_adjustment") or 0),
        context_learning_adjustment=float(supplier.get("context_learning_adjustment") or 0),
        combined_learning_adjustment=float(supplier.get("learning_adjustment") or 0),
        learning_adjustment_capped=bool(supplier.get("learning_adjustment_capped")),
        learning_context_key=supplier.get("learning_context_key"),
        global_learning_fact_ids=list(supplier.get("global_learning_fact_ids") or []),
        context_learning_fact_ids=list(supplier.get("context_learning_fact_ids") or []),
        selection_strategy=supplier_selection.get("selection_strategy"),
        data_source=supplier_selection.get("data_source"),
        reason=str(supplier.get("reason") or "Eligibility ve ağırlıklı supplier skoru ile seçildi."),
    )

def generate_supplier_rfq_drafts(
    *,
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    supplier_selection: dict[str, Any],
    workflow_id: str | None = None,
) -> List[SupplierRFQDraft]:
    require_operational_shipment(shipment)

    readiness = apply_road_rfq_readiness(
        shipment,
        check_missing_information(shipment),
    )

    if (
        shipment.transport_mode == "road"
        and not readiness.can_continue_to_quote
    ):
        raise ValueError(
            "Road Supplier RFQ cannot be generated with "
            "incomplete commercial shipment facts."
        )

    drafts: List[SupplierRFQDraft] = []
    resolved_workflow_id = workflow_id or str(uuid4())

    selected_suppliers = supplier_selection.get(
        "selected_suppliers",
        [],
    )[:3]

    pickup = _location(
        area=shipment.pickup_area,
        city=shipment.pickup_city,
        postcode=shipment.pickup_postcode,
        country=shipment.pickup_country,
    )

    delivery = _location(
        area=shipment.delivery_area,
        city=shipment.delivery_city,
        postcode=shipment.delivery_postcode,
        country=shipment.delivery_country,
    )

    packages = _package_summary(shipment)

    for supplier in selected_suppliers:
        supplier_name = (
            supplier.get("supplier_name")
            or "Tedarikçi"
        )
        recipient_email = supplier.get("recipient_email")
        priority = int(supplier.get("priority") or 0)
        rfq_id = str(uuid4())
        rfq_reference = build_supplier_rfq_reference(rfq_id)

        subject = (
            f"[{rfq_reference}] Navlun Talebi | "
            f"{pickup} - {delivery}"
        )
        required_delivery_text = (
            shipment.required_delivery_date
            or "Belirtilmedi"
        )
        external_special_notes = _external_special_notes(
            shipment.special_notes
        )
        special_notes_line = (
            f"Özel Notlar: {external_special_notes}\n"
            if external_special_notes
            else ""
        )

        if getattr(shipment, "quote_mode", "firm") == "indicative":
            package_text = packages or "Belirtilmedi - standart FTL varsayımı"
            weight_text = (
                f"{shipment.gross_weight_kg:g} kg"
                if shipment.gross_weight_kg is not None
                else "Belirtilmedi - standart FTL varsayımı"
            )
            body = f"""
Merhaba,

Aşağıdaki hat için İNDİKATİF / bağlayıcı olmayan bütçe navlunu rica ederiz. Bu talep araç rezervasyonu değildir.

RFQ Referansı: {rfq_reference}

Yükleme: {pickup}
Teslimat: {delivery}
Ürün: {shipment.commodity or "Standart non-ADR genel yük varsayımı"}
Paket / Ölçüler: {package_text}
Brüt Ağırlık: {weight_text}
Servis Tipi: {shipment.service_type}
Araç / Ekipman: {equipment_decision.selected_equipment}

Varsayım: standart non-ADR, sıcaklık kontrolü gerektirmeyen FTL/tenteli yük.

Lütfen indikatif navlun fiyatı ve para birimini paylaşınız. Varsa tahmini transit süreyi de ekleyebilirsiniz.

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()
        else:
            body = f"""
Merhaba,

Aşağıdaki taşıma için fiyat ve araç uygunluğunuzu rica ederiz.

RFQ Referansı: {rfq_reference}

Yükleme: {pickup}
Teslimat: {delivery}
Ürün: {shipment.commodity}
Paket / Ölçüler: {packages}
Brüt Ağırlık: {shipment.gross_weight_kg:g} kg
Servis Tipi: {shipment.service_type}
Araç / Ekipman: {equipment_decision.selected_equipment}
Yük Hazır Tarihi: {shipment.cargo_ready_date}
Gerekli Teslim Tarihi: {required_delivery_text}
{special_notes_line}
Lütfen aşağıdaki bilgileri paylaşınız:

- Navlun fiyatı ve para birimi
- Tahmini transit süre ve zaman birimi
- Varsa standart navluna dahil olmayan ek / hariç masraflar
- Talep edilenden farklı bir araç / ekipman öneriyorsanız ekipman tipi

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()

        drafts.append(
            SupplierRFQDraft(
                rfq_id=rfq_id,
                workflow_id=resolved_workflow_id,
                supplier_name=supplier_name,
                priority=priority,
                recipient_email=recipient_email,
                supplier_role=supplier.get("supplier_role"),
                dispatch_tier=supplier.get("dispatch_tier", "primary"),
                selection_explanation=_selection_explanation(supplier, supplier_selection),
                subject=subject,
                body=body,
            )
        )

    return drafts
