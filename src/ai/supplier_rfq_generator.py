from __future__ import annotations

from typing import Any, List

from pydantic import BaseModel

from src.core.models import EquipmentDecision, Shipment


class SupplierRFQDraft(BaseModel):
    supplier_name: str
    priority: int
    subject: str
    body: str
    source: str = "supplier_rfq_generator"


def generate_supplier_rfq_drafts(
    *,
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    supplier_selection: dict[str, Any],
) -> List[SupplierRFQDraft]:
    drafts: List[SupplierRFQDraft] = []

    selected_suppliers = supplier_selection.get("selected_suppliers", [])[:3]

    for supplier in selected_suppliers:
        supplier_name = supplier.get("supplier_name") or "Tedarikçi"
        priority = int(supplier.get("priority") or 0)

        subject = (
            f"Navlun Talebi | "
            f"{shipment.pickup_city} - {shipment.delivery_city}"
        )

        body = f"""
Merhaba,

Aşağıdaki taşıma için fiyat ve araç uygunluğunuzu rica ederiz.

Yükleme: {shipment.pickup_city}, {shipment.pickup_country}
Teslimat: {shipment.delivery_city}, {shipment.delivery_country}
Ürün: {shipment.commodity}
Brüt Ağırlık: {shipment.gross_weight_kg} kg
Servis Tipi: {shipment.service_type}
Araç / Ekipman: {equipment_decision.selected_equipment}
Yük Hazır Tarihi: {shipment.cargo_ready_date}

Lütfen aşağıdaki bilgileri paylaşınız:

- Navlun fiyatı ve para birimi
- Araç uygunluk tarihi
- Tahmini transit süre
- Fiyata dahil / hariç masraflar
- Teklif geçerlilik süresi

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()

        drafts.append(
            SupplierRFQDraft(
                supplier_name=supplier_name,
                priority=priority,
                subject=subject,
                body=body,
            )
        )

    return drafts
