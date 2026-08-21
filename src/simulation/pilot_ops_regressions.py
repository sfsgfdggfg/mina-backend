"""Focused regressions for the guided pilot operations CLI."""

from __future__ import annotations

import io
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from src.pilot_ops import (
    PilotOpsError,
    _guided_verify,
    _prepare,
    _run,
    _status,
)
from src.simulation.replay_receipt import ReleaseIdentity


def _pack(*, verified: bool) -> dict:
    return {
        "valid": True,
        "verified": verified,
        "errors": [],
        "warnings": ["synthetic non-blocking warning"],
        "active_customer_count": 2,
        "trusted_customer_count": 2,
        "active_supplier_count": 3,
        "contactable_supplier_count": 3,
    }


class _FakeClient:
    def status(self):
        return {"authentication": "ok"}

    def runtime_release(self):
        return {
            "available": True,
            "clean_worktree": True,
            "commit_sha": "a" * 40,
        }

    def list_rfqs(self):
        return {
            "supplier_rfqs": [
                {
                    "rfq_id": "synthetic-rfq",
                    "status": "awaiting_response",
                }
            ]
        }


def _release():
    return ReleaseIdentity(
        commit_sha="a" * 40,
        clean_worktree=True,
    )


def _auth_env(root: Path) -> dict[str, str]:
    cache = root / "token-cache.json"
    cache.write_text("{}", encoding="utf-8")
    if os.name == "posix":
        cache.chmod(0o600)

    pack = root / "smoke-pack"
    pack.mkdir()

    return {
        "MINAI_OUTLOOK_TENANT_ID": "9188040d-6c67-4c5b-b112-36a304b66dad",
        "MINAI_OUTLOOK_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
        "MINAI_OUTLOOK_MAILBOX_ID": "synthetic@example.invalid",
        "MINAI_OUTLOOK_TOKEN_CACHE_PATH": str(cache),
        "MINAI_OUTLOOK_SMOKE_PACK_DIR": str(pack),
        "MINAI_PILOT_DATA_DIR": str(pack),
        "MINAI_PILOT_TOKEN": "x" * 40,
        "MINAI_PILOT_BASE_URL": "http://127.0.0.1:8000",
    }


def evaluate_pilot_ops_regressions() -> dict:
    failures: list[str] = []

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        env = _auth_env(root)

        output = io.StringIO()
        with redirect_stdout(output):
            rc = _status(
                env,
                token_func=lambda config: "synthetic-token",
                status_func=lambda path: _pack(verified=False),
                client_factory=lambda environ: _FakeClient(),
                release_func=_release,
            )

        text = output.getvalue()
        if (
            rc != 0
            or "outlook-smoke verify" not in text
            or env["MINAI_PILOT_TOKEN"] in text
            or "synthetic-token" in text
        ):
            failures.append(
                "status did not route to human verification without leaking secrets"
            )

        calls: list[dict] = []

        def verify_func(path, **kwargs):
            calls.append(
                {
                    "path": path,
                    **kwargs,
                }
            )
            return _pack(verified=True)

        answers = iter(
            [
                "Synthetic Reviewer",
                "REVIEWED",
            ]
        )
        output = io.StringIO()
        with redirect_stdout(output):
            rc = _guided_verify(
                env,
                status_func=lambda path: _pack(verified=False),
                verify_func=verify_func,
                input_func=lambda prompt: next(answers),
            )

        if (
            rc != 0
            or len(calls) != 1
            or calls[0].get("verified_by") != "Synthetic Reviewer"
            or calls[0].get("confirm_final_reviewed") is not True
        ):
            failures.append(
                "guided verification did not preserve explicit human confirmation"
            )

        cancelled_calls: list[dict] = []
        answers = iter(
            [
                "Synthetic Reviewer",
                "no",
            ]
        )
        try:
            _guided_verify(
                env,
                status_func=lambda path: _pack(verified=False),
                verify_func=lambda *args, **kwargs: cancelled_calls.append(kwargs),
                input_func=lambda prompt: next(answers),
            )
        except PilotOpsError:
            pass
        else:
            failures.append(
                "guided verification accepted a non-exact human confirmation"
            )

        if cancelled_calls:
            failures.append(
                "cancelled human verification still mutated the data pack"
            )

        evidence = root / "evidence"
        env["MINAI_OUTLOOK_SMOKE_EVIDENCE_DIR"] = str(evidence)

        live_calls: list[list[str]] = []

        def live_smoke_main(args):
            live_calls.append(list(args))
            manifest = Path(
                args[
                    args.index("--manifest")
                    + 1
                ]
            )
            if args[0] == "prepare":
                manifest.write_text(
                    "{}",
                    encoding="utf-8",
                )
                if os.name == "posix":
                    manifest.chmod(0o600)
            return 0

        answers = iter(["YES", "YES", "YES", "YES"])
        output = io.StringIO()
        with redirect_stdout(output):
            rc = _prepare(
                env,
                status_func=lambda path: _pack(verified=True),
                live_smoke_main=live_smoke_main,
                input_func=lambda prompt: next(answers),
            )

        if rc != 0 or len(live_calls) != 1:
            failures.append(
                "guided prepare did not invoke the existing live smoke runner once"
            )
        else:
            args = live_calls[0]
            expected_flags = {
                "--confirm-live-tenant-approved",
                "--confirm-openai-data-use-approved",
                "--confirm-four-test-messages-prepared",
                "--confirm-no-autonomous-outbound",
            }
            if not expected_flags.issubset(set(args)):
                failures.append(
                    "guided prepare dropped an explicit live smoke confirmation"
                )

        run_answers = iter(["YES", "YES", "YES", "YES"])
        output = io.StringIO()
        with redirect_stdout(output):
            rc = _run(
                env,
                status_func=lambda path: _pack(verified=True),
                live_smoke_main=live_smoke_main,
                input_func=lambda prompt: next(run_answers),
            )

        if (
            rc != 0
            or len(live_calls) != 2
            or live_calls[-1][0] != "run"
        ):
            failures.append(
                "guided run did not reuse the prepared evidence session"
            )

        mismatched = dict(env)
        wrong_pack = root / "wrong-pack"
        wrong_pack.mkdir()
        mismatched["MINAI_PILOT_DATA_DIR"] = str(wrong_pack)

        called = []
        try:
            _prepare(
                mismatched,
                status_func=lambda path: _pack(verified=True),
                live_smoke_main=lambda args: called.append(args) or 0,
                input_func=lambda prompt: "YES",
            )
        except PilotOpsError:
            pass
        else:
            failures.append(
                "prepare accepted a runtime data directory different from the verified smoke pack"
            )

        if called:
            failures.append(
                "prepare called the live smoke runner after a pack/runtime mismatch"
            )

    return {
        "name": "Guided pilot operations CLI",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    print(evaluate_pilot_ops_regressions())
