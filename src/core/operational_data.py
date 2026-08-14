"""Explicit sources for read-only operational workflow data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.paths import data_path


@dataclass(frozen=True)
class OperationalDataSources:
    """Coherent paths used by one operational workflow execution."""

    provenance_registry_path: Path = data_path("provenance_registry.json")
    customer_memory_path: Path = data_path("customer_memory.json")
    supplier_capabilities_path: Path = data_path("supplier_capabilities.json")


DEFAULT_OPERATIONAL_DATA_SOURCES = OperationalDataSources()


def resolve_operational_data_sources(
    sources: OperationalDataSources | None,
) -> OperationalDataSources:
    return sources or DEFAULT_OPERATIONAL_DATA_SOURCES
