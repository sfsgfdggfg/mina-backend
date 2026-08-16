"""Focused regressions for the external pilot data-pack builder."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from src.core.data_provenance import (
    DataProvenanceBlockedError,
    require_pilot_operational_dataset,
)
from src.pilot_data_pack import (
    PilotDataPackError,
    initialize_pack,
    resolve_pack_paths,
    status_pack,
    validate_pack,
    verify_pack,
)
from src.paths import REPO_ROOT


def _customers() -> list[dict]:
    return [
        {
            "customer_name": "Synthetic Customer A",
            "active": True,
            "aliases": [],
            "trusted_sender_addresses": [
                "ops-a@customer-a.invalid"
            ],
            "trusted_sender_domains": [],
            "operational_notes": [],
        },
        {
            "customer_name": "Synthetic Customer B",
            "active": True,
            "aliases": [],
            "trusted_sender_addresses": [
                "ops-b@customer-b.invalid"
            ],
            "trusted_sender_domains": [],
            "operational_notes": [],
        },
    ]


def _supplier(name: str, email: str) -> dict:
    return {
        "supplier_name": name,
        "active": True,
        "role": "primary",
        "route_regions": ["international"],
        "countries": ["Türkiye", "Almanya"],
        "service_types": ["FTL"],
        "equipment_types": ["Tenteli"],
        "special_capabilities": [],
        "priority_routes": ["Türkiye-Almanya"],
        "reliability_score": 0.9,
        "price_score": 0.8,
        "speed_score": 0.8,
        "notes": "Synthetic regression evidence.",
        "contacts": [
            {
                "email": email,
                "active": True,
                "is_primary": True,
            }
        ],
    }


def _suppliers() -> list[dict]:
    return [
        _supplier(
            "Synthetic Supplier A",
            "rfq-a@supplier-a.invalid",
        ),
        _supplier(
            "Synthetic Supplier B",
            "rfq-b@supplier-b.invalid",
        ),
        _supplier(
            "Synthetic Supplier C",
            "rfq-c@supplier-c.invalid",
        ),
    ]


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def evaluate_pilot_data_pack_regressions() -> dict:
    failures: list[str] = []

    try:
        resolve_pack_paths(REPO_ROOT / "data" / "unsafe-pack")
    except PilotDataPackError:
        pass
    else:
        failures.append("repository-contained pilot pack was accepted")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "pilot-pack"
        paths = initialize_pack(root)

        if (
            not paths.customer_memory.is_file()
            or not paths.supplier_capabilities.is_file()
            or paths.provenance_registry.exists()
        ):
            failures.append("pack initialization contract is incorrect")

        try:
            initialize_pack(root)
        except PilotDataPackError:
            pass
        else:
            failures.append("pack initialization overwrote managed files")

        _write_json(paths.customer_memory, _customers())
        _write_json(paths.supplier_capabilities, _suppliers())

        validation = validate_pack(root)
        if (
            validation.get("valid") is not True
            or validation.get("active_customer_count") != 2
            or validation.get("trusted_customer_count") != 2
            or validation.get("active_supplier_count") != 3
            or validation.get("contactable_supplier_count") != 3
        ):
            failures.append("valid pilot pack did not pass cardinality checks")

        try:
            verify_pack(
                root,
                verified_by="Synthetic Data Owner",
                confirm_final_reviewed=False,
            )
        except PilotDataPackError:
            pass
        else:
            failures.append("verification did not require explicit confirmation")

        try:
            verify_pack(
                root,
                verified_by="Synthetic Data Owner",
                confirm_final_reviewed=True,
                verified_at=datetime(2026, 8, 16, 12, 0, 0),
            )
        except PilotDataPackError:
            pass
        else:
            failures.append("naive verification timestamp was accepted")

        status = verify_pack(
            root,
            verified_by="Synthetic Data Owner",
            confirm_final_reviewed=True,
            verified_at=datetime(
                2026,
                8,
                16,
                9,
                0,
                0,
                tzinfo=timezone.utc,
            ),
        )
        if (
            status.get("valid") is not True
            or status.get("verified") is not True
            or not paths.provenance_registry.is_file()
        ):
            failures.append("verified pilot pack did not become verified")

        registry = json.loads(
            paths.provenance_registry.read_text(encoding="utf-8")
        )
        datasets = registry.get("datasets") or {}
        for key in ("customer_memory", "supplier_capabilities"):
            record = datasets.get(key) or {}
            if (
                record.get("classification") != "pilot_verified"
                or record.get("operational") is not True
                or record.get("pilot_usable") is not True
                or record.get("verified_by")
                != "Synthetic Data Owner"
                or len(str(record.get("verified_sha256") or "")) != 64
                or record.get("verified_at")
                != "2026-08-16T09:00:00+00:00"
            ):
                failures.append(
                    f"{key} verification registry record is incomplete"
                )

        pilot_env = {"MINAI_PILOT_MODE": "true"}
        try:
            require_pilot_operational_dataset(
                "customer_memory",
                environ=pilot_env,
                path=paths.provenance_registry,
                dataset_path=paths.customer_memory,
            )
            require_pilot_operational_dataset(
                "supplier_capabilities",
                environ=pilot_env,
                path=paths.provenance_registry,
                dataset_path=paths.supplier_capabilities,
            )
        except Exception:
            failures.append("verified pack failed production provenance check")

        tampered = _suppliers()
        tampered[0]["price_score"] = 0.7
        _write_json(paths.supplier_capabilities, tampered)

        after_tamper = status_pack(root)
        if after_tamper.get("verified") is not False:
            failures.append("tampered verified pack remained verified")

        try:
            require_pilot_operational_dataset(
                "supplier_capabilities",
                environ=pilot_env,
                path=paths.provenance_registry,
                dataset_path=paths.supplier_capabilities,
            )
        except DataProvenanceBlockedError:
            pass
        else:
            failures.append("tampered supplier data did not fail closed")

    with tempfile.TemporaryDirectory() as cardinality_dir:
        root = Path(cardinality_dir) / "pilot-pack"
        paths = initialize_pack(root)
        _write_json(paths.customer_memory, _customers()[:1])
        _write_json(paths.supplier_capabilities, _suppliers())
        result = validate_pack(root)
        if (
            result.get("valid") is not False
            or not any(
                "2 to 3 active customer" in error
                for error in result.get("errors", [])
            )
        ):
            failures.append("undersized customer pilot pack was accepted")

    return {
        "name": "Pilot operational data pack builder",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    print(evaluate_pilot_data_pack_regressions())
