"""Deterministic regressions for sanitized replay evidence receipts."""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from src.simulation.pilot_rehearsal import _write_synthetic_sources
from src.simulation.replay_receipt import (
    CUSTOMER_IDENTITY_MODE,
    ReleaseIdentity,
    ReplayReceiptError,
    build_replay_receipt,
    load_replay_receipt,
    receipt_readiness_summary,
    write_replay_receipt,
)
from src.simulation.sanitized_replay import ReplayAggregateResult


HEAD = "a" * 40


def _result(*, safety_mismatches: int = 0) -> ReplayAggregateResult:
    counts = Counter(
        {
            "correct": 8,
            "incorrect": 1,
            "missing": 1,
            "unexpected_inference": 1,
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


def evaluate_replay_receipt_regressions() -> dict:
    failures: list[str] = []
    checks: dict[str, bool] = {}

    def require(name: str, condition: bool) -> None:
        checks[name] = bool(condition)
        if not condition:
            failures.append(name)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        sources = _write_synthetic_sources(root)
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
        )
        require(
            "receipt binds exact commit",
            receipt.pilot_commit_sha == HEAD,
        )
        require(
            "receipt binds replay input",
            len(receipt.replay_input_sha256) == 64,
        )
        require(
            "receipt binds verified operational datasets",
            set(receipt.operational_dataset_sha256)
            == {"customer_memory", "supplier_capabilities"}
            and all(
                len(value) == 64
                for value
                in receipt.operational_dataset_sha256.values()
            ),
        )
        require(
            "receipt exposes pseudonymous identity limitation",
            receipt.customer_identity_mode
            == CUSTOMER_IDENTITY_MODE,
        )
        require(
            "receipt preserves safe aggregate metrics",
            receipt.metrics.extraction_fields_evaluated == 10
            and receipt.metrics.correct_fields == 8
            and receipt.metrics.incorrect_fields == 1
            and receipt.metrics.missing_fields == 1
            and receipt.metrics.unexpected_inference_count == 1,
        )
        destination = root / "replay-receipt.json"
        written = write_replay_receipt(destination, receipt)
        loaded = load_replay_receipt(written)
        require(
            "receipt round trip",
            loaded == receipt,
        )
        if os.name == "posix":
            require(
                "receipt file is restrictive",
                (written.stat().st_mode & 0o777) == 0o600,
            )

        try:
            write_replay_receipt(destination, receipt)
        except ReplayReceiptError as exc:
            overwrite_blocked = (
                exc.code == "replay_receipt_already_exists"
            )
        else:
            overwrite_blocked = False
        require(
            "verified replay receipt is immutable",
            overwrite_blocked,
        )

        dirty = ReleaseIdentity(HEAD, False)
        try:
            build_replay_receipt(
                _result(),
                input_path=replay_input,
                operational_data_sources=sources,
                release_identity=dirty,
            )
        except ReplayReceiptError as exc:
            dirty_blocked = (
                exc.code
                == "replay_receipt_requires_clean_worktree"
            )
        else:
            dirty_blocked = False
        require(
            "dirty worktree cannot produce receipt",
            dirty_blocked,
        )

        failed_receipt = build_replay_receipt(
            _result(safety_mismatches=1),
            input_path=replay_input,
            operational_data_sources=sources,
            release_identity=identity,
        )
        require(
            "failed safety replay remains failed evidence",
            failed_receipt.result == "fail"
            and failed_receipt.safety_critical_mismatches == 1,
        )

        readiness = receipt_readiness_summary(receipt)
        require(
            "readiness summary carries only required replay attestation",
            set(readiness)
            == {
                "completed",
                "result",
                "completed_at",
                "case_count",
                "safety_critical_mismatches",
            }
            and readiness["completed"] is True
            and readiness["result"] == "pass",
        )

        safe_json = json.dumps(
            receipt.model_dump(mode="json"),
            sort_keys=True,
        )
        require(
            "receipt omits replay/customer values",
            "body_text" not in safe_json
            and "sender_address" not in safe_json
            and "customer.invalid" not in safe_json
            and "case_id" not in safe_json,
        )

        inside = Path.cwd() / ".replay-receipt-forbidden.json"
        try:
            write_replay_receipt(inside, receipt)
        except ReplayReceiptError as exc:
            inside_blocked = (
                exc.code == "receipt_path_inside_repository"
            )
        else:
            inside_blocked = False
            inside.unlink(missing_ok=True)
        require(
            "repository receipt path rejected",
            inside_blocked,
        )

        malformed = root / "malformed-receipt.json"
        malformed.write_text("{}", encoding="utf-8")
        try:
            load_replay_receipt(malformed)
        except ReplayReceiptError:
            malformed_blocked = True
        else:
            malformed_blocked = False
        require(
            "malformed receipt rejected safely",
            malformed_blocked,
        )

    return {
        "passed": not failures,
        "failures": failures,
        "checks": checks,
    }


def main() -> int:
    result = evaluate_replay_receipt_regressions()
    for name, passed in result["checks"].items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(
        "\nReplay receipt regressions: "
        + ("PASS" if result["passed"] else "FAIL")
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
