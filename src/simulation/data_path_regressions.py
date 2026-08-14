"""Regressions for deterministic repository-owned data paths."""

from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import paths
from src.core.commodity_profile import COMMODITY_DICTIONARY_PATH, load_commodity_dictionary
from src.core.customer_memory import CUSTOMER_MEMORY_FILE, load_customer_memory
from src.core.data_provenance import PROVENANCE_REGISTRY_PATH, load_data_provenance_registry
from src.core.gtip import HS_COMMODITY_MAP_PATH, load_hs_commodity_map
from src.core.pilot_store import DEFAULT_PILOT_DB_PATH, SQLitePilotStore
from src.core.supplier_capability_validator import SUPPLIER_CAPABILITIES_PATH


def _repository_data_snapshot() -> tuple[Path, Path, Path, Path, Path, int, int, int]:
    registry = load_data_provenance_registry()
    return (
        PROVENANCE_REGISTRY_PATH.resolve(),
        COMMODITY_DICTIONARY_PATH.resolve(),
        SUPPLIER_CAPABILITIES_PATH.resolve(),
        CUSTOMER_MEMORY_FILE.resolve(),
        HS_COMMODITY_MAP_PATH.resolve(),
        len(registry.get("datasets", {})),
        len(load_commodity_dictionary()),
        len(load_hs_commodity_map()),
    )


def evaluate_data_path_regressions() -> dict[str, object]:
    failures: list[str] = []
    original_cwd = Path.cwd()

    expected_root = Path(__file__).resolve().parents[2]
    if paths.REPO_ROOT != expected_root:
        failures.append("repository root is not derived from the module location")
    if not paths.DATA_DIR.is_dir():
        failures.append("repository data directory was not found")

    try:
        os.chdir(paths.REPO_ROOT)
        root_snapshot = _repository_data_snapshot()

        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            os.chdir(temp_path)
            unrelated_cwd_snapshot = _repository_data_snapshot()

            if root_snapshot != unrelated_cwd_snapshot:
                failures.append("repository data paths changed with cwd")
            if PROVENANCE_REGISTRY_PATH.resolve() != paths.data_path("provenance_registry.json"):
                failures.append("provenance registry path is not repository-owned")
            if DEFAULT_PILOT_DB_PATH != paths.data_path("pilot", "minai_pilot.sqlite3"):
                failures.append("default pilot database path is not repository-owned")

            supplied_db_path = temp_path / "caller-supplied.sqlite3"
            store = SQLitePilotStore(db_path=supplied_db_path)
            if store.db_path != supplied_db_path:
                failures.append("caller-supplied database path was changed")

            configured_db_path = Path("configured/relative-pilot.sqlite3")
            with patch.dict(
                os.environ,
                {"MINAI_PILOT_DB_PATH": str(configured_db_path)},
                clear=False,
            ):
                configured_store = SQLitePilotStore()
            if configured_store.db_path != configured_db_path:
                failures.append("configured relative database path was changed")
            if configured_store.db_path.is_absolute():
                failures.append("configured relative database path became absolute")
            if not (temp_path / configured_db_path).exists():
                failures.append("configured relative database was not created in temporary cwd")

        if "/workspaces/" + "mina-backend" in "\n".join(
            path.read_text(encoding="utf-8")
            for path in (paths.REPO_ROOT / "src").rglob("*.py")
        ):
            failures.append("a hard-coded workspace path exists")
    finally:
        os.chdir(original_cwd)

    if Path.cwd() != original_cwd:
        failures.append("path regression did not restore cwd")

    return {"passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_data_path_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
