"""Safe builder and verifier for external controlled-pilot operational data packs."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.data_provenance import (
    DataProvenanceError,
    calculate_dataset_sha256,
    require_pilot_operational_dataset,
)
from src.core.operational_data import (
    PILOT_DATA_DIR_ENV,
    OperationalDataSourceConfigurationError,
    operational_data_sources_from_environment,
)
from src.core.supplier_capability_validator import (
    validate_supplier_capabilities_file,
)
from src.pilot_data_pack_intake import (
    PilotDataPackIntakeError,
    add_customer_profile,
    add_supplier_profile,
    list_customer_profiles,
    list_supplier_profiles,
)
from src.paths import REPO_ROOT


MIN_ACTIVE_PILOT_CUSTOMERS = 2
MAX_ACTIVE_PILOT_CUSTOMERS = 3
MIN_ACTIVE_PILOT_SUPPLIERS = 3
MAX_ACTIVE_PILOT_SUPPLIERS = 5


class PilotDataPackError(ValueError):
    """The requested data-pack operation is unsafe or invalid."""


@dataclass(frozen=True)
class PilotDataPackPaths:
    root: Path
    data_dir: Path
    customer_memory: Path
    supplier_capabilities: Path
    provenance_registry: Path


def _outside_repository(path: Path) -> bool:
    try:
        path.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return True
    return False


def resolve_pack_paths(
    pack_dir: Path | str,
    *,
    require_datasets: bool = False,
    require_registry: bool = False,
) -> PilotDataPackPaths:
    configured = Path(pack_dir).expanduser()
    if not configured.is_absolute():
        raise PilotDataPackError("Pilot data pack path must be absolute.")
    if configured.is_symlink():
        raise PilotDataPackError("Pilot data pack root must not be a symlink.")

    root = configured.resolve()
    if not _outside_repository(root):
        raise PilotDataPackError(
            "Pilot operational data must be stored outside the repository."
        )
    if root.exists() and not root.is_dir():
        raise PilotDataPackError("Pilot data pack root must be a directory.")

    data_dir = root / "data"
    if data_dir.is_symlink():
        raise PilotDataPackError("Pilot data directory must not be a symlink.")
    if data_dir.exists() and not data_dir.is_dir():
        raise PilotDataPackError("Pilot data path must be a directory.")

    paths = PilotDataPackPaths(
        root=root,
        data_dir=data_dir,
        customer_memory=data_dir / "customer_memory.json",
        supplier_capabilities=data_dir / "supplier_capabilities.json",
        provenance_registry=data_dir / "provenance_registry.json",
    )

    required = [paths.customer_memory, paths.supplier_capabilities]
    if require_registry:
        required.append(paths.provenance_registry)

    for candidate in required if require_datasets or require_registry else []:
        if candidate.is_symlink():
            raise PilotDataPackError(
                "Pilot data pack files must not be symlinks."
            )
        resolved = candidate.resolve()
        if resolved.parent != data_dir.resolve():
            raise PilotDataPackError("Pilot data pack file path is unsafe.")
        if not resolved.is_file():
            raise PilotDataPackError(
                f"Required pilot data pack file is missing: {candidate.name}"
            )

    return paths


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def initialize_pack(pack_dir: Path | str) -> PilotDataPackPaths:
    paths = resolve_pack_paths(pack_dir)
    paths.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    targets = (
        paths.customer_memory,
        paths.supplier_capabilities,
        paths.provenance_registry,
    )
    if any(target.exists() or target.is_symlink() for target in targets):
        raise PilotDataPackError(
            "Pilot data pack already contains managed files; refusing to overwrite."
        )

    _atomic_write_json(paths.customer_memory, [])
    _atomic_write_json(paths.supplier_capabilities, [])
    return paths


def validate_pack(pack_dir: Path | str) -> dict[str, Any]:
    paths = resolve_pack_paths(pack_dir, require_datasets=True)
    customer = validate_customer_memory_file(paths.customer_memory)
    supplier = validate_supplier_capabilities_file(
        paths.supplier_capabilities
    )

    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(customer.get("errors") or [])
    errors.extend(supplier.get("errors") or [])
    warnings.extend(customer.get("warnings") or [])
    warnings.extend(supplier.get("warnings") or [])

    active_customers = int(customer.get("active_profile_count") or 0)
    trusted_customers = int(
        customer.get("active_trusted_profile_count") or 0
    )
    active_suppliers = int(supplier.get("active_supplier_count") or 0)
    contactable_suppliers = int(
        supplier.get("active_contactable_supplier_count") or 0
    )

    if customer.get("valid") is True:
        if not (
            MIN_ACTIVE_PILOT_CUSTOMERS
            <= active_customers
            <= MAX_ACTIVE_PILOT_CUSTOMERS
        ):
            errors.append(
                "Pilot pack requires 2 to 3 active customer profiles."
            )
        if trusted_customers != active_customers:
            errors.append(
                "Every active pilot customer requires valid sender trust."
            )

    if supplier.get("valid") is True:
        if not (
            MIN_ACTIVE_PILOT_SUPPLIERS
            <= active_suppliers
            <= MAX_ACTIVE_PILOT_SUPPLIERS
        ):
            errors.append(
                "Pilot pack requires 3 to 5 active supplier profiles."
            )
        if contactable_suppliers != active_suppliers:
            errors.append(
                "Every active pilot supplier requires exactly one usable "
                "active primary RFQ contact."
            )

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "active_customer_count": active_customers,
        "trusted_customer_count": trusted_customers,
        "active_supplier_count": active_suppliers,
        "contactable_supplier_count": contactable_suppliers,
        "pack_root": str(paths.root),
    }


def _verification_record(
    relative_path: str,
    dataset_path: Path,
    *,
    verified_by: str,
    verified_at: datetime,
) -> dict[str, Any]:
    return {
        "path": relative_path,
        "classification": "pilot_verified",
        "operational": True,
        "pilot_usable": True,
        "verified_by": verified_by,
        "verified_at": verified_at.isoformat(),
        "verified_sha256": calculate_dataset_sha256(dataset_path),
    }


def verify_pack(
    pack_dir: Path | str,
    *,
    verified_by: str,
    confirm_final_reviewed: bool,
    verified_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_verifier = verified_by.strip()
    if not normalized_verifier:
        raise PilotDataPackError("verified_by must not be empty.")
    if confirm_final_reviewed is not True:
        raise PilotDataPackError(
            "Final human review confirmation is required before verification."
        )

    moment = verified_at or datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PilotDataPackError("verified_at must be timezone-aware.")

    validation = validate_pack(pack_dir)
    if validation["valid"] is not True:
        raise PilotDataPackError(
            "Pilot data pack validation failed; verification was not written."
        )

    paths = resolve_pack_paths(pack_dir, require_datasets=True)
    if (
        paths.provenance_registry.exists()
        or paths.provenance_registry.is_symlink()
    ):
        raise PilotDataPackError(
            "Pilot data pack already contains a verification registry; "
            "create a new pack version instead of overwriting verified evidence."
        )
    registry = {
        "version": 1,
        "datasets": {
            "customer_memory": _verification_record(
                "data/customer_memory.json",
                paths.customer_memory,
                verified_by=normalized_verifier,
                verified_at=moment,
            ),
            "supplier_capabilities": _verification_record(
                "data/supplier_capabilities.json",
                paths.supplier_capabilities,
                verified_by=normalized_verifier,
                verified_at=moment,
            ),
        },
    }
    _atomic_write_json(paths.provenance_registry, registry)

    status = status_pack(paths.root)
    if status["verified"] is not True:
        raise PilotDataPackError(
            "Verification registry was written but final fingerprint "
            "verification failed."
        )
    return status


def status_pack(pack_dir: Path | str) -> dict[str, Any]:
    try:
        validation = validate_pack(pack_dir)
    except (OSError, UnicodeError, ValueError) as exc:
        return {
            "valid": False,
            "verified": False,
            "errors": [str(exc)],
            "warnings": [],
        }

    result = dict(validation)
    result["verified"] = False

    if validation["valid"] is not True:
        return result

    try:
        paths = resolve_pack_paths(
            pack_dir,
            require_datasets=True,
            require_registry=True,
        )
        sources = operational_data_sources_from_environment(
            {PILOT_DATA_DIR_ENV: str(paths.root)},
            require_external=True,
        )
        pilot_env: Mapping[str, str] = {"MINAI_PILOT_MODE": "true"}
        require_pilot_operational_dataset(
            "customer_memory",
            environ=pilot_env,
            path=sources.provenance_registry_path,
            dataset_path=sources.customer_memory_path,
        )
        require_pilot_operational_dataset(
            "supplier_capabilities",
            environ=pilot_env,
            path=sources.provenance_registry_path,
            dataset_path=sources.supplier_capabilities_path,
        )
    except (
        DataProvenanceError,
        OperationalDataSourceConfigurationError,
        OSError,
        UnicodeError,
        ValueError,
    ) as exc:
        result["errors"] = [*result["errors"], str(exc)]
        return result

    result["verified"] = True
    return result


def _print_result(result: dict[str, Any], stream: TextIO) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2), file=stream)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build and verify an external MINAI controlled-pilot "
            "operational data pack."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)

    for command in ("init", "validate", "status"):
        item = commands.add_parser(command)
        item.add_argument("--pack-dir", required=True, type=Path)

    verify = commands.add_parser("verify")
    verify.add_argument("--pack-dir", required=True, type=Path)
    verify.add_argument("--verified-by", required=True)
    verify.add_argument(
        "--confirm-final-reviewed",
        action="store_true",
        help=(
            "Confirm the final customer and supplier bytes were reviewed "
            "by the named verifier."
        ),
    )

    customer = commands.add_parser("customer")
    customer_commands = customer.add_subparsers(
        dest="customer_action",
        required=True,
    )
    customer_list = customer_commands.add_parser("list")
    customer_list.add_argument("--pack-dir", required=True, type=Path)
    customer_add = customer_commands.add_parser("add")
    customer_add.add_argument("--pack-dir", required=True, type=Path)
    customer_add.add_argument("--name", required=True)
    customer_add.add_argument("--alias", action="append")
    customer_add.add_argument("--trusted-address", action="append")
    customer_add.add_argument("--trusted-domain", action="append")
    customer_add.add_argument("--default-commodity")
    customer_add.add_argument("--default-equipment")
    customer_add.add_argument(
        "--price-sensitivity",
        choices=("low", "medium", "high"),
    )
    customer_add.add_argument(
        "--time-sensitivity",
        choices=("low", "medium", "high"),
    )
    customer_add.add_argument("--pickup-city")
    customer_add.add_argument("--pickup-area")
    customer_add.add_argument("--pickup-country")
    customer_add.add_argument("--delivery-city")
    customer_add.add_argument("--delivery-country")
    customer_add.add_argument("--note", action="append")
    customer_add.add_argument("--inactive", action="store_true")

    supplier = commands.add_parser("supplier")
    supplier_commands = supplier.add_subparsers(
        dest="supplier_action",
        required=True,
    )
    supplier_list = supplier_commands.add_parser("list")
    supplier_list.add_argument("--pack-dir", required=True, type=Path)
    supplier_add = supplier_commands.add_parser("add")
    supplier_add.add_argument("--pack-dir", required=True, type=Path)
    supplier_add.add_argument("--name", required=True)
    supplier_add.add_argument(
        "--role",
        required=True,
        choices=("primary", "backup", "specialist"),
    )
    supplier_add.add_argument(
        "--route-region",
        action="append",
        required=True,
    )
    supplier_add.add_argument(
        "--country",
        action="append",
        required=True,
    )
    supplier_add.add_argument(
        "--service-type",
        action="append",
        required=True,
        choices=("FTL", "LTL"),
    )
    supplier_add.add_argument(
        "--equipment-type",
        action="append",
        required=True,
    )
    supplier_add.add_argument(
        "--special-capability",
        action="append",
    )
    supplier_add.add_argument(
        "--priority-route",
        action="append",
    )
    supplier_add.add_argument(
        "--reliability-score",
        required=True,
        type=float,
    )
    supplier_add.add_argument(
        "--price-score",
        required=True,
        type=float,
    )
    supplier_add.add_argument(
        "--speed-score",
        required=True,
        type=float,
    )
    supplier_add.add_argument("--notes", required=True)
    supplier_add.add_argument("--contact-email", required=True)
    supplier_add.add_argument("--inactive", action="store_true")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stream: TextIO | None = None,
) -> int:
    output = stream or __import__("sys").stdout
    args = _parser().parse_args(argv)

    try:
        if args.command == "init":
            paths = initialize_pack(args.pack_dir)
            result = {
                "initialized": True,
                "pack_root": str(paths.root),
                "customer_memory": str(paths.customer_memory),
                "supplier_capabilities": str(paths.supplier_capabilities),
            }
            _print_result(result, output)
            return 0

        if args.command == "customer":
            paths = resolve_pack_paths(
                args.pack_dir,
                require_datasets=True,
            )
            if args.customer_action == "list":
                result = list_customer_profiles(
                    paths.customer_memory
                )
            else:
                result = add_customer_profile(
                    customer_memory_path=paths.customer_memory,
                    provenance_registry_path=paths.provenance_registry,
                    customer_name=args.name,
                    active=not args.inactive,
                    aliases=args.alias,
                    trusted_sender_addresses=args.trusted_address,
                    trusted_sender_domains=args.trusted_domain,
                    default_commodity=args.default_commodity,
                    default_equipment_type=args.default_equipment,
                    price_sensitivity=args.price_sensitivity,
                    time_sensitivity=args.time_sensitivity,
                    default_pickup_city=args.pickup_city,
                    default_pickup_area=args.pickup_area,
                    default_pickup_country=args.pickup_country,
                    default_delivery_city=args.delivery_city,
                    default_delivery_country=args.delivery_country,
                    operational_notes=args.note,
                )
            _print_result(result, output)
            return 0

        if args.command == "supplier":
            paths = resolve_pack_paths(
                args.pack_dir,
                require_datasets=True,
            )
            if args.supplier_action == "list":
                result = list_supplier_profiles(
                    paths.supplier_capabilities
                )
            else:
                result = add_supplier_profile(
                    supplier_capabilities_path=(
                        paths.supplier_capabilities
                    ),
                    provenance_registry_path=paths.provenance_registry,
                    supplier_name=args.name,
                    active=not args.inactive,
                    role=args.role,
                    route_regions=args.route_region,
                    countries=args.country,
                    service_types=args.service_type,
                    equipment_types=args.equipment_type,
                    special_capabilities=args.special_capability,
                    priority_routes=args.priority_route,
                    reliability_score=args.reliability_score,
                    price_score=args.price_score,
                    speed_score=args.speed_score,
                    notes=args.notes,
                    primary_contact_email=args.contact_email,
                )
            _print_result(result, output)
            return 0

        if args.command == "validate":
            result = validate_pack(args.pack_dir)
            _print_result(result, output)
            return 0 if result["valid"] else 1

        if args.command == "status":
            result = status_pack(args.pack_dir)
            _print_result(result, output)
            return 0 if result.get("verified") is True else 1

        result = verify_pack(
            args.pack_dir,
            verified_by=args.verified_by,
            confirm_final_reviewed=args.confirm_final_reviewed,
        )
        _print_result(result, output)
        return 0 if result.get("verified") is True else 1
    except (PilotDataPackError, PilotDataPackIntakeError) as exc:
        _print_result(
            {
                "valid": False,
                "verified": False,
                "errors": [str(exc)],
                "warnings": [],
            },
            output,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
