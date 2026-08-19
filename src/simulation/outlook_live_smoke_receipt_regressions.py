"""Offline regressions for P1-21 live Outlook smoke evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from src.simulation.outlook_live_smoke_receipt import (
    OutlookLiveSmokeReceiptError,
    build_outlook_live_smoke_receipt,
    evaluate_outlook_live_smoke_pull,
    load_outlook_live_smoke_receipt,
    write_outlook_live_smoke_receipt,
)
from src.simulation.replay_receipt import (
    ReleaseIdentity,
)


HEAD = "b" * 40

CUSTOMER_ID = "graph-customer-secret-id"
SUPPLIER_ID = "graph-supplier-secret-id"
WRONG_ID = "graph-wrong-secret-id"
ATTACHMENT_ID = "graph-attachment-secret-id"

MAILBOX = "real-mailbox@example.com"
TOKEN = "live-secret-token-value"


def _pull() -> dict:
    return {
        "provider": "microsoft_graph",
        "mailbox_id": MAILBOX,
        "requested_limit": 10,
        "fetched_message_count": 4,
        "handled_message_count": 4,
        "proposal_count": 1,
        "supplier_response_count": 1,
        "manual_review_count": 2,
        "pull_status": "complete",
        "mailbox_write_performed": False,
        "automated_send_performed": False,
        "debug_token": TOKEN,
        "results": [
            {
                "external_message_id": CUSTOMER_ID,
                "result_type": (
                    "extraction_confirmation_required"
                ),
                "ingestion_status": "created",
                "inbound_route": "customer",
                "proposal_id": "proposal-live-smoke",
            },
            {
                "external_message_id": SUPPLIER_ID,
                "result_type": (
                    "supplier_response_ingestion"
                ),
                "ingestion_status": (
                    "response_attached"
                ),
                "reason_code": (
                    "response_attached"
                ),
                "inbound_route": "supplier",
                "rfq_id": "rfq-live-smoke",
                "correlation_method": (
                    "explicit_reference"
                ),
            },
            {
                "external_message_id": WRONG_ID,
                "result_type": (
                    "inbound_sender_verification_required"
                ),
                "ingestion_status": "blocked",
                "reason_code": (
                    "sender_not_in_verified_inbound_scope"
                ),
                "inbound_route": "manual_review",
            },
            {
                "external_message_id": ATTACHMENT_ID,
                "result_type": (
                    "inbound_mail_manual_review_required"
                ),
                "ingestion_status": "blocked",
                "reason_code": (
                    "outlook_attachments_not_supported"
                ),
                "inbound_route": "manual_review",
            },
        ],
    }


def evaluate_outlook_live_smoke_receipt_regressions():
    failures = []
    passes = []

    def check(condition, label):
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    pull = _pull()

    evaluation = (
        evaluate_outlook_live_smoke_pull(
            pull,
            trusted_customer_message_id=(
                CUSTOMER_ID
            ),
            known_supplier_message_id=(
                SUPPLIER_ID
            ),
            wrong_supplier_message_id=(
                WRONG_ID
            ),
            attachment_message_id=(
                ATTACHMENT_ID
            ),
        )
    )

    check(
        evaluation.result == "pass"
        and all(
            value == "pass"
            for value
            in evaluation.scenarios.values()
        )
        and not evaluation.failed_scenarios,
        "four controlled live Outlook scenarios reconcile",
    )

    identity = ReleaseIdentity(
        HEAD,
        True,
    )

    confirmations = {
        "live_tenant_approved": True,
        "openai_data_use_approved": True,
        "four_test_messages_prepared": True,
        "no_autonomous_outbound": True,
    }

    receipt = build_outlook_live_smoke_receipt(
        evaluation,
        release_identity=identity,
        manifest_sha256=("c" * 64),
        confirmations=confirmations,
    )

    serialized = json.dumps(
        receipt.model_dump(mode="json"),
        sort_keys=True,
    )

    check(
        receipt.result == "pass"
        and receipt.pilot_commit_sha == HEAD
        and receipt.manifest_sha256 == ("c" * 64)
        and receipt.pull_status == "complete"
        and all(receipt.confirmations.values())
        and receipt.mailbox_write_performed is False
        and receipt.automated_send_performed is False,
        "receipt binds commit and no-outbound invariants",
    )

    sensitive_values = (
        MAILBOX,
        TOKEN,
        CUSTOMER_ID,
        SUPPLIER_ID,
        WRONG_ID,
        ATTACHMENT_ID,
        "proposal-live-smoke",
        "rfq-live-smoke",
    )

    check(
        all(
            value not in serialized
            for value in sensitive_values
        )
        and "mailbox_id" not in serialized
        and "external_message_id" not in serialized
        and "proposal_id" not in serialized
        and "rfq_id" not in serialized
        and "body_text" not in serialized
        and "sender_address" not in serialized,
        "receipt omits mailbox PII token and message identifiers",
    )

    with TemporaryDirectory() as temporary:
        destination = (
            Path(temporary)
            / "outlook-live-smoke-receipt.json"
        )

        written = (
            write_outlook_live_smoke_receipt(
                destination,
                receipt,
            )
        )

        loaded = (
            load_outlook_live_smoke_receipt(
                written
            )
        )

        check(
            loaded == receipt,
            "live Outlook smoke receipt round trip",
        )

        if os.name == "posix":
            check(
                (
                    written.stat().st_mode
                    & 0o777
                )
                == 0o600,
                "live smoke receipt is owner-only",
            )

        try:
            write_outlook_live_smoke_receipt(
                destination,
                receipt,
            )
        except OutlookLiveSmokeReceiptError as exc:
            overwrite_blocked = (
                exc.code
                == "outlook_smoke_receipt_already_exists"
            )
        else:
            overwrite_blocked = False

        check(
            overwrite_blocked,
            "live smoke receipt is create-only",
        )

    bad = _pull()

    bad["results"][2][
        "reason_code"
    ] = "unexpected_reason"

    failed_evaluation = (
        evaluate_outlook_live_smoke_pull(
            bad,
            trusted_customer_message_id=(
                CUSTOMER_ID
            ),
            known_supplier_message_id=(
                SUPPLIER_ID
            ),
            wrong_supplier_message_id=(
                WRONG_ID
            ),
            attachment_message_id=(
                ATTACHMENT_ID
            ),
        )
    )

    check(
        failed_evaluation.result == "fail"
        and failed_evaluation.scenarios[
            "wrong_supplier_sender"
        ]
        == "fail",
        "wrong negative routing cannot produce passing evidence",
    )

    duplicate_pull = _pull()

    duplicate_pull["results"][1] = {
        "external_message_id": SUPPLIER_ID,
        "result_type": (
            "supplier_response_duplicate"
        ),
        "ingestion_status": (
            "duplicate_response"
        ),
        "reason_code": (
            "supplier_message_already_ingested"
        ),
        "inbound_route": "supplier",
    }

    duplicate_evaluation = (
        evaluate_outlook_live_smoke_pull(
            duplicate_pull,
            trusted_customer_message_id=(
                CUSTOMER_ID
            ),
            known_supplier_message_id=(
                SUPPLIER_ID
            ),
            wrong_supplier_message_id=(
                WRONG_ID
            ),
            attachment_message_id=(
                ATTACHMENT_ID
            ),
        )
    )

    check(
        duplicate_evaluation.scenarios[
            "known_supplier_reply"
        ]
        == "pass",
        "exact supplier replay preserves live evidence",
    )

    try:
        build_outlook_live_smoke_receipt(
            evaluation,
            release_identity=ReleaseIdentity(
                HEAD,
                False,
            ),
            manifest_sha256=("c" * 64),
            confirmations=confirmations,
        )
    except OutlookLiveSmokeReceiptError as exc:
        dirty_blocked = (
            exc.code
            == (
                "outlook_smoke_receipt_"
                "requires_clean_release"
            )
        )
    else:
        dirty_blocked = False

    check(
        dirty_blocked,
        "dirty worktree cannot produce live receipt",
    )

    inside = (
        Path.cwd()
        / ".outlook-live-smoke-forbidden.json"
    )

    try:
        write_outlook_live_smoke_receipt(
            inside,
            receipt,
        )
    except OutlookLiveSmokeReceiptError as exc:
        inside_blocked = (
            exc.code
            == "outlook_smoke_receipt_inside_repository"
        )
    else:
        inside_blocked = False
        inside.unlink(missing_ok=True)

    check(
        inside_blocked,
        "repository receipt destination is rejected",
    )

    return {
        "name": (
            "Live Outlook smoke evidence contract"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_outlook_live_smoke_receipt_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for label in result["failures"]:
        print(f"FAIL {label}")

    print(
        "\nLive Outlook smoke evidence "
        + (
            "regressions: PASS"
            if result["passed"]
            else "regressions: FAIL"
        )
    )

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
