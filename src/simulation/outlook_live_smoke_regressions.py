from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import src.outlook_live_smoke as smoke_module

from src.outlook_live_smoke import (
    OutlookLiveSmokeRunnerError,
    load_manifest,
    prepare_live_smoke_manifest,
    run_live_smoke,
)
from src.simulation.replay_receipt import (
    ReleaseIdentity,
)


HEAD = "d" * 40

CUSTOMER_ID = "customer-sensitive-id"
SUPPLIER_ID = "supplier-sensitive-id"
WRONG_ID = "wrong-sensitive-id"
ATTACHMENT_ID = "attachment-sensitive-id"

CONFIRMATIONS = {
    "live_tenant_approved": True,
    "openai_data_use_approved": True,
    "four_test_messages_prepared": True,
    "no_autonomous_outbound": True,
}


def _first_pull():
    return {
        "provider": "microsoft_graph",
        "mailbox_id": (
            "pilot-mailbox@example.invalid"
        ),
        "fetched_message_count": 4,
        "handled_message_count": 4,
        "pull_status": "complete",
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "results": [
            {
                "external_message_id": CUSTOMER_ID,
                "inbound_route": "customer",
                "ingestion_status": "created",
                "proposal_id": "proposal-sensitive",
            },
            {
                "external_message_id": SUPPLIER_ID,
                "inbound_route": "supplier",
                "ingestion_status": (
                    "response_attached"
                ),
                "rfq_id": "rfq-sensitive",
            },
            {
                "external_message_id": WRONG_ID,
                "inbound_route": "manual_review",
                "ingestion_status": "blocked",
                "reason_code": (
                    "sender_not_in_verified_"
                    "inbound_scope"
                ),
            },
            {
                "external_message_id": ATTACHMENT_ID,
                "inbound_route": "manual_review",
                "ingestion_status": "blocked",
                "reason_code": (
                    "outlook_attachments_"
                    "not_supported"
                ),
            },
        ],
    }


def _second_pull():
    result = _first_pull()

    result["results"][0][
        "ingestion_status"
    ] = "duplicate_existing_proposal"

    result["results"][1] = {
        "external_message_id": SUPPLIER_ID,
        "inbound_route": "supplier",
        "ingestion_status": (
            "duplicate_response"
        ),
        "reason_code": (
            "supplier_message_already_ingested"
        ),
    }

    return result


class _Client:
    def __init__(
        self,
        pulls,
        *,
        runtime_sha=HEAD,
    ):
        self.pulls = list(pulls)
        self.runtime_sha = runtime_sha
        self.pull_calls = 0
        self.status_calls = 0

    def status(self):
        self.status_calls += 1
        return {
            "health": {"status": "ok"},
            "authentication": "ok",
        }

    def runtime_release(self):
        return {
            "available": True,
            "commit_sha": self.runtime_sha,
            "clean_worktree": True,
        }

    def pull_outlook(self, *, limit):
        self.pull_calls += 1

        if not self.pulls:
            raise AssertionError(
                "unexpected pull"
            )

        return self.pulls.pop(0)


def evaluate_outlook_live_smoke_regressions():
    failures = []
    passes = []

    def check(condition, label):
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    with TemporaryDirectory() as temp:
        root = Path(temp)
        manifest_path = (
            root / "manifest.json"
        )
        receipt_path = (
            root / "receipt.json"
        )

        client = _Client(
            [
                _first_pull(),
                _second_pull(),
            ]
        )

        identity = ReleaseIdentity(
            HEAD,
            True,
        )

        manifest = (
            prepare_live_smoke_manifest(
                client=client,
                release_identity=identity,
                manifest_path=(
                    manifest_path
                ),
                pull_limit=4,
                confirmations=CONFIRMATIONS,
            )
        )

        check(
            manifest.pilot_commit_sha
            == HEAD
            and set(
                manifest.message_ids
            )
            == {
                "trusted_customer",
                "known_supplier_reply",
                "wrong_supplier_sender",
                "attachment_manual_review",
            }
            and client.pull_calls == 1,
            "first live pass prepares exact four-scenario manifest",
        )

        loaded = load_manifest(
            manifest_path
        )

        check(
            loaded == manifest,
            "private live smoke manifest round trip",
        )

        if os.name == "posix":
            check(
                (
                    manifest_path.stat().st_mode
                    & 0o777
                )
                == 0o600,
                "live smoke manifest is owner-only",
            )

        receipt = run_live_smoke(
            client=client,
            release_identity=identity,
            manifest_path=manifest_path,
            receipt_path=receipt_path,
            confirmations=CONFIRMATIONS,
        )

        check(
            receipt.result == "pass"
            and all(
                status == "pass"
                for status
                in receipt.scenarios.values()
            )
            and client.pull_calls == 2,
            "second live pass proves deterministic idempotent routing",
        )

        serialized = json.dumps(
            receipt.model_dump(mode="json"),
            sort_keys=True,
        )

        check(
            all(
                sensitive not in serialized
                for sensitive in (
                    CUSTOMER_ID,
                    SUPPLIER_ID,
                    WRONG_ID,
                    ATTACHMENT_ID,
                    "proposal-sensitive",
                    "rfq-sensitive",
                    "pilot-mailbox@example.invalid",
                )
            ),
            "live receipt excludes manifest identifiers and mailbox values",
        )

        mismatch = _Client(
            [_second_pull()],
            runtime_sha=("e" * 40),
        )

        try:
            run_live_smoke(
                client=mismatch,
                release_identity=identity,
                manifest_path=(
                    manifest_path
                ),
                receipt_path=(
                    root
                    / "mismatch-receipt.json"
                ),
                confirmations=CONFIRMATIONS,
            )
        except OutlookLiveSmokeRunnerError as exc:
            blocked = (
                exc.code
                == (
                    "outlook_smoke_runtime_"
                    "commit_mismatch"
                )
            )
        else:
            blocked = False

        check(
            blocked
            and mismatch.pull_calls == 0,
            "runtime commit mismatch blocks before live pull",
        )

        missing_confirmation = dict(
            CONFIRMATIONS
        )
        missing_confirmation[
            "live_tenant_approved"
        ] = False

        blocked_client = _Client(
            [_first_pull()]
        )

        try:
            prepare_live_smoke_manifest(
                client=blocked_client,
                release_identity=identity,
                manifest_path=(
                    root
                    / "blocked-manifest.json"
                ),
                pull_limit=4,
                confirmations=(
                    missing_confirmation
                ),
            )
        except OutlookLiveSmokeRunnerError as exc:
            confirmations_blocked = (
                exc.code
                == (
                    "outlook_smoke_explicit_"
                    "confirmation_required"
                )
            )
        else:
            confirmations_blocked = False

        check(
            confirmations_blocked
            and blocked_client.pull_calls == 0,
            "missing human confirmation blocks before live pull",
        )

    with TemporaryDirectory() as temp:
        failure_path = (
            Path(temp)
            / "filesystem-failure.json"
        )

        failure_manifest = (
            smoke_module
            .OutlookLiveSmokeManifest(
                pilot_commit_sha=HEAD,
                prepared_at=datetime.now(
                    timezone.utc
                ),
                pull_limit=4,
                message_ids={
                    "trusted_customer": CUSTOMER_ID,
                    "known_supplier_reply": SUPPLIER_ID,
                    "wrong_supplier_sender": WRONG_ID,
                    "attachment_manual_review": ATTACHMENT_ID,
                },
            )
        )

        with patch.object(
            smoke_module.os,
            "link",
            side_effect=OSError(
                "sensitive filesystem detail"
            ),
        ):
            try:
                smoke_module.write_manifest(
                    failure_path,
                    failure_manifest,
                )
            except OutlookLiveSmokeRunnerError as exc:
                safe_filesystem_failure = (
                    exc.code
                    == (
                        "outlook_smoke_manifest_"
                        "write_failed"
                    )
                    and (
                        "sensitive filesystem detail"
                        not in str(exc)
                    )
                )
            else:
                safe_filesystem_failure = False

        check(
            safe_filesystem_failure,
            "manifest filesystem failures are safely summarized",
        )

    return {
        "name": (
            "Controlled live Outlook smoke runner"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_outlook_live_smoke_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for label in result["failures"]:
        print(f"FAIL {label}")

    print(
        "\nControlled live Outlook smoke "
        + (
            "regressions: PASS"
            if result["passed"]
            else "regressions: FAIL"
        )
    )

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
