from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.core.pilot_access import pilot_mode_enabled


PROVENANCE_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "provenance_registry.json"
)

ALLOWED_CLASSIFICATIONS = {
    "demo",
    "internal_reference",
    "pilot_verified",
}


class DataProvenanceError(RuntimeError):
    pass


class DataProvenanceBlockedError(DataProvenanceError):
    pass


def calculate_dataset_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_data_provenance_registry(
    path: Path = PROVENANCE_REGISTRY_PATH,
) -> dict[str, Any]:
    if not path.exists():
        raise DataProvenanceError(
            f"Data provenance registry not found: {path}"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DataProvenanceError(
            f"Invalid data provenance registry JSON: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise DataProvenanceError(
            "Data provenance registry root must be an object."
        )

    return raw


def validate_data_provenance_registry(
    path: Path = PROVENANCE_REGISTRY_PATH,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    try:
        registry = load_data_provenance_registry(path)
    except DataProvenanceError as exc:
        return {
            "valid": False,
            "errors": [str(exc)],
            "warnings": [],
            "dataset_count": 0,
            "source": str(path),
        }

    datasets = registry.get("datasets")

    if not isinstance(datasets, dict) or not datasets:
        return {
            "valid": False,
            "errors": [
                "Data provenance registry must contain non-empty datasets."
            ],
            "warnings": [],
            "dataset_count": 0,
            "source": str(path),
        }

    repo_root = path.resolve().parent.parent

    for dataset_key, record in datasets.items():
        prefix = f"{dataset_key}:"

        if not isinstance(record, dict):
            errors.append(f"{prefix} provenance record must be an object.")
            continue

        dataset_path = record.get("path")
        classification = record.get("classification")
        operational = record.get("operational")
        pilot_usable = record.get("pilot_usable")

        if not isinstance(dataset_path, str) or not dataset_path.strip():
            errors.append(f"{prefix} path is required.")
        else:
            resolved = repo_root / dataset_path
            if not resolved.exists():
                errors.append(
                    f"{prefix} dataset file does not exist: {dataset_path}"
                )

        if classification not in ALLOWED_CLASSIFICATIONS:
            errors.append(
                f"{prefix} unsupported classification: {classification}"
            )

        if not isinstance(operational, bool):
            errors.append(f"{prefix} operational must be boolean.")

        if not isinstance(pilot_usable, bool):
            errors.append(f"{prefix} pilot_usable must be boolean.")

        if (
            operational is True
            and pilot_usable is True
            and classification != "pilot_verified"
        ):
            errors.append(
                f"{prefix} operational pilot data must be pilot_verified."
            )

        if classification == "pilot_verified":
            verified_by = record.get("verified_by")
            verified_at = record.get("verified_at")
            verified_sha256 = record.get("verified_sha256")

            if not isinstance(verified_by, str) or not verified_by.strip():
                errors.append(
                    f"{prefix} pilot_verified data requires verified_by."
                )

            if not isinstance(verified_at, str) or not verified_at.strip():
                errors.append(
                    f"{prefix} pilot_verified data requires verified_at."
                )

            if (
                operational is True
                and (
                    not isinstance(verified_sha256, str)
                    or len(verified_sha256) != 64
                    or any(
                        char not in "0123456789abcdefABCDEF"
                        for char in verified_sha256
                    )
                )
            ):
                errors.append(
                    f"{prefix} operational pilot_verified data "
                    "requires a valid SHA-256 fingerprint."
                )

        if classification == "internal_reference" and operational is True:
            warnings.append(
                f"{prefix} internal_reference dataset is marked operational."
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "dataset_count": len(datasets),
        "source": str(path),
    }


def get_dataset_provenance(
    dataset_key: str,
    path: Path = PROVENANCE_REGISTRY_PATH,
) -> dict[str, Any]:
    validation = validate_data_provenance_registry(path)

    if not validation["valid"]:
        raise DataProvenanceError(
            "Data provenance registry is invalid: "
            + "; ".join(validation["errors"])
        )

    registry = load_data_provenance_registry(path)
    datasets = registry["datasets"]

    record = datasets.get(dataset_key)

    if not isinstance(record, dict):
        raise DataProvenanceError(
            f"Dataset has no provenance record: {dataset_key}"
        )

    return dict(record)


def require_pilot_operational_dataset(
    dataset_key: str,
    *,
    environ: Mapping[str, str] | None = None,
    path: Path = PROVENANCE_REGISTRY_PATH,
) -> dict[str, Any]:
    record = get_dataset_provenance(dataset_key, path)

    if not pilot_mode_enabled(environ):
        return record

    if record.get("operational") is not True:
        return record

    if (
        record.get("classification") != "pilot_verified"
        or record.get("pilot_usable") is not True
    ):
        raise DataProvenanceBlockedError(
            "Pilot operational dataset is not verified: "
            f"{dataset_key} "
            f"(classification={record.get('classification')}, "
            f"pilot_usable={record.get('pilot_usable')})"
        )

    dataset_path = (
        path.resolve().parent.parent
        / str(record.get("path"))
    )

    expected_sha256 = record.get("verified_sha256")

    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(
            char not in "0123456789abcdefABCDEF"
            for char in expected_sha256
        )
    ):
        raise DataProvenanceBlockedError(
            "Pilot operational dataset has no valid verified fingerprint: "
            f"{dataset_key}"
        )

    actual_sha256 = calculate_dataset_sha256(dataset_path)

    if actual_sha256 != expected_sha256.lower():
        raise DataProvenanceBlockedError(
            "Pilot operational dataset changed after verification: "
            f"{dataset_key}"
        )

    return record
