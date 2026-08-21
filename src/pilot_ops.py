from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from src.integrations.microsoft_auth import (
    CLIENT_ID_ENV,
    MAILBOX_ID_ENV,
    TENANT_ID_ENV,
    TOKEN_CACHE_PATH_ENV,
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
    MicrosoftAuthenticationError,
    acquire_silent_access_token,
)
from src.outlook_live_smoke import main as outlook_live_smoke_main
from src.paths import REPO_ROOT
from src.pilot_data_pack import (
    PilotDataPackError,
    resolve_pack_paths,
    status_pack,
    verify_pack,
)
from src.pilot_operator import (
    OperatorAPIError,
    OperatorConfigurationError,
    PilotOperatorClient,
)
from src.simulation.replay_receipt import (
    ReplayReceiptError,
    collect_release_identity,
)


SMOKE_PACK_ENV = "MINAI_OUTLOOK_SMOKE_PACK_DIR"
SMOKE_EVIDENCE_ENV = "MINAI_OUTLOOK_SMOKE_EVIDENCE_DIR"

DEFAULT_SMOKE_PACK = (
    Path.home()
    / ".local"
    / "share"
    / "minai-outlook-smoke-test"
)
DEFAULT_EVIDENCE_DIR = (
    Path.home()
    / ".local"
    / "share"
    / "minai-outlook-smoke-evidence"
)

OUTLOOK_AUTH_ENVS = (
    TENANT_ID_ENV,
    CLIENT_ID_ENV,
    MAILBOX_ID_ENV,
    TOKEN_CACHE_PATH_ENV,
)

CONFIRMATION_PROMPTS = (
    (
        "live_tenant_approved",
        "Controlled live read against the configured Microsoft mailbox is approved",
    ),
    (
        "openai_data_use_approved",
        "The four controlled smoke messages are approved for the configured OpenAI parser",
    ),
    (
        "four_test_messages_prepared",
        "All four controlled smoke messages are prepared in the mailbox",
    ),
    (
        "no_autonomous_outbound",
        "No autonomous outbound mail is configured or authorized for this smoke",
    ),
)

CONFIRMATION_FLAGS = {
    "live_tenant_approved": "--confirm-live-tenant-approved",
    "openai_data_use_approved": "--confirm-openai-data-use-approved",
    "four_test_messages_prepared": "--confirm-four-test-messages-prepared",
    "no_autonomous_outbound": "--confirm-no-autonomous-outbound",
}


class PilotOpsError(RuntimeError):
    """Safe operational failure whose message contains no secret values."""


def _outside_repository(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        return True
    return False


def _smoke_pack_path(environ: Mapping[str, str]) -> Path:
    raw = (environ.get(SMOKE_PACK_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_SMOKE_PACK
    if not path.is_absolute():
        raise PilotOpsError(f"{SMOKE_PACK_ENV} must be an absolute path")
    if not _outside_repository(path):
        raise PilotOpsError("smoke pack must remain outside the repository")
    return path


def _evidence_root(environ: Mapping[str, str]) -> Path:
    raw = (environ.get(SMOKE_EVIDENCE_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else DEFAULT_EVIDENCE_DIR
    if not path.is_absolute():
        raise PilotOpsError(f"{SMOKE_EVIDENCE_ENV} must be an absolute path")
    if not _outside_repository(path):
        raise PilotOpsError("smoke evidence must remain outside the repository")
    return path


def _cache_status(environ: Mapping[str, str]) -> tuple[str, str]:
    missing = [name for name in OUTLOOK_AUTH_ENVS if not (environ.get(name) or "").strip()]
    if missing:
        return "MISSING", "Microsoft Outlook environment is incomplete"

    try:
        config = MicrosoftAuthConfig.from_environment(environ)
    except MicrosoftAuthConfigurationError:
        return "BLOCKED", "Microsoft Outlook authentication configuration is invalid"

    path = config.token_cache_path
    if not path.is_file():
        return "MISSING", "Microsoft Outlook token cache is missing"
    if path.is_symlink():
        return "BLOCKED", "Microsoft Outlook token cache must not be a symlink"

    if os.name == "posix" and path.stat().st_mode & 0o077:
        return "BLOCKED", "Microsoft Outlook token cache permissions are not private"

    return "READY", "Private Microsoft Outlook token cache is present"


def _silent_auth_status(
    environ: Mapping[str, str],
    *,
    token_func: Callable[[MicrosoftAuthConfig], str] = acquire_silent_access_token,
) -> tuple[str, str]:
    cache_state, cache_message = _cache_status(environ)
    if cache_state != "READY":
        return cache_state, cache_message

    try:
        config = MicrosoftAuthConfig.from_environment(environ)
        token = token_func(config)
    except (
        MicrosoftAuthConfigurationError,
        MicrosoftAuthenticationError,
        OSError,
    ):
        return "BLOCKED", "Silent Microsoft authentication requires attention"

    if not isinstance(token, str) or not token.strip():
        return "BLOCKED", "Silent Microsoft authentication returned no usable token"

    return "PASS", "Silent Microsoft authentication passed; no mailbox read was performed"


def _release_status(
    *,
    release_func=collect_release_identity,
) -> tuple[str, str, str | None]:
    try:
        identity = release_func()
    except ReplayReceiptError:
        return "BLOCKED", "Repository release identity is unavailable", None

    if not identity.clean_worktree:
        return "BLOCKED", "Repository worktree is not clean", identity.commit_sha

    return "PASS", "Repository release identity is clean", identity.commit_sha


def _pack_status(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
) -> tuple[str, str, dict]:
    path = _smoke_pack_path(environ)
    try:
        result = status_func(path)
    except (OSError, UnicodeError, ValueError):
        return "BLOCKED", "Smoke data pack could not be inspected", {}

    if result.get("valid") is not True:
        return "BLOCKED", "Smoke data pack is not valid", result
    if result.get("verified") is not True:
        return "REVIEW", "Smoke data pack is valid and awaits human verification", result
    return "PASS", "Smoke data pack is valid and human-verified", result



def _openai_status(environ: Mapping[str, str]) -> tuple[str, str]:
    if not (environ.get("OPENAI_API_KEY") or "").strip():
        return "MISSING", "OPENAI_API_KEY is not configured in this shell"
    return "SET", "OpenAI provider secret is configured without displaying it"


def _runtime_status(
    environ: Mapping[str, str],
    *,
    client_factory=PilotOperatorClient.from_environment,
    release_func=collect_release_identity,
) -> tuple[str, str, dict | None]:
    if not (environ.get("MINAI_PILOT_TOKEN") or "").strip():
        return "MISSING", "Pilot operator token is not configured in this shell", None

    try:
        identity = release_func()
        client = client_factory(environ)
        client.status()
        runtime = client.runtime_release()
    except (
        OperatorAPIError,
        OperatorConfigurationError,
        ReplayReceiptError,
    ):
        return "OFFLINE", "Pilot runtime is not reachable with the current operator configuration", None

    if not isinstance(runtime, dict):
        return "BLOCKED", "Pilot runtime release payload is invalid", None

    runtime_sha = runtime.get("commit_sha")
    if (
        runtime.get("available") is not True
        or runtime.get("clean_worktree") is not True
        or not isinstance(runtime_sha, str)
    ):
        return "BLOCKED", "Pilot runtime does not report a clean release", runtime

    if runtime_sha.strip().lower() != identity.commit_sha:
        return "BLOCKED", "Pilot runtime commit does not match the local release", runtime

    return "PASS", "Pilot runtime is authenticated and matches the local release", runtime


def _rfq_status(
    environ: Mapping[str, str],
    *,
    client_factory=PilotOperatorClient.from_environment,
) -> tuple[str, str, dict | None]:
    if not (environ.get("MINAI_PILOT_TOKEN") or "").strip():
        return "MISSING", "Supplier RFQ state cannot be checked until the pilot operator is configured", None

    try:
        client = client_factory(environ)
        payload = client.list_rfqs()
    except (OperatorAPIError, OperatorConfigurationError):
        return "OFFLINE", "Supplier RFQ state is unavailable while the pilot runtime is offline", None

    if not isinstance(payload, dict):
        return "BLOCKED", "Supplier RFQ list payload is invalid", None

    rfqs = payload.get("supplier_rfqs")
    if not isinstance(rfqs, list):
        return "BLOCKED", "Supplier RFQ list payload is invalid", payload

    awaiting = [
        item for item in rfqs
        if isinstance(item, dict)
        and item.get("status") == "awaiting_response"
        and isinstance(item.get("rfq_id"), str)
        and item.get("rfq_id")
    ]

    if not awaiting:
        return "REQUIRED", "A truthfully sent controlled test RFQ must reach awaiting_response", payload

    return "PASS", "At least one controlled supplier RFQ is awaiting a response", payload


def _latest_session(evidence_root: Path) -> Path | None:
    if not evidence_root.is_dir():
        return None
    sessions = sorted(
        (
            item for item in evidence_root.iterdir()
            if item.is_dir() and item.name.startswith("session-")
        ),
        key=lambda item: item.name,
        reverse=True,
    )
    return sessions[0] if sessions else None


def _latest_prepared_session(evidence_root: Path) -> Path | None:
    if not evidence_root.is_dir():
        return None
    sessions = sorted(
        (
            item for item in evidence_root.iterdir()
            if item.is_dir()
            and item.name.startswith("session-")
            and (item / "manifest.json").is_file()
            and not (item / "receipt.json").exists()
        ),
        key=lambda item: item.name,
        reverse=True,
    )
    return sessions[0] if sessions else None


def _evidence_status(environ: Mapping[str, str]) -> tuple[str, str, Path | None]:
    root = _evidence_root(environ)
    session = _latest_session(root)
    if session is None:
        return "NOT_STARTED", "No live Outlook smoke evidence session exists", None

    manifest = session / "manifest.json"
    receipt = session / "receipt.json"
    if receipt.is_file():
        return "COMPLETE", "A smoke receipt exists in the latest evidence session", session
    if manifest.is_file():
        return "PREPARED", "The latest smoke session has a manifest and awaits the second pass", session
    return "INCOMPLETE", "The latest evidence session is incomplete", session


def _print_check(label: str, status: str, message: str) -> None:
    print(f"{label:<24} {status:<11} {message}")


def _status(
    environ: Mapping[str, str],
    *,
    token_func=acquire_silent_access_token,
    status_func=status_pack,
    client_factory=PilotOperatorClient.from_environment,
    release_func=collect_release_identity,
) -> int:
    release_state, release_message, release_sha = _release_status(
        release_func=release_func,
    )
    pack_state, pack_message, pack_result = _pack_status(
        environ,
        status_func=status_func,
    )
    cache_state, cache_message = _cache_status(environ)
    auth_state, auth_message = _silent_auth_status(
        environ,
        token_func=token_func,
    )
    openai_state, openai_message = _openai_status(environ)
    runtime_state, runtime_message, _ = _runtime_status(
        environ,
        client_factory=client_factory,
        release_func=release_func,
    )
    rfq_state, rfq_message, _ = _rfq_status(
        environ,
        client_factory=client_factory,
    )
    evidence_state, evidence_message, session = _evidence_status(environ)

    print("MINAI Pilot Operations")
    print("======================")
    _print_check("Repository release", release_state, release_message)
    if release_sha:
        print(f"{'Release SHA':<24} {release_sha}")
    _print_check("Smoke data pack", pack_state, pack_message)
    _print_check("Outlook token cache", cache_state, cache_message)
    _print_check("Silent Outlook auth", auth_state, auth_message)
    _print_check("OpenAI parser", openai_state, openai_message)
    _print_check("Pilot runtime", runtime_state, runtime_message)
    _print_check("Supplier RFQ state", rfq_state, rfq_message)
    _print_check("Smoke evidence", evidence_state, evidence_message)

    warnings = pack_result.get("warnings") if isinstance(pack_result, dict) else None
    if warnings:
        print("\nData-pack warnings:")
        for warning in warnings:
            print(f"- {warning}")

    print("\nNEXT ACTION")
    if release_state != "PASS":
        print("Resolve the repository release/worktree block before continuing.")
        return 2
    if pack_state == "BLOCKED":
        print("Repair or rebuild the technical smoke data pack.")
        return 2
    if pack_state == "REVIEW":
        print("Run: python -m src.pilot_ops outlook-smoke verify")
        return 0
    if auth_state != "PASS":
        print("Run: python -m src.outlook_auth")
        return 0
    if openai_state != "SET":
        print("Configure the approved OPENAI_API_KEY locally; do not paste it into chat.")
        return 0
    if runtime_state != "PASS":
        print("Configure/start the controlled pilot runtime, then rerun this status command.")
        return 0
    if rfq_state != "PASS":
        print("Run: python -m src.pilot_ops outlook-smoke setup-rfq")
        return 0
    if evidence_state in {"NOT_STARTED", "INCOMPLETE"}:
        print("Prepare the four controlled messages, then run: python -m src.pilot_ops outlook-smoke prepare")
        return 0
    if evidence_state == "PREPARED":
        print("Run: python -m src.pilot_ops outlook-smoke run")
        return 0

    print("Latest technical Outlook smoke evidence session is complete.")
    if session is not None:
        print(f"Evidence session: {session}")
    return 0


def _read_exact(prompt: str, expected: str, *, input_func=input) -> bool:
    value = input_func(f"{prompt}\nType {expected} to continue: ")
    return value.strip() == expected


def _guided_verify(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
    verify_func=verify_pack,
    input_func=input,
) -> int:
    path = _smoke_pack_path(environ)
    try:
        result = status_func(path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PilotOpsError("smoke data pack could not be inspected") from exc

    if result.get("valid") is not True:
        raise PilotOpsError("smoke data pack is not valid")
    if result.get("verified") is True:
        print("Smoke data pack is already human-verified.")
        return 0

    print("Technical smoke data-pack review")
    print("================================")
    for key in (
        "active_customer_count",
        "trusted_customer_count",
        "active_supplier_count",
        "contactable_supplier_count",
    ):
        print(f"{key}: {result.get(key)}")

    warnings = result.get("warnings") or []
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"- {warning}")

    print(
        "\nThis action freezes the current customer/supplier bytes as "
        "human-reviewed pilot evidence. It does not read Outlook, call OpenAI, "
        "or send any email."
    )

    verified_by = input_func("Verifier name: ").strip()
    if not verified_by:
        raise PilotOpsError("verifier identity is required")

    if not _read_exact(
        "Confirm that you reviewed the final technical smoke identities and warnings.",
        "REVIEWED",
        input_func=input_func,
    ):
        raise PilotOpsError("human verification was cancelled")

    try:
        verified = verify_func(
            path,
            verified_by=verified_by,
            confirm_final_reviewed=True,
        )
    except (PilotDataPackError, OSError, UnicodeError, ValueError) as exc:
        raise PilotOpsError("smoke data-pack verification failed") from exc

    if verified.get("verified") is not True:
        raise PilotOpsError("smoke data pack did not become verified")

    print("Smoke data-pack verification: PASS")
    return 0


def _collect_confirmations(*, input_func=input) -> list[str]:
    print(
        "This is a real controlled mailbox-read operation. "
        "It can call Microsoft Graph and the configured OpenAI parser. "
        "It does not authorize mailbox writes or automated outbound mail."
    )
    flags: list[str] = []
    for key, text in CONFIRMATION_PROMPTS:
        if not _read_exact(text, "YES", input_func=input_func):
            raise PilotOpsError("live smoke confirmation was cancelled")
        flags.append(CONFIRMATION_FLAGS[key])
    return flags


def _require_verified_pack(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
) -> Path:
    path = _smoke_pack_path(environ)
    try:
        status = status_func(path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise PilotOpsError("smoke data pack could not be inspected") from exc
    if status.get("valid") is not True or status.get("verified") is not True:
        raise PilotOpsError("technical smoke data pack must be valid and human-verified")

    configured_data_dir = (environ.get("MINAI_PILOT_DATA_DIR") or "").strip()
    if not configured_data_dir:
        raise PilotOpsError("MINAI_PILOT_DATA_DIR must point to the verified technical smoke pack")

    configured = Path(configured_data_dir).expanduser()
    if configured.resolve() != path.resolve():
        raise PilotOpsError(
            "MINAI_PILOT_DATA_DIR does not point to the verified technical smoke pack"
        )

    return path


def _ensure_evidence_root(environ: Mapping[str, str]) -> Path:
    root = _evidence_root(environ)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink():
        raise PilotOpsError("smoke evidence root must not be a symlink")
    if os.name == "posix":
        os.chmod(root, 0o700)
    return root


def _new_session(root: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for suffix in ("", "-01", "-02", "-03", "-04", "-05"):
        session = root / f"session-{stamp}{suffix}"
        try:
            session.mkdir(mode=0o700)
        except FileExistsError:
            continue
        if os.name == "posix":
            os.chmod(session, 0o700)
        return session
    raise PilotOpsError("could not allocate a new smoke evidence session")


def _prepare(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
    live_smoke_main=outlook_live_smoke_main,
    input_func=input,
) -> int:
    _require_verified_pack(environ, status_func=status_func)
    flags = _collect_confirmations(input_func=input_func)

    root = _ensure_evidence_root(environ)
    session = _new_session(root)
    manifest = session / "manifest.json"

    args = [
        "prepare",
        "--manifest",
        str(manifest),
        *flags,
    ]
    rc = live_smoke_main(args)
    if rc != 0:
        if not any(session.iterdir()):
            session.rmdir()
        raise PilotOpsError(f"live Outlook smoke prepare was blocked (exit {rc})")

    print("Smoke prepare: PASS")
    print(f"Evidence session: {session}")
    print("NEXT ACTION: run python -m src.pilot_ops outlook-smoke run")
    return 0


def _run(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
    live_smoke_main=outlook_live_smoke_main,
    input_func=input,
) -> int:
    _require_verified_pack(environ, status_func=status_func)
    root = _ensure_evidence_root(environ)
    session = _latest_prepared_session(root)
    if session is None:
        raise PilotOpsError("no prepared smoke evidence session exists")

    manifest = session / "manifest.json"
    receipt = session / "receipt.json"

    if not manifest.is_file():
        raise PilotOpsError("latest smoke evidence session has no manifest")
    if receipt.exists() or receipt.is_symlink():
        raise PilotOpsError("latest smoke evidence session already has a receipt")

    flags = _collect_confirmations(input_func=input_func)
    args = [
        "run",
        "--manifest",
        str(manifest),
        "--receipt",
        str(receipt),
        *flags,
    ]
    rc = live_smoke_main(args)
    if rc != 0:
        raise PilotOpsError(f"live Outlook smoke run was blocked (exit {rc})")

    print("Smoke run: PASS")
    print(f"Receipt: {receipt}")
    return 0



SMOKE_RFQ_INQUIRY_SUBJECT = "MINAI controlled smoke RFQ setup"
SMOKE_RFQ_INQUIRY_BODY = (
    "Please quote one controlled FTL road shipment.\n\n"
    "Pickup: Adana, Türkiye.\n"
    "Delivery: Hamburg 20095, Germany.\n"
    "Cargo: non-dangerous textile goods.\n"
    "Quantity: 33 EUR pallets, each 120 x 80 x 150 cm.\n"
    "Total gross weight: 20,000 kg.\n"
    "Equipment: Tenteli / Curtainsider.\n"
    "Temperature control: not required.\n"
    "ADR: no.\n"
    "Ready date: 2026-08-24.\n"
    "Requested delivery: standard road transit.\n\n"
    "This is controlled technical smoke-test content only.\n"
)


def _load_json_list(path: Path, *, label: str) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotOpsError(f"{label} could not be read") from exc
    if not isinstance(raw, list):
        raise PilotOpsError(f"{label} payload is invalid")
    return [item for item in raw if isinstance(item, dict)]


def _technical_smoke_identities(
    environ: Mapping[str, str],
) -> tuple[str, str, str]:
    pack = _smoke_pack_path(environ)
    try:
        paths = resolve_pack_paths(pack)
    except (PilotDataPackError, OSError, ValueError) as exc:
        raise PilotOpsError("smoke data-pack paths are unavailable") from exc

    customers = _load_json_list(
        paths.customer_memory,
        label="customer smoke dataset",
    )
    suppliers = _load_json_list(
        paths.supplier_capabilities,
        label="supplier smoke dataset",
    )

    trusted: list[str] = []
    for profile in customers:
        if profile.get("active") is not True:
            continue
        addresses = profile.get("trusted_sender_addresses")
        if not isinstance(addresses, list):
            continue
        for value in addresses:
            address = str(value or "").strip().lower()
            if address and not address.endswith(".invalid"):
                trusted.append(address)

    supplier_contacts: list[tuple[str, str]] = []
    for supplier in suppliers:
        if supplier.get("active") is not True:
            continue
        if str(supplier.get("role") or "").strip().lower() != "primary":
            continue
        supplier_name = str(supplier.get("supplier_name") or "").strip()
        contacts = supplier.get("contacts")
        if not isinstance(contacts, list):
            continue
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            if contact.get("active") is not True:
                continue
            if contact.get("is_primary") is not True:
                continue
            address = str(contact.get("email") or "").strip().lower()
            if address and not address.endswith(".invalid"):
                supplier_contacts.append((supplier_name, address))

    trusted = sorted(set(trusted))
    supplier_contacts = sorted(set(supplier_contacts))

    if len(trusted) != 1:
        raise PilotOpsError(
            "technical smoke pack must contain exactly one non-filler trusted customer address"
        )
    if len(supplier_contacts) != 1:
        raise PilotOpsError(
            "technical smoke pack must contain exactly one non-filler primary supplier contact"
        )

    supplier_name, supplier_email = supplier_contacts[0]
    return trusted[0], supplier_name, supplier_email


def _rfq_list(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        raise PilotOpsError("supplier RFQ list payload is invalid")
    items = payload.get("supplier_rfqs")
    if not isinstance(items, list):
        raise PilotOpsError("supplier RFQ list payload is invalid")
    return [item for item in items if isinstance(item, dict)]


def _find_string(payload: object, key: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for item in payload.values():
            found = _find_string(item, key)
            if found:
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _find_string(item, key)
            if found:
                return found
    return None


def _proposal_review_payload(proposal: object) -> object:
    if not isinstance(proposal, dict):
        return {"proposal": "available"}
    for key in (
        "proposed_shipment",
        "extracted_shipment",
        "shipment",
    ):
        value = proposal.get(key)
        if isinstance(value, dict):
            return value
    return {
        key: proposal.get(key)
        for key in ("proposal_id", "status", "confirmation_status")
        if key in proposal
    }


def _matching_supplier_rfqs(
    rfqs: list[dict],
    supplier_email: str,
    statuses: set[str],
) -> list[dict]:
    return [
        item
        for item in rfqs
        if str(item.get("recipient_email") or "").strip().lower()
        == supplier_email
        and str(item.get("status") or "").strip().lower()
        in statuses
        and isinstance(item.get("rfq_id"), str)
        and item.get("rfq_id")
    ]


def _require_runtime_ready(
    environ: Mapping[str, str],
    *,
    client_factory=PilotOperatorClient.from_environment,
    release_func=collect_release_identity,
):
    state, message, _ = _runtime_status(
        environ,
        client_factory=client_factory,
        release_func=release_func,
    )
    if state != "PASS":
        raise PilotOpsError(message)
    try:
        return client_factory(environ)
    except (OperatorAPIError, OperatorConfigurationError) as exc:
        raise PilotOpsError("pilot operator client is unavailable") from exc


def _setup_rfq(
    environ: Mapping[str, str],
    *,
    status_func=status_pack,
    client_factory=PilotOperatorClient.from_environment,
    release_func=collect_release_identity,
    input_func=input,
) -> int:
    _require_verified_pack(environ, status_func=status_func)
    client = _require_runtime_ready(
        environ,
        client_factory=client_factory,
        release_func=release_func,
    )

    customer_email, supplier_name, supplier_email = (
        _technical_smoke_identities(environ)
    )

    try:
        initial = _rfq_list(client.list_rfqs())
    except (OperatorAPIError, OperatorConfigurationError) as exc:
        raise PilotOpsError("supplier RFQ state could not be read") from exc

    awaiting = _matching_supplier_rfqs(
        initial,
        supplier_email,
        {"awaiting_response"},
    )
    if len(awaiting) == 1:
        print("Controlled supplier RFQ setup: PASS")
        print("A truthfully sent controlled RFQ is already awaiting a response.")
        print(
            "NEXT HUMAN ACTION: reply to that RFQ from the controlled supplier "
            "mailbox so the reply arrives in the configured Outlook pilot inbox."
        )
        return 0
    if len(awaiting) > 1:
        raise PilotOpsError(
            "multiple controlled supplier RFQs are awaiting responses; manual cleanup is required"
        )

    reusable = _matching_supplier_rfqs(
        initial,
        supplier_email,
        {"draft", "approved"},
    )

    if len(reusable) > 1:
        raise PilotOpsError(
            "multiple reusable controlled supplier RFQs exist; manual review is required"
        )

    draft: dict | None = reusable[0] if reusable else None

    if draft is None:
        if not (environ.get("OPENAI_API_KEY") or "").strip():
            raise PilotOpsError(
                "OPENAI_API_KEY is required to create the controlled synthetic inquiry"
            )

        print("Controlled RFQ setup")
        print("====================")
        print(
            "This step sends only the synthetic technical inquiry below to the "
            "configured OpenAI parser through the local pilot API."
        )
        print("It does NOT read Outlook and does NOT send any email.")
        print()
        print(SMOKE_RFQ_INQUIRY_BODY.rstrip())
        print()

        if not _read_exact(
            "Approve creation of this synthetic technical inquiry.",
            "CREATE",
            input_func=input_func,
        ):
            raise PilotOpsError("controlled inquiry creation was cancelled")

        before_ids = {
            str(item.get("rfq_id"))
            for item in initial
            if item.get("rfq_id")
        }

        try:
            result = client.process_email(
                email_text=SMOKE_RFQ_INQUIRY_BODY,
                sender_address=customer_email,
                sender_name="Controlled Smoke Customer",
                subject=SMOKE_RFQ_INQUIRY_SUBJECT,
                external_message_id=(
                    "pilot-ops-rfq-setup-"
                    + release_func().commit_sha[:16]
                ),
            )
        except (OperatorAPIError, OperatorConfigurationError) as exc:
            raise PilotOpsError(
                "controlled synthetic inquiry processing failed"
            ) from exc

        proposal_id = _find_string(result, "proposal_id")
        if not proposal_id:
            raise PilotOpsError(
                "controlled inquiry did not return an extraction proposal"
            )

        try:
            proposal = client.get_proposal(proposal_id)
        except (OperatorAPIError, OperatorConfigurationError) as exc:
            raise PilotOpsError(
                "extraction proposal could not be read for human review"
            ) from exc

        print("Extracted technical shipment review")
        print("===================================")
        print(
            json.dumps(
                _proposal_review_payload(proposal),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )

        if not _read_exact(
            "Confirm this extracted technical shipment without corrections.",
            "REVIEWED",
            input_func=input_func,
        ):
            raise PilotOpsError(
                "extraction proposal remains unconfirmed; no RFQ was approved or sent"
            )

        try:
            client.confirm_proposal(proposal_id, {})
            client.resume_proposal(proposal_id)
            after = _rfq_list(client.list_rfqs())
        except (OperatorAPIError, OperatorConfigurationError) as exc:
            raise PilotOpsError(
                "proposal confirmation/RFQ generation was blocked; "
                "use the existing proposal correction workflow if a safety field needs correction"
            ) from exc

        created = [
            item
            for item in _matching_supplier_rfqs(
                after,
                supplier_email,
                {"draft", "approved"},
            )
            if str(item.get("rfq_id")) not in before_ids
        ]

        if len(created) != 1:
            raise PilotOpsError(
                "controlled inquiry did not create exactly one reusable RFQ for the test supplier"
            )
        draft = created[0]

    rfq_id = str(draft.get("rfq_id") or "").strip()
    if not rfq_id:
        raise PilotOpsError("controlled supplier RFQ identifier is missing")

    try:
        current = client.get_rfq(rfq_id)
    except (OperatorAPIError, OperatorConfigurationError) as exc:
        raise PilotOpsError("controlled supplier RFQ could not be read") from exc

    if not isinstance(current, dict):
        raise PilotOpsError("controlled supplier RFQ payload is invalid")

    subject = str(current.get("subject") or "").strip()
    body = str(current.get("body") or "").strip()
    status = str(current.get("status") or "").strip().lower()

    if not subject or not body:
        raise PilotOpsError("controlled supplier RFQ has no sendable subject/body")

    print()
    print("Controlled supplier RFQ review")
    print("==============================")
    print(f"Supplier:  {supplier_name}")
    print(f"To:        {supplier_email}")
    print(f"Reference: MINAI-RFQ:{rfq_id}")
    print(f"Subject:   {subject}")
    print()
    print(body)
    print()

    if status == "draft":
        if not _read_exact(
            "Approve this controlled RFQ for manual external sending.",
            "APPROVE",
            input_func=input_func,
        ):
            raise PilotOpsError(
                "controlled RFQ remains draft; no email was sent"
            )
        try:
            current = client.approve_rfq(rfq_id)
        except (OperatorAPIError, OperatorConfigurationError) as exc:
            raise PilotOpsError("controlled supplier RFQ approval failed") from exc
        if not isinstance(current, dict):
            raise PilotOpsError("controlled supplier RFQ approval payload is invalid")
        status = str(current.get("status") or "").strip().lower()

    if status != "approved":
        raise PilotOpsError(
            f"controlled supplier RFQ is in unexpected lifecycle state: {status or 'unknown'}"
        )

    try:
        mailbox = MicrosoftAuthConfig.from_environment(environ).mailbox_id
    except MicrosoftAuthConfigurationError as exc:
        raise PilotOpsError(
            "configured Outlook mailbox identity is unavailable"
        ) from exc

    print()
    print("NEXT HUMAN ACTION")
    print("=================")
    print("Send this RFQ manually now. MINAI will not send it for you.")
    print(f"From: {mailbox}")
    print(f"To:   {supplier_email}")
    print("Use the exact Subject and Body shown above.")
    print(
        "After the message is genuinely present in the Sent folder, return here."
    )

    if not _read_exact(
        "Confirm the exact controlled RFQ was genuinely sent manually.",
        "SENT",
        input_func=input_func,
    ):
        raise PilotOpsError(
            "manual send was not confirmed; sent evidence was NOT recorded"
        )

    try:
        client.record_rfq_manually_sent(rfq_id)
        final = client.get_rfq(rfq_id)
    except (OperatorAPIError, OperatorConfigurationError) as exc:
        raise PilotOpsError(
            "manual-send evidence could not be recorded"
        ) from exc

    if (
        not isinstance(final, dict)
        or str(final.get("status") or "").strip().lower()
        != "awaiting_response"
    ):
        raise PilotOpsError(
            "controlled RFQ did not reach awaiting_response after truthful manual-send evidence"
        )

    print("Controlled supplier RFQ setup: PASS")
    print(f"RFQ reference: MINAI-RFQ:{rfq_id}")
    print(
        "NEXT HUMAN ACTION: open the controlled supplier mailbox, reply to the "
        "RFQ without changing its reference, and make sure the reply arrives in "
        "the configured Outlook pilot inbox."
    )
    return 0

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Guided MINAI pilot operations with explicit human safety gates."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "doctor",
        help="Inspect the current technical pilot state without reading the mailbox.",
    )

    smoke = commands.add_parser("outlook-smoke")
    smoke_commands = smoke.add_subparsers(dest="smoke_action")
    smoke_commands.add_parser("status")
    smoke_commands.add_parser("verify")
    smoke_commands.add_parser("setup-rfq")
    smoke_commands.add_parser("prepare")
    smoke_commands.add_parser("run")

    return parser


def main(
    argv=None,
    *,
    environ: Mapping[str, str] | None = None,
    token_func=acquire_silent_access_token,
    status_func=status_pack,
    verify_func=verify_pack,
    client_factory=PilotOperatorClient.from_environment,
    release_func=collect_release_identity,
    live_smoke_main=outlook_live_smoke_main,
    input_func=input,
) -> int:
    args = _parser().parse_args(argv)
    env = environ if environ is not None else os.environ

    try:
        if args.command == "doctor":
            return _status(
                env,
                token_func=token_func,
                status_func=status_func,
                client_factory=client_factory,
                release_func=release_func,
            )

        action = args.smoke_action or "status"
        if action == "status":
            return _status(
                env,
                token_func=token_func,
                status_func=status_func,
                client_factory=client_factory,
                release_func=release_func,
            )
        if action == "verify":
            return _guided_verify(
                env,
                status_func=status_func,
                verify_func=verify_func,
                input_func=input_func,
            )
        if action == "setup-rfq":
            return _setup_rfq(
                env,
                status_func=status_func,
                client_factory=client_factory,
                release_func=release_func,
                input_func=input_func,
            )
        if action == "prepare":
            return _prepare(
                env,
                status_func=status_func,
                live_smoke_main=live_smoke_main,
                input_func=input_func,
            )
        if action == "run":
            return _run(
                env,
                status_func=status_func,
                live_smoke_main=live_smoke_main,
                input_func=input_func,
            )

        raise PilotOpsError("unsupported pilot operation")

    except PilotOpsError as exc:
        print(f"Pilot ops blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
