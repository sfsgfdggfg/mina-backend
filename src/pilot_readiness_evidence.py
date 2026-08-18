"""Guided builder for external controlled-pilot readiness evidence."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.core.data_provenance import (
    DataProvenanceError,
    calculate_dataset_sha256,
    require_pilot_operational_dataset,
)
from src.core.operational_data import (
    OperationalDataSourceConfigurationError,
    OperationalDataSources,
    operational_data_sources_from_environment,
)
from src.paths import REPO_ROOT
from src.pilot_readiness import (
    APPROVAL_KEYS,
    READINESS_EVIDENCE_SCHEMA_VERSION,
    EvidenceValidationError,
    load_external_evidence,
)
from src.simulation.replay_receipt import (
    ReleaseIdentity,
    ReplayReceipt,
    ReplayReceiptError,
    collect_release_identity,
    load_replay_receipt,
    receipt_readiness_summary,
    require_clean_release_identity,
)


APPROVAL_LABELS = {
    "organization_approval": "Organization approval",
    "privacy_legal_approval": "Privacy/legal approval",
    "openai_data_control_approval": "OpenAI data-control approval",
    "deployment_storage_approval": "Deployment/storage approval",
    "retention_deletion_approval": "Retention/deletion procedure",
    "named_operators_confirmed": "Named operators confirmed",
    "senior_road_reviewer_confirmed": "Senior road reviewer confirmed",
}


class ReadinessEvidenceBuilderError(ValueError):
    """A readiness-evidence operation is unsafe or incomplete."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _path_has_symlink(path: Path) -> bool:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    current = Path(candidate.anchor)
    for part in candidate.parts[1:]:
        current = current / part
        try:
            if current.is_symlink():
                return True
        except OSError:
            return True
    return False


def _outside_repository_destination(path: Path) -> Path:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        raise ReadinessEvidenceBuilderError(
            "evidence_path_must_be_absolute"
        )
    if _path_has_symlink(candidate.parent):
        raise ReadinessEvidenceBuilderError(
            "evidence_path_symlink_forbidden"
        )
    try:
        parent = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReadinessEvidenceBuilderError(
            "evidence_parent_unavailable"
        ) from exc
    if not parent.is_dir():
        raise ReadinessEvidenceBuilderError(
            "evidence_parent_unavailable"
        )
    destination = parent / candidate.name
    try:
        destination.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return destination
    raise ReadinessEvidenceBuilderError(
        "evidence_path_inside_repository"
    )


def _verified_operational_hashes(
    sources: OperationalDataSources,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, path in (
        ("customer_memory", sources.customer_memory_path),
        ("supplier_capabilities", sources.supplier_capabilities_path),
    ):
        try:
            require_pilot_operational_dataset(
                key,
                environ={"MINAI_PILOT_MODE": "true"},
                path=sources.provenance_registry_path,
                dataset_path=path,
            )
            result[key] = calculate_dataset_sha256(path)
        except (DataProvenanceError, OSError, ValueError) as exc:
            raise ReadinessEvidenceBuilderError(
                "operational_data_not_verified"
            ) from exc
    return result


def _normalize_approvals(
    approvals: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    if set(approvals) != set(APPROVAL_KEYS):
        raise ReadinessEvidenceBuilderError(
            "approval_set_incomplete"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for key in APPROVAL_KEYS:
        value = approvals[key]
        if (
            value.get("confirmed") is not True
            or not isinstance(value.get("confirmed_by"), str)
            or not value["confirmed_by"].strip()
            or not isinstance(value.get("confirmed_at"), str)
            or not value["confirmed_at"].strip()
        ):
            raise ReadinessEvidenceBuilderError(
                "approval_record_invalid"
            )
        normalized[key] = {
            "confirmed": True,
            "confirmed_by": value["confirmed_by"].strip(),
            "confirmed_at": value["confirmed_at"].strip(),
        }
    return normalized


def validate_receipt_context(
    *,
    receipt: ReplayReceipt,
    release_identity: ReleaseIdentity,
    operational_data_sources: OperationalDataSources,
) -> None:
    try:
        require_clean_release_identity(release_identity)
    except ReplayReceiptError as exc:
        raise ReadinessEvidenceBuilderError(exc.code) from exc

    if receipt.pilot_commit_sha != release_identity.commit_sha:
        raise ReadinessEvidenceBuilderError(
            "replay_receipt_commit_mismatch"
        )
    if (
        receipt.result != "pass"
        or receipt.case_count <= 0
        or receipt.safety_critical_mismatches != 0
    ):
        raise ReadinessEvidenceBuilderError(
            "replay_receipt_not_go_eligible"
        )

    current_hashes = _verified_operational_hashes(
        operational_data_sources
    )
    if receipt.operational_dataset_sha256 != current_hashes:
        raise ReadinessEvidenceBuilderError(
            "replay_receipt_operational_data_mismatch"
        )


def build_readiness_evidence(
    *,
    receipt: ReplayReceipt,
    approvals: Mapping[str, Mapping[str, Any]],
    release_identity: ReleaseIdentity,
    operational_data_sources: OperationalDataSources,
) -> dict[str, Any]:
    validate_receipt_context(
        receipt=receipt,
        release_identity=release_identity,
        operational_data_sources=operational_data_sources,
    )

    evidence: dict[str, Any] = {
        "schema_version": READINESS_EVIDENCE_SCHEMA_VERSION,
        "pilot_commit_sha": receipt.pilot_commit_sha,
        "operational_dataset_sha256": dict(
            receipt.operational_dataset_sha256
        ),
    }
    evidence.update(_normalize_approvals(approvals))
    evidence["sanitized_replay"] = receipt_readiness_summary(receipt)
    return evidence


def collect_attestations(
    *,
    input_fn: Callable[[str], str] = input,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, dict[str, Any]]:
    approvals: dict[str, dict[str, Any]] = {}
    for key in APPROVAL_KEYS:
        label = APPROVAL_LABELS[key]
        confirmation = input_fn(
            f"{label}: type CONFIRM only if approval already exists: "
        ).strip()
        if confirmation != "CONFIRM":
            raise ReadinessEvidenceBuilderError(
                f"{key}_not_confirmed"
            )
        confirmed_by = input_fn(
            f"{label}: confirmed by role/name: "
        ).strip()
        if not confirmed_by:
            raise ReadinessEvidenceBuilderError(
                f"{key}_confirmed_by_required"
            )
        moment = now()
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ReadinessEvidenceBuilderError(
                "attestation_timestamp_not_timezone_aware"
            )
        approvals[key] = {
            "confirmed": True,
            "confirmed_by": confirmed_by,
            "confirmed_at": moment.isoformat(),
        }
    return approvals


def write_readiness_evidence(
    path: Path,
    evidence: Mapping[str, Any],
) -> Path:
    destination = _outside_repository_destination(path)
    if destination.exists() or destination.is_symlink():
        raise ReadinessEvidenceBuilderError(
            "readiness_evidence_already_exists"
        )

    payload = (
        json.dumps(
            dict(evidence),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise ReadinessEvidenceBuilderError(
                "readiness_evidence_already_exists"
            ) from exc
        if os.name == "posix":
            destination.chmod(0o600)
        try:
            load_external_evidence(destination)
        except EvidenceValidationError as exc:
            destination.unlink(missing_ok=True)
            raise ReadinessEvidenceBuilderError(
                "generated_evidence_invalid"
            ) from exc
    except ReadinessEvidenceBuilderError:
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ReadinessEvidenceBuilderError(
            "readiness_evidence_write_failed"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build create-only external controlled-pilot readiness "
            "evidence from an approved replay receipt."
        )
    )
    parser.add_argument(
        "build",
        nargs="?",
        default="build",
        choices=("build",),
    )
    parser.add_argument(
        "--replay-receipt",
        type=Path,
        required=True,
        help="absolute external authorized replay receipt path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="absolute external create-only readiness evidence path",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    input_fn: Callable[[str], str] = input,
    release_identity_func: Callable[[], ReleaseIdentity] = (
        collect_release_identity
    ),
) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = load_replay_receipt(args.replay_receipt)
        sources = operational_data_sources_from_environment(
            require_external=True
        )
        initial_identity = release_identity_func()
        validate_receipt_context(
            receipt=receipt,
            release_identity=initial_identity,
            operational_data_sources=sources,
        )
        approvals = collect_attestations(input_fn=input_fn)
        current_identity = release_identity_func()
        evidence = build_readiness_evidence(
            receipt=receipt,
            approvals=approvals,
            release_identity=current_identity,
            operational_data_sources=sources,
        )
        destination = write_readiness_evidence(
            args.output,
            evidence,
        )
    except (
        ReadinessEvidenceBuilderError,
        ReplayReceiptError,
        OperationalDataSourceConfigurationError,
    ) as exc:
        code = getattr(exc, "code", "operational_data_configuration_invalid")
        print(
            f"Readiness evidence blocked: {code}",
            file=sys.stderr,
        )
        return 2

    print(
        "Readiness evidence written: "
        f"{destination.name}"
    )
    print(
        "This records existing approvals; it does not grant approval "
        "or start the real shadow pilot."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
