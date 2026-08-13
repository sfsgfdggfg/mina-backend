from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List

from src.core.commodity_dictionary_validator import validate_commodity_dictionary_file
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.hs_commodity_map_validator import validate_hs_commodity_map_file
from src.core.data_provenance import validate_data_provenance_registry
from src.core.supplier_capability_validator import validate_supplier_capabilities_file
from src.core.supplier_capability_registry_validator import (
    validate_supplier_capability_registry_file,
)


ValidationResult = Dict[str, object]


@dataclass(frozen=True)
class DataHealthCheck:
    key: str
    label: str
    validator: Callable[[], ValidationResult]


DATA_HEALTH_CHECKS: List[DataHealthCheck] = [
    DataHealthCheck(
        key="data_provenance",
        label="Veri Kaynağı / Provenance Registry",
        validator=validate_data_provenance_registry,
    ),
    DataHealthCheck(
        key="commodity_dictionary",
        label="Ürün Sözlüğü",
        validator=validate_commodity_dictionary_file,
    ),
    DataHealthCheck(
        key="supplier_capabilities",
        label="Tedarikçi Yetkinlik Matrisi",
        validator=validate_supplier_capabilities_file,
    ),
    DataHealthCheck(
        key="supplier_capability_registry",
        label="Tedarikçi Yetkinlik Registry",
        validator=validate_supplier_capability_registry_file,
    ),
    DataHealthCheck(
        key="customer_memory",
        label="Müşteri Hafızası",
        validator=validate_customer_memory_file,
    ),
    DataHealthCheck(
        key="hs_commodity_map",
        label="HS / GTIP Eşleştirme",
        validator=validate_hs_commodity_map_file,
    ),
]


def get_data_health_checks() -> List[DataHealthCheck]:
    return list(DATA_HEALTH_CHECKS)


def get_data_health_check_keys() -> List[str]:
    return [check.key for check in DATA_HEALTH_CHECKS]


def get_data_health_check_labels() -> Dict[str, str]:
    return {
        check.key: check.label
        for check in DATA_HEALTH_CHECKS
    }


def run_data_health_checks() -> Dict[str, ValidationResult]:
    results: Dict[str, ValidationResult] = {}

    for check in DATA_HEALTH_CHECKS:
        result = dict(check.validator())
        result["label"] = check.label
        results[check.key] = result

    return results
