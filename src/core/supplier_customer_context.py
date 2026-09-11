from __future__ import annotations

from typing import Any

from src.core.master_data import normalize_master_text
from src.core.master_data_repository import MasterDataRepository
from src.core.supplier_context import shipment_context_keys


def resolve_customer_master_profile(
    *, customer_name: str | None, master_repository: MasterDataRepository | None,
):
    if master_repository is None or not str(customer_name or "").strip():
        return None
    direct = master_repository.find_customer_by_name(str(customer_name))
    if direct is not None and direct.active:
        return direct
    target = normalize_master_text(str(customer_name))
    matches = []
    for profile in master_repository.list_customers():
        if not profile.active:
            continue
        terms = [profile.customer_name, *profile.aliases]
        if any(normalize_master_text(term) == target for term in terms):
            matches.append(profile)
    return matches[0] if len(matches) == 1 else None


def supplier_customer_context_keys(
    shipment: Any, *, customer_id: str, equipment_decision: Any | None = None,
) -> list[str]:
    normalized_customer = str(customer_id or "").strip().casefold()
    if not normalized_customer:
        return []
    base = shipment_context_keys(shipment, equipment_decision)
    return [f"customer={normalized_customer}|{item}" for item in base]
