from __future__ import annotations

import os
import shutil
from pathlib import Path
from threading import Lock

from src.core.demo_runtime import demo_mode_enabled, validate_demo_runtime
from src.demo_seed import seed_demo_customer_memory, seed_demo_database
from src.paths import REPO_ROOT


_RESET_LOCK = Lock()


class DemoResetUnavailableError(RuntimeError):
    pass


def _required_path(name: str) -> Path:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        raise DemoResetUnavailableError(f"{name} is required for demo reset.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DemoResetUnavailableError(f"{name} must be absolute for demo reset.")
    return path.absolute()


def _demo_state_dir() -> Path:
    raw = (os.environ.get("MINAI_DEMO_STATE_DIR") or str(Path.home() / ".minai" / "demo")).strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DemoResetUnavailableError("MINAI_DEMO_STATE_DIR must be absolute.")
    resolved = path.resolve(strict=False)
    repo = REPO_ROOT.resolve()
    try:
        resolved.relative_to(repo)
    except ValueError:
        pass
    else:
        raise DemoResetUnavailableError("Demo reset state must remain outside the repository.")
    if path.exists() and path.is_symlink():
        raise DemoResetUnavailableError("Demo reset state directory must not be a symlink.")
    return resolved


def _require_state_child(path: Path, state_dir: Path, label: str) -> Path:
    resolved = path.resolve(strict=False)
    try:
        relative = resolved.relative_to(state_dir)
    except ValueError as exc:
        raise DemoResetUnavailableError(f"Demo {label} must stay inside MINAI_DEMO_STATE_DIR.") from exc
    if not relative.parts:
        raise DemoResetUnavailableError(f"Demo {label} cannot be the state directory itself.")
    if path.exists() and path.is_symlink():
        raise DemoResetUnavailableError(f"Demo {label} must not be a symlink.")
    return resolved


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def reset_demo_sandbox() -> dict:
    if not demo_mode_enabled():
        raise DemoResetUnavailableError("demo_reset_unavailable")
    validate_demo_runtime()

    state_dir = _demo_state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = _require_state_child(_required_path("MINAI_PILOT_DB_PATH"), state_dir, "database")
    outbox_path = _require_state_child(_required_path("MINAI_DEMO_OUTBOX_PATH"), state_dir, "outbox")
    memory_path = _require_state_child(_required_path("MINAI_CUSTOMER_MEMORY_PATH"), state_dir, "customer memory")
    backup_dir = _require_state_child(_required_path("MINAI_CUSTOMER_MEMORY_BACKUP_DIR"), state_dir, "customer memory backup directory")
    outlook_target = _require_state_child(state_dir / "demo_outlook_supplier_target.txt", state_dir, "Outlook target lock")

    with _RESET_LOCK:
        for candidate in (outbox_path, outlook_target, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
            _remove_file(candidate)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        seeded = seed_demo_database(db_path, reset=True)
        memory = seed_demo_customer_memory(memory_path, reset=True)

    return {
        "reset_status": "complete",
        "synthetic_only": True,
        "job_count": seeded.get("job_count", 0),
        "customer_count": seeded.get("customer_count", 0),
        "supplier_count": seeded.get("supplier_count", 0),
        "assignment_count": seeded.get("assignment_count", 0),
        "attachment_review_count": seeded.get("attachment_review_count", 0),
        "fixed_rate_count": seeded.get("fixed_rate_count", 0),
        "customer_memory_profile_count": memory.get("profile_count", 0),
        "outbox_cleared": not outbox_path.exists(),
        "outlook_replay_state_cleared": not outlook_target.exists(),
    }
