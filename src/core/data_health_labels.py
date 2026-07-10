from __future__ import annotations

from src.core.data_health_registry import get_data_health_check_labels


def get_data_health_check_label(check_name: str) -> str:
    labels = get_data_health_check_labels()

    return labels.get(
        check_name,
        check_name.replace("_", " ").title(),
    )
