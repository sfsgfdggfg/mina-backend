"""Deterministic regressions for guided pilot readiness evidence."""

from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.data_provenance import calculate_dataset_sha256
from src.pilot_readiness import load_external_evidence
from src.pilot_readiness_evidence import (
    ReadinessEvidenceBuilderError,
    build_readiness_evidence,
    collect_attestations,
    main as evidence_main,
    validate_receipt_context,
    write_readiness_evidence,
)
from src.simulation.pilot_rehearsal import _write_synthetic_sources
from src.simulation.replay_receipt import (
    ReleaseIdentity,
    build_replay_receipt,
    write_replay_receipt,
)
from src.simulation.sanitized_replay import ReplayAggregateResult


HEAD = "a" * 40
NOW = datetime(2026, 8, 18, 9, 0, tzinfo=timezone.utc)


def _result(*, safety_mismatches: int = 0) -> ReplayAggregateResult:
    counts = Counter(
        {
            "correct": 8,
            "incorrect": 1,
            "missing": 1,
            "unexpected_inference": 0,
        }
    )
    return ReplayAggregateResult(
        cases=[object(), object(), object()],
        outcome_counts=counts,
        grouped_mismatches=Counter(),
        ground_truth_fields=10,
        correct_fields=8,
        clarification_correct=2,
        clarification_evaluated=3,
        scope_correct=3,
        scope_evaluated=3,
        equipment_correct=2,
        equipment_evaluated=2,
        supplier_progression_correct=3,
        supplier_progression_evaluated=3,
        safety_critical_mismatches=safety_mismatches,
    )


def _answers() -> list[str]:
    result: list[str] = []
    for index in range(7):
        result.extend(("CONFIRM", f"authorized-role-{index + 1:02d}"))
    return result


def _approvals() -> dict[str, dict[str, object]]:
    answers = iter(_answers())
    return collect_attestations(
        input_fn=lambda _prompt: next(answers),
        now=lambda: NOW,
    )


def _make_distinct_verified_pack(root: Path):
    sources = _write_synthetic_sources(root)
    customer_rows = json.loads(
        sources.customer_memory_path.read_text(encoding="utf-8")
    )
    customer_rows[0]["operational_notes"] = [
        "Distinct verified pack B regression fixture."
    ]
    sources.customer_memory_path.write_text(
        json.dumps(customer_rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    registry = json.loads(
        sources.provenance_registry_path.read_text(encoding="utf-8")
    )
    registry["datasets"]["customer_memory"]["verified_sha256"] = (
        calculate_dataset_sha256(sources.customer_memory_path)
    )
    sources.provenance_registry_path.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return sources


def evaluate_pilot_readiness_evidence_regressions() -> dict:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        pack_root = root / "pilot-pack"
        data_dir = pack_root / "data"
        data_dir.mkdir(parents=True)
        sources = _write_synthetic_sources(data_dir)

        replay_input = root / "sanitized-replay.jsonl"
        replay_input.write_text(
            '{"case_id":"synthetic-only"}\n',
            encoding="utf-8",
        )
        identity = ReleaseIdentity(HEAD, True)
        receipt = build_replay_receipt(
            _result(),
            input_path=replay_input,
            operational_data_sources=sources,
            release_identity=identity,
            completed_at=NOW,
        )

        approvals = _approvals()
        evidence = build_readiness_evidence(
            receipt=receipt,
            approvals=approvals,
            release_identity=identity,
            operational_data_sources=sources,
        )
        require(
            "valid receipt builds schema v2 evidence",
            evidence["schema_version"] == 2
            and evidence["pilot_commit_sha"] == HEAD
            and evidence["operational_dataset_sha256"]
            == receipt.operational_dataset_sha256
            and evidence["sanitized_replay"]["result"] == "pass"
            and evidence["sanitized_replay"]["case_count"] == 3,
        )

        destination = root / "readiness-evidence.json"
        written = write_readiness_evidence(destination, evidence)
        loaded = load_external_evidence(written)
        require(
            "generated evidence loads through readiness contract",
            loaded == evidence,
        )
        if os.name == "posix":
            require(
                "readiness evidence file is restrictive",
                (written.stat().st_mode & 0o777) == 0o600,
            )

        safe_json = json.dumps(evidence, sort_keys=True)
        require(
            "generated evidence omits replay and secret payload values",
            "body_text" not in safe_json
            and "sender_address" not in safe_json
            and "replay_input_sha256" not in safe_json
            and "token" not in safe_json
            and "password" not in safe_json,
        )

        try:
            write_readiness_evidence(destination, evidence)
        except ReadinessEvidenceBuilderError as exc:
            overwrite_blocked = (
                exc.code == "readiness_evidence_already_exists"
            )
        else:
            overwrite_blocked = False
        require(
            "readiness evidence is create only",
            overwrite_blocked,
        )

        inside = Path.cwd() / ".readiness-evidence-forbidden.json"
        try:
            write_readiness_evidence(inside, evidence)
        except ReadinessEvidenceBuilderError as exc:
            inside_blocked = (
                exc.code == "evidence_path_inside_repository"
            )
        else:
            inside_blocked = False
            inside.unlink(missing_ok=True)
        require(
            "repository readiness evidence path rejected",
            inside_blocked,
        )

        try:
            validate_receipt_context(
                receipt=receipt,
                release_identity=ReleaseIdentity("b" * 40, True),
                operational_data_sources=sources,
            )
        except ReadinessEvidenceBuilderError as exc:
            stale_blocked = exc.code == "replay_receipt_commit_mismatch"
        else:
            stale_blocked = False
        require(
            "stale receipt commit blocked",
            stale_blocked,
        )

        try:
            validate_receipt_context(
                receipt=receipt,
                release_identity=ReleaseIdentity(HEAD, False),
                operational_data_sources=sources,
            )
        except ReadinessEvidenceBuilderError as exc:
            dirty_blocked = (
                exc.code == "replay_receipt_requires_clean_worktree"
            )
        else:
            dirty_blocked = False
        require(
            "dirty worktree blocked",
            dirty_blocked,
        )

        pack_b_root = root / "pack-b"
        pack_b_root.mkdir()
        pack_b_sources = _make_distinct_verified_pack(pack_b_root)
        try:
            validate_receipt_context(
                receipt=receipt,
                release_identity=identity,
                operational_data_sources=pack_b_sources,
            )
        except ReadinessEvidenceBuilderError as exc:
            pack_mismatch_blocked = (
                exc.code
                == "replay_receipt_operational_data_mismatch"
            )
        else:
            pack_mismatch_blocked = False
        require(
            "receipt cannot be reused with different verified pack",
            pack_mismatch_blocked,
        )

        failed_receipt = build_replay_receipt(
            _result(safety_mismatches=1),
            input_path=replay_input,
            operational_data_sources=sources,
            release_identity=identity,
            completed_at=NOW,
        )
        try:
            validate_receipt_context(
                receipt=failed_receipt,
                release_identity=identity,
                operational_data_sources=sources,
            )
        except ReadinessEvidenceBuilderError as exc:
            failed_replay_blocked = (
                exc.code == "replay_receipt_not_go_eligible"
            )
        else:
            failed_replay_blocked = False
        require(
            "failed replay receipt blocked",
            failed_replay_blocked,
        )

        try:
            collect_attestations(input_fn=lambda _prompt: "NO")
        except ReadinessEvidenceBuilderError as exc:
            declined_blocked = (
                exc.code == "organization_approval_not_confirmed"
            )
        else:
            declined_blocked = False
        require(
            "declined attestation blocks evidence",
            declined_blocked,
        )

        receipt_path = root / "authorized-replay-receipt.json"
        write_replay_receipt(receipt_path, receipt)
        cli_output = root / "cli-readiness-evidence.json"
        answers = iter(_answers())
        stdout = io.StringIO()
        external_env = {
            "MINAI_PILOT_DATA_DIR": str(pack_root.resolve()),
        }
        with patch.dict(os.environ, external_env, clear=False):
            with patch(
                "socket.socket",
                side_effect=AssertionError("network forbidden"),
            ):
                with contextlib.redirect_stdout(stdout):
                    cli_result = evidence_main(
                        [
                            "build",
                            "--replay-receipt",
                            str(receipt_path),
                            "--output",
                            str(cli_output),
                        ],
                        input_fn=lambda _prompt: next(answers),
                        release_identity_func=lambda: identity,
                    )
        require(
            "guided CLI writes valid evidence without network",
            cli_result == 0
            and cli_output.is_file()
            and load_external_evidence(cli_output)["schema_version"] == 2,
        )
        require(
            "CLI states evidence does not grant approval",
            "does not grant approval" in stdout.getvalue(),
        )

    return {
        "name": "Guided pilot readiness evidence",
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }


def main() -> int:
    result = evaluate_pilot_readiness_evidence_regressions()
    for name, passed in result["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(
        "\nGuided readiness evidence regressions: "
        + ("PASS" if result["passed"] else "FAIL")
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
