"""Focused regressions for guided controlled supplier RFQ setup."""

from __future__ import annotations

import io
import json
import os
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from src.pilot_ops import (
    PilotOpsError,
    _setup_rfq,
    _smoke_pack_fingerprint,
)
from src.pilot_data_pack import resolve_pack_paths
from src.simulation.replay_receipt import ReleaseIdentity


class _Client:
    def __init__(self):
        self.rfqs = []
        self.record_calls = 0
        self.approve_calls = 0
        self.process_calls = 0
        self.process_payloads = []
        self.confirm_calls = 0
        self.resume_calls = 0

    def status(self):
        return {"authentication": "ok"}

    def runtime_release(self):
        return {
            "available": True,
            "clean_worktree": True,
            "commit_sha": "a" * 40,
        }

    def list_rfqs(self):
        return {"supplier_rfqs": [dict(item) for item in self.rfqs]}

    def process_email(self, **payload):
        self.process_calls += 1
        self.process_payloads.append(dict(payload))
        return {"proposal_id": "proposal-1"}

    def get_proposal(self, proposal_id):
        return {
            "proposal_id": proposal_id,
            "status": "pending_confirmation",
            "shipment": {
                "pickup": "Adana",
                "delivery": "Hamburg",
                "weight_kg": 20000,
                "commodity": "textile",
            },
        }

    def confirm_proposal(self, proposal_id, corrections):
        self.confirm_calls += 1
        return {"proposal_id": proposal_id, "status": "confirmed"}

    def resume_proposal(self, proposal_id):
        self.resume_calls += 1
        self.rfqs.append(
            {
                "rfq_id": "rfq-1",
                "supplier_name": "SMOKE Test Supplier",
                "recipient_email": "supplier@example.com",
                "subject": "Controlled RFQ MINAI-RFQ:rfq-1",
                "body": "Synthetic controlled RFQ body.",
                "status": "draft",
            }
        )
        return {"result_type": "supplier_rfq_created"}

    def get_rfq(self, rfq_id):
        return next(dict(item) for item in self.rfqs if item["rfq_id"] == rfq_id)

    def approve_rfq(self, rfq_id):
        self.approve_calls += 1
        for item in self.rfqs:
            if item["rfq_id"] == rfq_id:
                item["status"] = "approved"
                return dict(item)
        raise AssertionError("rfq missing")

    def record_rfq_manually_sent(self, rfq_id):
        self.record_calls += 1
        for item in self.rfqs:
            if item["rfq_id"] == rfq_id:
                item["status"] = "awaiting_response"
                return {
                    "supplier_rfq": dict(item),
                    "manual_sent_evidence": {"source": "manual_external_send"},
                }
        raise AssertionError("rfq missing")


def _release():
    return ReleaseIdentity("a" * 40, True)


def _pack(root: Path) -> dict:
    paths = resolve_pack_paths(root)
    paths.customer_memory.parent.mkdir(parents=True, exist_ok=True)

    paths.customer_memory.write_text(
        json.dumps(
            [
                {
                    "customer_name": "SMOKE Test Customer",
                    "active": True,
                    "trusted_sender_addresses": ["customer@example.com"],
                },
                {
                    "customer_name": "SMOKE Filler Customer",
                    "active": True,
                    "trusted_sender_addresses": ["unused@example.invalid"],
                },
            ]
        ),
        encoding="utf-8",
    )
    paths.supplier_capabilities.write_text(
        json.dumps(
            [
                {
                    "supplier_name": "SMOKE Test Supplier",
                    "active": True,
                    "role": "primary",
                    "contacts": [
                        {
                            "email": "supplier@example.com",
                            "active": True,
                            "is_primary": True,
                        }
                    ],
                },
                {
                    "supplier_name": "SMOKE Filler Supplier",
                    "active": True,
                    "role": "backup",
                    "contacts": [
                        {
                            "email": "unused@example.invalid",
                            "active": True,
                            "is_primary": True,
                        }
                    ],
                },
            ]
        ),
        encoding="utf-8",
    )
    return {
        "valid": True,
        "verified": True,
        "errors": [],
        "warnings": [],
    }


def evaluate_pilot_ops_rfq_regressions() -> dict:
    failures = []

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "pack"
        root.mkdir()
        status = _pack(root)
        cache = Path(temporary) / "token-cache.json"
        cache.write_text("{}", encoding="utf-8")
        if os.name == "posix":
            cache.chmod(0o600)

        env = {
            "MINAI_OUTLOOK_SMOKE_PACK_DIR": str(root),
            "MINAI_PILOT_DATA_DIR": str(root),
            "MINAI_PILOT_TOKEN": "secret-pilot-token",
            "MINAI_PILOT_BASE_URL": "http://127.0.0.1:8000",
            "MINAI_OUTLOOK_TENANT_ID": "9188040d-6c67-4c5b-b112-36a304b66dad",
            "MINAI_OUTLOOK_CLIENT_ID": "11111111-1111-1111-1111-111111111111",
            "MINAI_OUTLOOK_MAILBOX_ID": "pilot@example.com",
            "MINAI_OUTLOOK_TOKEN_CACHE_PATH": str(cache),
            "OPENAI_API_KEY": "secret-openai-key",
        }

        client = _Client()
        answers = iter(["CREATE", "REVIEWED", "APPROVE", "not-sent"])

        try:
            with redirect_stdout(io.StringIO()):
                _setup_rfq(
                    env,
                    status_func=lambda path: status,
                    client_factory=lambda environ: client,
                    release_func=_release,
                    input_func=lambda prompt: next(answers),
                )
        except PilotOpsError:
            pass
        else:
            failures.append("setup accepted non-exact manual SENT confirmation")

        if client.record_calls != 0:
            failures.append("setup fabricated manual-send evidence after cancelled send")

        expected_message_id = (
            "pilot-ops-rfq-setup-"
            + ("a" * 16)
            + "-"
            + _smoke_pack_fingerprint(root)[:16]
        )
        if (
            not client.process_payloads
            or client.process_payloads[0].get("external_message_id")
            != expected_message_id
        ):
            failures.append(
                "controlled RFQ setup dedup key did not include smoke-pack fingerprint"
            )

        if (
            client.process_calls != 1
            or client.confirm_calls != 1
            or client.resume_calls != 1
            or client.approve_calls != 1
        ):
            failures.append("setup did not automate the mechanical RFQ lifecycle")

        answers = iter(["SENT"])
        output = io.StringIO()
        with redirect_stdout(output):
            rc = _setup_rfq(
                env,
                status_func=lambda path: status,
                client_factory=lambda environ: client,
                release_func=_release,
                input_func=lambda prompt: next(answers),
            )

        text = output.getvalue()
        if rc != 0 or client.record_calls != 1:
            failures.append("truthful manual send did not reach awaiting_response")

        if (
            env["MINAI_PILOT_TOKEN"] in text
            or env["OPENAI_API_KEY"] in text
        ):
            failures.append("guided RFQ setup leaked a secret")

        before = (
            client.process_calls,
            client.confirm_calls,
            client.resume_calls,
            client.approve_calls,
            client.record_calls,
        )
        output = io.StringIO()
        with redirect_stdout(output):
            rc = _setup_rfq(
                env,
                status_func=lambda path: status,
                client_factory=lambda environ: client,
                release_func=_release,
                input_func=lambda prompt: (_ for _ in ()).throw(
                    AssertionError("no prompt expected")
                ),
            )
        after = (
            client.process_calls,
            client.confirm_calls,
            client.resume_calls,
            client.approve_calls,
            client.record_calls,
        )
        if rc != 0 or before != after:
            failures.append(
                "rerun with awaiting RFQ was not idempotent/read-only"
            )

    return {
        "name": "Guided controlled supplier RFQ setup",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    print(evaluate_pilot_ops_rfq_regressions())
