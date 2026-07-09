from __future__ import annotations


DATA_HEALTH_CHECK_LABELS = {
    "commodity_dictionary": "Ürün Sözlüğü",
    "supplier_capabilities": "Tedarikçi Yetkinlik Matrisi",
    "customer_memory": "Müşteri Hafızası",
    "hs_commodity_map": "HS / GTIP Eşleştirme",
}


def get_data_health_check_label(check_name: str) -> str:
    return DATA_HEALTH_CHECK_LABELS.get(
        check_name,
        check_name.replace("_", " ").title(),
    )
