from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.core.web_session import hash_password
from src.demo_seed import seed_demo_customer_memory, seed_demo_database

DEMO_EMAIL = "demo@minai.invalid"
DEMO_PASSWORD = "minai-demo-2026!"
DEMO_OPERATORS = {
    DEMO_EMAIL: "Demo Operator",
    "ayse@minai.invalid": "Ayşe Demo",
    "mehmet@minai.invalid": "Mehmet Demo",
}


def _configure_environment(root: Path) -> tuple[Path, Path]:
    state_dir = Path(os.environ.get("MINAI_DEMO_STATE_DIR", str(Path.home() / ".minai" / "demo"))).expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "minai_demo.sqlite3"
    outbox_path = state_dir / "demo_outbox.jsonl"
    customer_memory_path = state_dir / "customer_memory.json"
    customer_memory_backup_dir = state_dir / "customer_memory_backups"

    password_hash = hash_password(DEMO_PASSWORD, salt=b"minai-demo-seed!")
    users = {
        email: {
            "name": name,
            "password_hash": password_hash,
            "active": True,
        }
        for email, name in DEMO_OPERATORS.items()
    }
    os.environ.update({
        "MINAI_DEMO_MODE": "true",
        "MINAI_PILOT_MODE": "false",
        "MINAI_OUTBOUND_MODE": "shadow",
        "MINAI_WEB_SHELL_ENABLED": "true",
        "MINAI_WEB_COOKIE_SECURE": "false",
        "MINAI_PILOT_DB_PATH": str(db_path),
        "MINAI_DEMO_OUTBOX_PATH": str(outbox_path),
        "MINAI_CUSTOMER_MEMORY_PATH": str(customer_memory_path),
        "MINAI_CUSTOMER_MEMORY_BACKUP_DIR": str(customer_memory_backup_dir),
        "MINAI_DEMO_BIND_HOST": "127.0.0.1",
        "MINAI_WEB_USERS_JSON": json.dumps(users, separators=(",", ":")),
        "MINAI_WEB_SESSION_SECRET": "minai-demo-local-session-secret-2026-only",
        "MINAI_WEB_SESSION_TTL_MINUTES": "480",
        "MINAI_WEB_SESSION_IDLE_MINUTES": "120",
    })
    return db_path, outbox_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the isolated MINAI synthetic demo sandbox.")
    parser.add_argument("--reset", action="store_true", help="Reset and reseed synthetic demo state.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MINAI_DEMO_PORT", "8765")))
    args = parser.parse_args()
    if args.port < 1024 or args.port > 65535:
        parser.error("--port must be between 1024 and 65535")

    root = Path(__file__).resolve().parents[1]
    db_path, outbox_path = _configure_environment(root)
    result = seed_demo_database(db_path, reset=args.reset)
    memory_result = seed_demo_customer_memory(Path(os.environ["MINAI_CUSTOMER_MEMORY_PATH"]), reset=args.reset)

    print("MINAI Demo Sandbox")
    print(f"URL: http://127.0.0.1:{args.port}/app")
    print(f"Login: {DEMO_EMAIL}")
    print(f"Password: {DEMO_PASSWORD}")
    print(f"Synthetic DB: {db_path}")
    print(f"Synthetic outbox: {outbox_path}")
    print(f"Seed: {result}")
    print(f"Customer memory seed: {memory_result}")
    print("Safety: only *.invalid recipients are accepted; no Outlook delivery is possible in demo mode.")

    import uvicorn
    uvicorn.run(
        "src.api:app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
        proxy_headers=False,
        forwarded_allow_ips="",
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
