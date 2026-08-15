"""Explicit sources for read-only operational workflow data."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from src.paths import REPO_ROOT, data_path
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.supplier_capability_validator import (
    validate_supplier_capabilities_file,
)


PILOT_DATA_DIR_ENV = "MINAI_PILOT_DATA_DIR"


class OperationalDataSourceConfigurationError(RuntimeError):
    """Pilot operational-data source configuration is unsafe or incomplete."""


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


def operational_data_sources_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    require_external: bool = False,
) -> OperationalDataSources:
    """Resolve one external pilot data pack without exposing remote path choice."""

    env = environ if environ is not None else os.environ
    raw = (env.get(PILOT_DATA_DIR_ENV) or "").strip()
    if not raw:
        if require_external:
            raise OperationalDataSourceConfigurationError(
                "MINAI_PILOT_DATA_DIR is required for the controlled pilot."
            )
        return DEFAULT_OPERATIONAL_DATA_SOURCES

    configured = Path(raw).expanduser()
    if not configured.is_absolute():
        raise OperationalDataSourceConfigurationError(
            "MINAI_PILOT_DATA_DIR must be an absolute path."
        )
    root = configured.resolve()
    repo_root = REPO_ROOT.resolve()

    try:
        root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data must be stored outside the repository."
        )

    if not root.is_dir():
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data directory is unavailable."
        )

    data_candidate = root / "data"
    if data_candidate.is_symlink():
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data pack is incomplete or unsafe."
        )

    data_root = data_candidate.resolve()
    if data_root.parent != root:
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data pack is incomplete or unsafe."
        )

    try:
        data_root.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data must be stored outside the repository."
        )

    if not data_root.is_dir():
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data pack is incomplete or unsafe."
        )

    filenames = {
        "provenance_registry_path": "provenance_registry.json",
        "customer_memory_path": "customer_memory.json",
        "supplier_capabilities_path": "supplier_capabilities.json",
    }
    paths: dict[str, Path] = {}

    for key, filename in filenames.items():
        candidate = data_root / filename
        if candidate.is_symlink():
            raise OperationalDataSourceConfigurationError(
                "Pilot operational data pack is incomplete or unsafe."
            )
        resolved = candidate.resolve()
        if resolved.parent != data_root or not resolved.is_file():
            raise OperationalDataSourceConfigurationError(
                "Pilot operational data pack is incomplete or unsafe."
            )
        paths[key] = resolved

    sources = OperationalDataSources(**paths)

    try:
        customer_validation = validate_customer_memory_file(
            sources.customer_memory_path
        )
        supplier_validation = validate_supplier_capabilities_file(
            sources.supplier_capabilities_path
        )
    except (OSError, UnicodeError, ValueError) as exc:
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data pack contains unreadable operational datasets."
        ) from exc

    if (
        customer_validation.get("valid") is not True
        or supplier_validation.get("valid") is not True
    ):
        raise OperationalDataSourceConfigurationError(
            "Pilot operational data pack contains structurally invalid "
            "operational datasets."
        )

    return sources
