"""Safe, immutable evidence receipt for an authorized sanitized replay."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.data_provenance import (
    DataProvenanceError,
    calculate_dataset_sha256,
    require_pilot_operational_dataset,
)
from src.core.operational_data import OperationalDataSources
from src.core.privacy import PRIVACY_TRANSFORM_VERSION
from src.paths import REPO_ROOT
from src.simulation.sanitized_replay import (
    ReplayAggregateResult,
    validate_external_path,
)


REPLAY_RECEIPT_SCHEMA_VERSION = 1
CUSTOMER_IDENTITY_MODE = "pseudonymous_replay_no_trusted_sender_assertion"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReleaseIdentity:
    commit_sha: str
    clean_worktree: bool


class ReplayReceiptError(ValueError):
    """Safe receipt failure whose code contains no customer/replay values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ReplayMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction_fields_evaluated: int = Field(ge=0)
    correct_fields: int = Field(ge=0)
    incorrect_fields: int = Field(ge=0)
    missing_fields: int = Field(ge=0)
    unexpected_inference_count: int = Field(ge=0)
    clarification_correct: int = Field(ge=0)
    clarification_evaluated: int = Field(ge=0)
    scope_correct: int = Field(ge=0)
    scope_evaluated: int = Field(ge=0)
    equipment_correct: int = Field(ge=0)
    equipment_evaluated: int = Field(ge=0)
    supplier_progression_correct: int = Field(ge=0)
    supplier_progression_evaluated: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self):
        if (
            self.correct_fields
            + self.incorrect_fields
            + self.missing_fields
            != self.extraction_fields_evaluated
        ):
            raise ValueError("field counts do not reconcile")
        for correct, evaluated in (
            (self.clarification_correct, self.clarification_evaluated),
            (self.scope_correct, self.scope_evaluated),
            (self.equipment_correct, self.equipment_evaluated),
            (
                self.supplier_progression_correct,
                self.supplier_progression_evaluated,
            ),
        ):
            if correct > evaluated:
                raise ValueError("correct count exceeds evaluated count")
        return self


class ReplayReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = REPLAY_RECEIPT_SCHEMA_VERSION
    pilot_commit_sha: str
    completed_at: datetime
    result: Literal["pass", "fail"]
    case_count: int = Field(ge=0)
    safety_critical_mismatches: int = Field(ge=0)
    replay_input_sha256: str
    operational_dataset_sha256: dict[str, str]
    privacy_transform_version: str
    customer_identity_mode: Literal[
        "pseudonymous_replay_no_trusted_sender_assertion"
    ] = CUSTOMER_IDENTITY_MODE
    metrics: ReplayMetrics

    @field_validator("pilot_commit_sha")
    @classmethod
    def valid_commit(cls, value: str) -> str:
        if not _COMMIT_RE.fullmatch(value):
            raise ValueError("invalid commit sha")
        return value

    @field_validator("replay_input_sha256")
    @classmethod
    def valid_input_hash(cls, value: str) -> str:
        if not _SHA256_RE.fullmatch(value):
            raise ValueError("invalid replay hash")
        return value

    @field_validator("operational_dataset_sha256")
    @classmethod
    def valid_dataset_hashes(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != {"customer_memory", "supplier_capabilities"}:
            raise ValueError("invalid dataset hash keys")
        if any(not _SHA256_RE.fullmatch(item) for item in value.values()):
            raise ValueError("invalid dataset hash")
        return value

    @field_validator("privacy_transform_version")
    @classmethod
    def current_privacy_transform(cls, value: str) -> str:
        if value != PRIVACY_TRANSFORM_VERSION:
            raise ValueError("privacy transform version mismatch")
        return value

    @model_validator(mode="after")
    def result_matches_safety(self):
        if self.result == "pass" and self.safety_critical_mismatches != 0:
            raise ValueError("passing receipt cannot have safety mismatches")
        return self


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ReplayReceiptError("repository_identity_unavailable") from exc


def collect_release_identity() -> ReleaseIdentity:
    head = _git(["rev-parse", "HEAD"])
    status = _git(["status", "--porcelain"])
    commit_sha = head.stdout.strip()
    if (
        head.returncode != 0
        or status.returncode != 0
        or not _COMMIT_RE.fullmatch(commit_sha)
    ):
        raise ReplayReceiptError("repository_identity_unavailable")
    return ReleaseIdentity(commit_sha, status.stdout == "")


def require_clean_release_identity(identity: ReleaseIdentity) -> None:
    if not _COMMIT_RE.fullmatch(identity.commit_sha):
        raise ReplayReceiptError("repository_identity_unavailable")
    if not identity.clean_worktree:
        raise ReplayReceiptError("replay_receipt_requires_clean_worktree")


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
        raise ReplayReceiptError("receipt_path_must_be_absolute")
    if _path_has_symlink(candidate.parent):
        raise ReplayReceiptError("receipt_path_symlink_forbidden")
    try:
        parent = candidate.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReplayReceiptError("receipt_parent_unavailable") from exc
    if not parent.is_dir():
        raise ReplayReceiptError("receipt_parent_unavailable")
    destination = parent / candidate.name
    try:
        destination.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return destination
    raise ReplayReceiptError("receipt_path_inside_repository")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ReplayReceiptError("receipt_source_unreadable") from exc
    return digest.hexdigest()


def _verified_dataset_hashes(
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
            raise ReplayReceiptError("operational_data_not_verified") from exc
    return result


def build_replay_receipt(
    result: ReplayAggregateResult,
    *,
    input_path: Path,
    operational_data_sources: OperationalDataSources,
    release_identity: ReleaseIdentity,
    completed_at: datetime | None = None,
) -> ReplayReceipt:
    require_clean_release_identity(release_identity)
    resolved_input = validate_external_path(input_path)
    counts: Counter[str] = result.outcome_counts
    return ReplayReceipt(
        pilot_commit_sha=release_identity.commit_sha,
        completed_at=completed_at or datetime.now(timezone.utc),
        result="pass" if result.passed else "fail",
        case_count=len(result.cases),
        safety_critical_mismatches=result.safety_critical_mismatches,
        replay_input_sha256=_sha256_file(resolved_input),
        operational_dataset_sha256=_verified_dataset_hashes(
            operational_data_sources
        ),
        privacy_transform_version=PRIVACY_TRANSFORM_VERSION,
        metrics=ReplayMetrics(
            extraction_fields_evaluated=result.ground_truth_fields,
            correct_fields=result.correct_fields,
            incorrect_fields=counts["incorrect"],
            missing_fields=counts["missing"],
            unexpected_inference_count=counts["unexpected_inference"],
            clarification_correct=result.clarification_correct,
            clarification_evaluated=result.clarification_evaluated,
            scope_correct=result.scope_correct,
            scope_evaluated=result.scope_evaluated,
            equipment_correct=result.equipment_correct,
            equipment_evaluated=result.equipment_evaluated,
            supplier_progression_correct=result.supplier_progression_correct,
            supplier_progression_evaluated=(
                result.supplier_progression_evaluated
            ),
        ),
    )


def write_replay_receipt(path: Path, receipt: ReplayReceipt) -> Path:
    destination = _outside_repository_destination(path)
    if destination.exists() or destination.is_symlink():
        raise ReplayReceiptError("replay_receipt_already_exists")
    payload = (
        json.dumps(
            receipt.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )
    temp_path = Path(temp_name)
    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temp_path, destination)
        except FileExistsError as exc:
            raise ReplayReceiptError("replay_receipt_already_exists") from exc
        if os.name == "posix":
            destination.chmod(0o600)
    except ReplayReceiptError:
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise ReplayReceiptError("replay_receipt_write_failed") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return destination


def load_replay_receipt(path: Path) -> ReplayReceipt:
    candidate = path.expanduser()
    if not candidate.is_absolute():
        raise ReplayReceiptError("receipt_path_must_be_absolute")
    if _path_has_symlink(candidate):
        raise ReplayReceiptError("receipt_path_symlink_forbidden")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        pass
    except (OSError, RuntimeError) as exc:
        raise ReplayReceiptError("replay_receipt_unreadable") from exc
    else:
        raise ReplayReceiptError("receipt_path_inside_repository")
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
        return ReplayReceipt.model_validate(raw)
    except Exception as exc:
        raise ReplayReceiptError("replay_receipt_unreadable_or_invalid") from exc


def receipt_readiness_summary(receipt: ReplayReceipt) -> dict[str, object]:
    return {
        "completed": True,
        "result": receipt.result,
        "completed_at": receipt.completed_at.isoformat(),
        "case_count": receipt.case_count,
        "safety_critical_mismatches": receipt.safety_critical_mismatches,
    }
