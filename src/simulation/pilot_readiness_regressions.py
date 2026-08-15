"""Deterministic regressions for the pilot readiness assessment."""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from src.pilot_readiness import (
    EvidenceValidationError, Status, TechnicalGateResults, assess_readiness,
    collect_outbound_policy, collect_technical_gates,
    load_external_evidence, main, print_result,
)
from src.simulation.pilot_rehearsal import _write_synthetic_sources


HEAD = "a" * 40


def _gates(*, canonical: Status = Status.PASS, clean: bool = True, sha: str = HEAD) -> TechnicalGateResults:
    return TechnicalGateResults(Status.PASS, canonical, Status.PASS, sha, clean)


def _evidence(sha: str = HEAD, *, mismatches: int = 0) -> dict:
    approval = {"confirmed": True, "confirmed_by": "authorized-role-01", "confirmed_at": "2026-08-15T00:00:00+00:00"}
    return {
        "schema_version": 1, "pilot_commit_sha": sha,
        "organization_approval": dict(approval), "privacy_legal_approval": dict(approval),
        "openai_data_control_approval": dict(approval), "deployment_storage_approval": dict(approval),
        "retention_deletion_approval": dict(approval), "named_operators_confirmed": dict(approval),
        "senior_road_reviewer_confirmed": dict(approval),
        "sanitized_replay": {"completed": True, "result": "pass", "completed_at": "2026-08-15T00:00:00+00:00", "case_count": 12, "safety_critical_mismatches": mismatches},
    }


def _status(result, check_id: str) -> Status:
    return next(item.status for item in result.checks if item.check_id == check_id)


def _artifacts() -> set[Path]:
    return {path for path in Path(".").rglob("*") if path.is_file() and (path.suffix in {".sqlite3", ".sqlite", ".db"} or path.name.endswith(("-wal", "-shm")))}


def evaluate_pilot_readiness_regressions() -> dict:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    data_root = Path("data")
    before_data = {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()}
    before_artifacts = _artifacts()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = _write_synthetic_sources(root)

        default = assess_readiness(_gates(), evidence=None)
        require("default repository never false GO", not default.real_shadow_pilot_go)
        require("demo customer blocks", _status(default, "customer_memory") == Status.BLOCKED)
        require("demo supplier blocks", _status(default, "supplier_capabilities") == Status.BLOCKED)
        require("missing approvals not verified", _status(default, "organization_approval") == Status.NOT_VERIFIED)
        require("missing replay not run", _status(default, "sanitized_replay") == Status.NOT_RUN)

        controlled = assess_readiness(_gates(), evidence=_evidence(), data_sources=sources)
        require("controlled technical gates represented PASS", all(_status(controlled, key) == Status.PASS for key in ("runtime_preflight", "canonical_regression", "synthetic_rehearsal")))
        require("all required synthetic evidence can GO", controlled.real_shadow_pilot_go)
        require("GO exact commit match", _status(controlled, "organization_approval") == Status.PASS)

        stale = assess_readiness(_gates(), evidence=_evidence("b" * 40), data_sources=sources)
        require("stale commit blocks", not stale.real_shadow_pilot_go and _status(stale, "sanitized_replay") == Status.NOT_VERIFIED)
        replay_failed = assess_readiness(_gates(), evidence=_evidence(mismatches=1), data_sources=sources)
        require("critical replay mismatch blocks", not replay_failed.real_shadow_pilot_go and _status(replay_failed, "sanitized_replay") == Status.BLOCKED)

        provenance_override = assess_readiness(_gates(), evidence=_evidence())
        require("attestation cannot override provenance", not provenance_override.real_shadow_pilot_go and _status(provenance_override, "customer_memory") == Status.BLOCKED)
        technical_override = assess_readiness(_gates(canonical=Status.FAIL), evidence=_evidence(), data_sources=sources)
        require("attestation cannot override canonical failure", not technical_override.real_shadow_pilot_go and _status(technical_override, "canonical_regression") == Status.FAIL)
        require("disabled outbound non-blocking", _status(controlled, "supplier_outbound") == Status.EXPECTED_DISABLED and "supplier_outbound" not in controlled.blocking_check_ids)
        outbound = assess_readiness(_gates(), evidence=_evidence(), data_sources=sources, supplier_outbound_enabled=True)
        require("enabled outbound blocks", not outbound.real_shadow_pilot_go and _status(outbound, "supplier_outbound") == Status.BLOCKED)
        dirty = assess_readiness(_gates(clean=False), evidence=_evidence(), data_sources=sources)
        require("dirty worktree blocks", not dirty.real_shadow_pilot_go and _status(dirty, "clean_worktree") == Status.BLOCKED)

        skipped = collect_technical_gates(run_gates=False)
        skipped_result = assess_readiness(
            skipped,
            evidence=_evidence(),
            data_sources=sources,
        )
        require(
            "no-run gates stay NOT_RUN and block GO",
            skipped.runtime_preflight == Status.NOT_RUN
            and skipped.canonical_regression == Status.NOT_RUN
            and skipped.synthetic_rehearsal == Status.NOT_RUN
            and not skipped_result.real_shadow_pilot_go,
        )

        supplier_policy, customer_policy = collect_outbound_policy()
        require(
            "live pilot outbound policy disabled",
            supplier_policy is False and customer_policy is False,
        )

        evidence_path = root / "readiness.json"
        evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")
        require("valid external evidence loads", load_external_evidence(evidence_path)["schema_version"] == 1)
        malformed = root / "malformed.json"
        malformed.write_text("[]", encoding="utf-8")
        try:
            load_external_evidence(malformed)
        except EvidenceValidationError:
            malformed_rejected = True
        else:
            malformed_rejected = False
        require("malformed evidence rejected safely", malformed_rejected)
        inside = Path(".pilot-readiness-regression-evidence.json")
        try:
            inside.write_text(json.dumps(_evidence()), encoding="utf-8")
            try:
                load_external_evidence(inside)
            except EvidenceValidationError:
                inside_rejected = True
            else:
                inside_rejected = False
        finally:
            inside.unlink(missing_ok=True)
        require("repository evidence path rejected", inside_rejected)
        sensitive = _evidence()
        sensitive["organization_approval"]["token"] = "do-not-print-this-secret"
        sensitive_path = root / "sensitive.json"
        sensitive_path.write_text(json.dumps(sensitive), encoding="utf-8")
        try:
            load_external_evidence(sensitive_path)
        except EvidenceValidationError:
            sensitive_rejected = True
        else:
            sensitive_rejected = False
        require("forbidden sensitive keys rejected", sensitive_rejected)

        output = io.StringIO()
        print_result(controlled, output)
        require("safe output omits attestation values", "authorized-role-01" not in output.getvalue() and HEAD not in output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            require("CLI --no-run-gates exits one", main(["--no-run-gates"]) == 1)

        external_pack_root = root / "external-pilot-pack"
        external_data_dir = external_pack_root / "data"
        external_data_dir.mkdir(parents=True)
        _write_synthetic_sources(external_data_dir)
        external_env = {
            "MINAI_PILOT_DATA_DIR": str(
                external_pack_root.resolve()
            )
        }
        with patch.dict(os.environ, external_env, clear=False):
            with contextlib.redirect_stdout(io.StringIO()):
                external_cli_result = main(["--no-run-gates"])
        require(
            "CLI resolves external operational data pack",
            external_cli_result == 1,
        )
        with contextlib.redirect_stderr(io.StringIO()):
            require("invalid evidence exits two", main(["--evidence", str(malformed), "--no-run-gates"]) == 2)

        network_attempts: list[object] = []
        def reject_network(*args, **kwargs):
            network_attempts.append((args, kwargs))
            raise AssertionError("network attempted")
        with patch.object(socket, "create_connection", reject_network), patch.object(socket.socket, "connect", reject_network):
            isolated = assess_readiness(_gates(), evidence=_evidence(), data_sources=sources)
        require("no network OpenAI or outbound", isolated.real_shadow_pilot_go and not network_attempts)

    after_data = {p.relative_to(data_root): p.read_bytes() for p in data_root.rglob("*") if p.is_file()}
    require("no repository data mutation", before_data == after_data)
    require("no SQLite artifacts", before_artifacts == _artifacts())
    require("replay harness distinct from replay evidence", _status(default, "replay_harness") == Status.PASS and _status(default, "sanitized_replay") == Status.NOT_RUN)
    require("technical injection avoids recursive gate execution", controlled.real_shadow_pilot_go)

    return {"name": "Pilot readiness assessment", "passed": not failures, "failures": failures, "checks": checks}


if __name__ == "__main__":
    result = evaluate_pilot_readiness_regressions()
    for name, passed in result["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"\nPilot readiness regressions: {'PASS' if result['passed'] else 'FAIL'}")
    raise SystemExit(0 if result["passed"] else 1)
