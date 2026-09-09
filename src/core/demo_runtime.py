from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from src.core.mail import MailSendResult, OutboundMailRequest
from src.paths import REPO_ROOT

DEMO_MODE_ENV = "MINAI_DEMO_MODE"
DEMO_OUTBOX_ENV = "MINAI_DEMO_OUTBOX_PATH"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def demo_mode_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return _truthy(env.get(DEMO_MODE_ENV))


def validate_demo_runtime(environ: Mapping[str, str] | None = None) -> None:
    env = environ if environ is not None else os.environ
    if not demo_mode_enabled(env):
        return
    if _truthy(env.get("MINAI_PILOT_MODE")):
        raise RuntimeError("MINAI demo mode cannot run as controlled pilot mode.")
    if (env.get("MINAI_OUTBOUND_MODE") or "shadow").strip().casefold() != "shadow":
        raise RuntimeError("MINAI demo mode requires MINAI_OUTBOUND_MODE=shadow.")
    if not _truthy(env.get("MINAI_WEB_SHELL_ENABLED")):
        raise RuntimeError("MINAI demo mode requires the browser web shell.")
    db_raw = (env.get("MINAI_PILOT_DB_PATH") or "").strip()
    outbox_raw = (env.get(DEMO_OUTBOX_ENV) or "").strip()
    if not db_raw or not outbox_raw:
        raise RuntimeError("MINAI demo mode requires explicit synthetic DB and outbox paths.")
    db_path = Path(db_raw).expanduser()
    outbox_path = Path(outbox_raw).expanduser()
    if not db_path.is_absolute() or not outbox_path.is_absolute():
        raise RuntimeError("MINAI demo DB and outbox paths must be absolute.")
    repo = REPO_ROOT.resolve()
    for candidate, label in ((db_path, "database"), (outbox_path, "outbox")):
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(repo)
        except ValueError:
            pass
        else:
            raise RuntimeError(f"MINAI demo {label} must be stored outside the repository.")
    if db_path.resolve(strict=False) == outbox_path.resolve(strict=False):
        raise RuntimeError("MINAI demo DB and outbox paths must be distinct.")


class DemoOutboundMailSender:
    """Local-only synthetic sender used by the demo sandbox.

    It rejects every recipient outside the reserved .invalid namespace and writes
    a JSONL outbox receipt instead of touching Outlook or any external provider.
    """

    provider_name = "minai_demo_outbox"

    def __init__(self, outbox_path: str | Path) -> None:
        self.outbox_path = Path(outbox_path)
        self.outbox_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    @staticmethod
    def _safe_recipient(address: str) -> bool:
        domain = address.rsplit("@", 1)[-1].strip().casefold()
        return domain == "invalid" or domain.endswith(".invalid")

    def send(self, request: OutboundMailRequest) -> MailSendResult:
        unsafe = [address for address in request.recipients if not self._safe_recipient(address)]
        if unsafe:
            return MailSendResult(
                operation_id=request.operation_id,
                status="rejected_before_provider",
                reason="demo_sender_rejects_non_invalid_recipient",
            )
        sent_at = datetime.now(timezone.utc)
        message_id = f"demo-{uuid4()}"
        receipt = {
            "provider": self.provider_name,
            "provider_message_id": message_id,
            "sent_at": sent_at.isoformat(),
            "request": request.model_dump(mode="json"),
        }
        with self._lock:
            with self.outbox_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="synthetic_demo_delivery_recorded",
            provider_name=self.provider_name,
            provider_message_id=message_id,
            sent_at=sent_at,
        )
