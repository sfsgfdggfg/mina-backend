"""Fail-closed evidence assessment for a real controlled shadow pilot."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from src.core.data_provenance import DataProvenanceError, require_pilot_operational_dataset
from src.core.operational_data import (
    DEFAULT_OPERATIONAL_DATA_SOURCES,
    OperationalDataSourceConfigurationError,
    OperationalDataSources,
    operational_data_sources_from_environment,
)
from src.core.pilot_access import route_allowed


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_EVIDENCE_KEYS = {"body_text", "email_body", "token", "password", "api_key", "raw_email"}
APPROVAL_KEYS = (
    "organization_approval", "privacy_legal_approval", "openai_data_control_approval",
    "deployment_storage_approval", "retention_deletion_approval",
    "named_operators_confirmed", "senior_road_reviewer_confirmed",
)


class Status(str, Enum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_RUN = "NOT_RUN"
    EXPECTED_DISABLED = "EXPECTED_DISABLED"
    FAIL = "FAIL"


@dataclass(frozen=True)
class ReadinessCheck:
    check_id: str
    label: str
    status: Status
    reason_code: str
    safe_summary: str
    evidence: tuple[str, ...] = ()
    mandatory: bool = True


@dataclass(frozen=True)
class PilotReadinessResult:
    checks: tuple[ReadinessCheck, ...]
    real_shadow_pilot_go: bool
    blocking_check_ids: tuple[str, ...]
    technical_failures: tuple[str, ...]
    external_unverified: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalGateResults:
    runtime_preflight: Status
    canonical_regression: Status
    synthetic_rehearsal: Status
    git_commit_sha: str | None
    clean_worktree: bool | None


class EvidenceValidationError(ValueError):
    """Evidence is malformed or unsafe; details are intentionally not printed."""


def _run_command(module: str, *, timeout: int = 180) -> Status:
    env = dict(os.environ)
    env.pop("OPENAI_API_KEY", None)
    try:
        with tempfile.TemporaryDirectory(prefix="minai-readiness-gate-") as temporary:
            env["MINAI_PILOT_DB_PATH"] = str(Path(temporary) / "pilot.sqlite3")
            completed = subprocess.run(
                [sys.executable, "-m", module], cwd=REPOSITORY_ROOT, env=env,
                capture_output=True, text=True, timeout=timeout, check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return Status.FAIL
    return Status.PASS if completed.returncode == 0 else Status.FAIL


def _git(args: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPOSITORY_ROOT, capture_output=True,
            text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def collect_outbound_policy() -> tuple[bool, bool]:
    supplier_outbound_enabled = route_allowed(
        "POST", "/supplier-rfqs/readiness-probe/send"
    )
    customer_outbound_enabled = route_allowed(
        "POST", "/quotes/prepare-send"
    )
    return supplier_outbound_enabled, customer_outbound_enabled


def collect_technical_gates(*, run_gates: bool = True) -> TechnicalGateResults:
    head = _git(("rev-parse", "HEAD"))
    sha = head.stdout.strip() if head and head.returncode == 0 and len(head.stdout.strip()) == 40 else None
    status = _git(("status", "--porcelain"))
    clean = status.stdout == "" if status and status.returncode == 0 else None
    gate_status = (
        (_run_command("src.runtime_preflight", timeout=60),
         _run_command("src.simulation.pilot_regression_suite", timeout=300),
         _run_command("src.simulation.pilot_rehearsal", timeout=180))
        if run_gates else (Status.NOT_RUN, Status.NOT_RUN, Status.NOT_RUN)
    )
    return TechnicalGateResults(*gate_status, sha, clean)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower() in FORBIDDEN_EVIDENCE_KEYS or _contains_forbidden_key(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def load_external_evidence(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(REPOSITORY_ROOT.resolve())
    except ValueError:
        pass
    else:
        raise EvidenceValidationError("evidence_path_inside_repository")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceValidationError("evidence_unreadable_or_invalid_json") from exc
    if not isinstance(value, dict) or _contains_forbidden_key(value):
        raise EvidenceValidationError("evidence_schema_or_privacy_invalid")
    expected = {"schema_version", "pilot_commit_sha", *APPROVAL_KEYS, "sanitized_replay"}
    if set(value) != expected or value.get("schema_version") != 1:
        raise EvidenceValidationError("evidence_schema_invalid")
    if not isinstance(value.get("pilot_commit_sha"), str) or len(value["pilot_commit_sha"]) != 40:
        raise EvidenceValidationError("evidence_commit_invalid")
    for key in APPROVAL_KEYS:
        item = value.get(key)
        if not isinstance(item, dict) or set(item) != {"confirmed", "confirmed_by", "confirmed_at"}:
            raise EvidenceValidationError("evidence_approval_invalid")
        if item.get("confirmed") is not True or not isinstance(item.get("confirmed_by"), str) or not item["confirmed_by"].strip() or not _timestamp(item.get("confirmed_at")):
            raise EvidenceValidationError("evidence_approval_invalid")
    replay = value.get("sanitized_replay")
    if not isinstance(replay, dict) or set(replay) != {"completed", "result", "completed_at", "case_count", "safety_critical_mismatches"}:
        raise EvidenceValidationError("evidence_replay_invalid")
    if not isinstance(replay.get("completed"), bool) or replay.get("result") not in {"pass", "fail"} or not _timestamp(replay.get("completed_at")) or not isinstance(replay.get("case_count"), int) or isinstance(replay.get("case_count"), bool) or replay["case_count"] < 0 or not isinstance(replay.get("safety_critical_mismatches"), int) or isinstance(replay.get("safety_critical_mismatches"), bool) or replay["safety_critical_mismatches"] < 0:
        raise EvidenceValidationError("evidence_replay_invalid")
    return value


def _check(check_id: str, label: str, status: Status, reason: str, summary: str, *evidence: str, mandatory: bool = True) -> ReadinessCheck:
    return ReadinessCheck(check_id, label, status, reason, summary, tuple(evidence), mandatory)


def assess_readiness(
    gates: TechnicalGateResults, *, evidence: Mapping[str, Any] | None = None,
    data_sources: OperationalDataSources = DEFAULT_OPERATIONAL_DATA_SOURCES,
    supplier_outbound_enabled: bool = False, customer_outbound_enabled: bool = False,
) -> PilotReadinessResult:
    checks: list[ReadinessCheck] = []
    for check_id, label, state in (
        ("runtime_preflight", "Runtime preflight", gates.runtime_preflight),
        ("canonical_regression", "Technical regression gate", gates.canonical_regression),
        ("synthetic_rehearsal", "Synthetic full rehearsal", gates.synthetic_rehearsal),
    ):
        reason = f"{check_id}_{'passed' if state == Status.PASS else 'not_run' if state == Status.NOT_RUN else 'failed'}"
        checks.append(_check(check_id, label, state, reason, reason))
    capability_state = Status.PASS if gates.canonical_regression == Status.PASS else gates.canonical_regression
    for check_id, label in (
        ("pilot_launcher", "Safe pilot launcher/configuration"),
        ("operator_controls", "Authenticated operator controls"),
        ("persistence", "Persistence/durability coverage"),
        ("pilot_scope", "Pilot scope fail-closed coverage"),
        ("network_isolation", "Network/outbound isolation coverage"),
        ("replay_harness", "Replay harness capability"),
    ):
        checks.append(_check(check_id, label, capability_state, f"{check_id}_canonical_coverage", "covered_by_current_canonical_gate"))
    if gates.git_commit_sha is None:
        checks.append(_check("git_commit", "Repository commit identity", Status.BLOCKED, "git_commit_unavailable", "current_commit_not_verified"))
    else:
        checks.append(_check("git_commit", "Repository commit identity", Status.PASS, "git_commit_verified", "current_commit_verified"))
    clean_state = Status.PASS if gates.clean_worktree is True else Status.BLOCKED
    clean_reason = "worktree_clean" if gates.clean_worktree is True else "worktree_dirty" if gates.clean_worktree is False else "worktree_state_unavailable"
    checks.append(_check("clean_worktree", "Release worktree", clean_state, clean_reason, clean_reason))

    for dataset_key, dataset_path in (
        ("customer_memory", data_sources.customer_memory_path),
        ("supplier_capabilities", data_sources.supplier_capabilities_path),
    ):
        try:
            require_pilot_operational_dataset(dataset_key, environ={"MINAI_PILOT_MODE": "true"}, path=data_sources.provenance_registry_path, dataset_path=dataset_path)
        except (DataProvenanceError, OSError, ValueError):
            state, reason = Status.BLOCKED, f"{dataset_key}_not_pilot_verified"
        else:
            state, reason = Status.PASS, f"{dataset_key}_pilot_verified"
        checks.append(_check(dataset_key, "Real customer dataset" if dataset_key == "customer_memory" else "Real supplier dataset", state, reason, reason))

    commit_matches = bool(evidence and gates.git_commit_sha and evidence.get("pilot_commit_sha") == gates.git_commit_sha)
    if evidence is None:
        checks.append(_check("sanitized_replay", "Authorized sanitized replay", Status.NOT_RUN, "sanitized_replay_not_run", "no_current_authorized_replay_attestation"))
    elif not commit_matches:
        checks.append(_check("sanitized_replay", "Authorized sanitized replay", Status.NOT_VERIFIED, "evidence_commit_mismatch", "attestation_not_bound_to_current_commit"))
    elif (evidence["sanitized_replay"]["completed"] is not True
          or evidence["sanitized_replay"]["result"] != "pass"
          or evidence["sanitized_replay"]["case_count"] <= 0
          or evidence["sanitized_replay"]["safety_critical_mismatches"] != 0):
        checks.append(_check("sanitized_replay", "Authorized sanitized replay", Status.BLOCKED, "sanitized_replay_failed_or_incomplete", "authorized_replay_did_not_pass_safely"))
    else:
        checks.append(_check("sanitized_replay", "Authorized sanitized replay", Status.PASS, "sanitized_replay_attested", "human_attestation_for_current_commit"))

    labels = {
        "organization_approval": "Organization approval", "privacy_legal_approval": "Privacy/legal approval",
        "openai_data_control_approval": "OpenAI data-control approval", "deployment_storage_approval": "Deployment/storage approval",
        "retention_deletion_approval": "Retention/deletion procedure", "named_operators_confirmed": "Named operators",
        "senior_road_reviewer_confirmed": "Senior road reviewer",
    }
    for key in APPROVAL_KEYS:
        state = Status.PASS if evidence is not None and commit_matches else Status.NOT_VERIFIED
        reason = f"{key}_attested" if state == Status.PASS else "evidence_commit_mismatch" if evidence is not None else f"{key}_not_verified"
        checks.append(_check(key, labels[key], state, reason, "human_attestation_for_current_commit" if state == Status.PASS else reason))

    for check_id, label, enabled in (
        ("supplier_outbound", "Automated supplier outbound", supplier_outbound_enabled),
        ("customer_outbound", "Automated customer outbound", customer_outbound_enabled),
    ):
        state = Status.BLOCKED if enabled else Status.EXPECTED_DISABLED
        checks.append(_check(check_id, label, state, f"{check_id}_{'enabled' if enabled else 'disabled_by_policy'}", "automated_outbound_must_remain_disabled"))
    checks.append(_check("pilot_scope_summary", "Allowed pilot scope", Status.PASS, "road_human_operated_scope", "road_only_one_firm_human_operated_no_autonomous_outbound", "excluded:ADR,reefer,medical_pharma,chemical,high_value,oversize_project,multimodal,mixed_currency", mandatory=False))

    blockers = tuple(item.check_id for item in checks if item.mandatory and item.status in {Status.FAIL, Status.BLOCKED, Status.NOT_VERIFIED, Status.NOT_RUN})
    return PilotReadinessResult(tuple(checks), not blockers, blockers,
        tuple(item.check_id for item in checks if item.check_id in {"runtime_preflight", "canonical_regression", "synthetic_rehearsal", "git_commit", "clean_worktree"} and item.status != Status.PASS),
        tuple(item.check_id for item in checks if item.status == Status.NOT_VERIFIED))


def print_result(result: PilotReadinessResult, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    print("MINAI Pilot Readiness\n", file=stream)
    for item in result.checks:
        print(f"{item.label:.<42} {item.status.value.replace('_', ' ')}", file=stream)
    print(f"\nBlocking prerequisites: {len(result.blocking_check_ids)}", file=stream)
    if result.blocking_check_ids:
        print("Blocking check IDs: " + ", ".join(result.blocking_check_ids), file=stream)
    print("\nREAL SHADOW PILOT: " + ("GO" if result.real_shadow_pilot_go else "NO-GO"), file=stream)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assess controlled shadow-pilot readiness.")
    parser.add_argument("--evidence", type=Path, help="External human-attestation JSON (must be outside the repository).")
    parser.add_argument("--no-run-gates", action="store_true", help="Do not execute live technical gates; they report NOT RUN.")
    args = parser.parse_args(argv)
    try:
        evidence = load_external_evidence(args.evidence) if args.evidence else None
    except EvidenceValidationError:
        print("MINAI Pilot Readiness\n\nEvidence file ........ INVALID\n\nREAL SHADOW PILOT: NO-GO", file=sys.stderr)
        return 2
    supplier_outbound_enabled, customer_outbound_enabled = collect_outbound_policy()
    try:
        data_sources = operational_data_sources_from_environment()
    except OperationalDataSourceConfigurationError:
        print(
            "MINAI Pilot Readiness\n\n"
            "Operational data pack ........ INVALID\n\n"
            "REAL SHADOW PILOT: NO-GO",
            file=sys.stderr,
        )
        return 2

    result = assess_readiness(
        collect_technical_gates(run_gates=not args.no_run_gates),
        evidence=evidence,
        data_sources=data_sources,
        supplier_outbound_enabled=supplier_outbound_enabled,
        customer_outbound_enabled=customer_outbound_enabled,
    )
    print_result(result)
    return 0 if result.real_shadow_pilot_go else 1


if __name__ == "__main__":
    raise SystemExit(main())
