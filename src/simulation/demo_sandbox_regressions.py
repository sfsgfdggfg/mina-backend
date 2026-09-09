from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from src.core.demo_runtime import DemoOutboundMailSender, validate_demo_runtime
from src.core.mail import OutboundMailRequest
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.master_data_repository import SQLiteMasterDataRepository
from src.demo_launcher import _configure_environment
from src.demo_seed import seed_demo_database


def evaluate_demo_sandbox_regressions() -> dict:
    failures: list[str] = []

    def check(condition: bool, label: str):
        if condition:
            print(f"PASS {label}")
        else:
            print(f"FAIL {label}")
            failures.append(label)

    with tempfile.TemporaryDirectory(prefix="minai-demo-regression-") as directory:
        root = Path(directory)
        db = root / "demo.sqlite3"
        outbox = root / "outbox.jsonl"
        seeded = seed_demo_database(db, reset=True)
        repeated = seed_demo_database(db, reset=False)
        store = SQLitePilotStore(db, run_id="demo-regression", retention_days=365)
        jobs = SQLiteMinaJobRepository(store).list_all()
        masters = SQLiteMasterDataRepository(store)
        check(seeded.get("job_count") == 11 and len(jobs) == 11, "demo seed creates a populated synthetic MINA workload")
        check(repeated.get("reason") == "already_seeded" and len(jobs) == 11, "demo seed is idempotent without reset")
        check(len(masters.list_customers()) == 12 and len(masters.list_suppliers()) == 6, "demo seed includes synthetic customer and supplier master data")
        check(all(
            (contact.email or "").endswith(".invalid")
            for profile in [*masters.list_customers(), *masters.list_suppliers()]
            for contact in profile.contacts if contact.email
        ), "all demo master-data email contacts use reserved invalid domains")

        sender = DemoOutboundMailSender(outbox)
        safe = sender.send(OutboundMailRequest(
            operation_id="demo-safe", recipients=["pricing@rhein.supplier.invalid"],
            subject="Synthetic", body_text="Synthetic demo message", purpose="supplier_rfq",
        ))
        unsafe = sender.send(OutboundMailRequest(
            operation_id="demo-unsafe", recipients=["real@example.com"],
            subject="Synthetic", body_text="Synthetic demo message", purpose="supplier_rfq",
        ))
        check(safe.status == "sent" and outbox.exists(), "demo sender records synthetic sent evidence locally")
        check(unsafe.status == "rejected_before_provider", "demo sender rejects non-invalid recipients before provider delivery")
        receipts = [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines() if line.strip()]
        check(len(receipts) == 1 and receipts[0]["request"]["operation_id"] == "demo-safe", "rejected demo delivery never enters synthetic outbox")

        env = {
            "MINAI_DEMO_MODE": "true",
            "MINAI_PILOT_MODE": "false",
            "MINAI_OUTBOUND_MODE": "shadow",
            "MINAI_WEB_SHELL_ENABLED": "true",
            "MINAI_PILOT_DB_PATH": str(db),
            "MINAI_DEMO_OUTBOX_PATH": str(outbox),
        }
        try:
            validate_demo_runtime(env)
            valid_isolation = True
        except RuntimeError:
            valid_isolation = False
        check(valid_isolation, "demo runtime accepts only isolated shadow-mode configuration")
        for mutation in (
            {**env, "MINAI_PILOT_MODE": "true"},
            {**env, "MINAI_OUTBOUND_MODE": "controlled_send"},
            {**env, "MINAI_PILOT_DB_PATH": str(Path(__file__).resolve().parents[2] / "data" / "demo.sqlite3")},
            {**env, "MINAI_DEMO_OUTBOX_PATH": "relative-outbox.jsonl"},
        ):
            try:
                validate_demo_runtime(mutation)
            except RuntimeError:
                pass
            else:
                failures.append("demo runtime isolation validation failed closed")
                print("FAIL demo runtime isolation validation failed closed")
                break
        else:
            print("PASS demo runtime isolation validation fails closed")

        old = dict(os.environ)
        try:
            os.environ["MINAI_DEMO_STATE_DIR"] = str(root / "launcher-state")
            db_path, outbox_path = _configure_environment(root)
            check(
                os.environ.get("MINAI_DEMO_MODE") == "true"
                and os.environ.get("MINAI_PILOT_MODE") == "false"
                and os.environ.get("MINAI_OUTBOUND_MODE") == "shadow"
                and Path(db_path).parent == root / "launcher-state"
                and Path(outbox_path).parent == root / "launcher-state",
                "demo launcher forces isolated local runtime boundaries",
            )
        finally:
            os.environ.clear(); os.environ.update(old)

    root = Path(__file__).resolve().parents[2]
    shell = (root / "src" / "web_shell.py").read_text(encoding="utf-8")
    css = (root / "ui" / "web_shell" / "app.css").read_text(encoding="utf-8")
    check("DEMO · SENTETİK VERİ" in shell and ".demo-banner" in css, "browser shell visibly labels synthetic demo mode")

    return {"name": "Synthetic demo sandbox", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_demo_sandbox_regressions()
    print("\nDemo sandbox regressions:", "PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)
