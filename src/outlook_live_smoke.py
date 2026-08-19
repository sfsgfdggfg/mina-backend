from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from src.paths import REPO_ROOT
from src.pilot_operator import (
    OperatorAPIError,
    OperatorConfigurationError,
    PilotOperatorClient,
)
from src.simulation.outlook_live_smoke_receipt import (
    CONFIRMATION_KEYS,
    SCENARIOS,
    OutlookLiveSmokeReceiptError,
    build_outlook_live_smoke_receipt,
    evaluate_outlook_live_smoke_pull,
    write_outlook_live_smoke_receipt,
)
from src.simulation.replay_receipt import (
    ReleaseIdentity,
    ReplayReceiptError,
    collect_release_identity,
    require_clean_release_identity,
)


_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class OutlookLiveSmokeRunnerError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OutlookLiveSmokeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    pilot_commit_sha: str
    prepared_at: datetime
    pull_limit: int = Field(
        ge=4,
        le=50,
    )
    message_ids: dict[str, str]

    @field_validator("pilot_commit_sha")
    @classmethod
    def valid_commit(cls, value: str):
        normalized = value.strip().lower()

        if not _COMMIT_RE.fullmatch(
            normalized
        ):
            raise ValueError(
                "invalid pilot commit sha"
            )

        return normalized

    @field_validator("message_ids")
    @classmethod
    def exact_unique_scenarios(
        cls,
        value,
    ):
        if set(value) != set(SCENARIOS):
            raise ValueError(
                "invalid smoke scenario set"
            )

        ids = list(value.values())

        if any(
            not isinstance(item, str)
            or not item.strip()
            for item in ids
        ):
            raise ValueError(
                "invalid smoke message id"
            )

        if len(set(ids)) != len(ids):
            raise ValueError(
                "smoke message ids must be unique"
            )

        return {
            key: item.strip()
            for key, item in value.items()
        }


def _path_has_symlink(path: Path):
    candidate = path.expanduser()

    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate

    current = Path(candidate.anchor)

    for part in candidate.parts[1:]:
        current = current / part

        try:
            if current.is_symlink():
                return True
        except OSError:
            return True

    return False


def _external_destination(path: Path):
    candidate = path.expanduser()

    if not candidate.is_absolute():
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "path_must_be_absolute"
        )

    if _path_has_symlink(
        candidate.parent
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "symlink_forbidden"
        )

    try:
        parent = candidate.parent.resolve(
            strict=True
        )
    except (OSError, RuntimeError) as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "parent_unavailable"
        ) from exc

    destination = parent / candidate.name

    try:
        destination.relative_to(
            REPO_ROOT.resolve()
        )
    except ValueError:
        return destination

    raise OutlookLiveSmokeRunnerError(
        "outlook_smoke_manifest_"
        "inside_repository"
    )


def write_manifest(
    path: Path,
    manifest: OutlookLiveSmokeManifest,
):
    destination = _external_destination(
        path
    )

    if (
        destination.exists()
        or destination.is_symlink()
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "already_exists"
        )

    payload = (
        json.dumps(
            manifest.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        dir=destination.parent,
    )

    temporary = Path(temp_name)

    try:
        if os.name == "posix":
            os.fchmod(fd, 0o600)

        with os.fdopen(
            fd,
            "wb",
        ) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())

        try:
            os.link(
                temporary,
                destination,
            )
        except FileExistsError as exc:
            raise OutlookLiveSmokeRunnerError(
                "outlook_smoke_manifest_"
                "already_exists"
            ) from exc

        if os.name == "posix":
            destination.chmod(0o600)

    except OutlookLiveSmokeRunnerError:
        raise

    except OSError as exc:
        destination.unlink(
            missing_ok=True
        )
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_write_failed"
        ) from exc

    finally:
        temporary.unlink(
            missing_ok=True
        )

    return destination


def load_manifest(
    path: Path,
):
    candidate = path.expanduser()

    if (
        not candidate.is_absolute()
        or _path_has_symlink(candidate)
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_invalid"
        )

    try:
        resolved = candidate.resolve(
            strict=True
        )
        resolved.relative_to(
            REPO_ROOT.resolve()
        )
    except ValueError:
        pass
    except (OSError, RuntimeError) as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_unreadable"
        ) from exc
    else:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "inside_repository"
        )

    if os.name == "posix":
        try:
            mode = resolved.stat().st_mode
        except OSError as exc:
            raise OutlookLiveSmokeRunnerError(
                "outlook_smoke_manifest_unreadable"
            ) from exc

        if mode & 0o077:
            raise OutlookLiveSmokeRunnerError(
                "outlook_smoke_manifest_"
                "permissions_not_private"
            )

    try:
        raw = json.loads(
            resolved.read_text(
                encoding="utf-8"
            )
        )

        manifest = (
            OutlookLiveSmokeManifest
            .model_validate(raw)
        )

    except Exception as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_invalid"
        ) from exc

    return manifest


def manifest_sha256(path: Path):
    digest = hashlib.sha256()

    try:
        with path.open("rb") as stream:
            for chunk in iter(
                lambda: stream.read(
                    1024 * 1024
                ),
                b"",
            ):
                digest.update(chunk)
    except OSError as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_unreadable"
        ) from exc

    return digest.hexdigest()


def _require_local_release(
    identity: ReleaseIdentity,
):
    try:
        require_clean_release_identity(
            identity
        )
    except ReplayReceiptError as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_requires_"
            "clean_release"
        ) from exc


def _require_runtime_matches(
    client,
    identity: ReleaseIdentity,
):
    try:
        runtime = client.runtime_release()
    except (
        OperatorAPIError,
        OperatorConfigurationError,
    ) as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_runtime_"
            "identity_unavailable"
        ) from exc

    if (
        not isinstance(runtime, dict)
        or runtime.get("available")
        is not True
        or runtime.get(
            "clean_worktree"
        )
        is not True
        or not isinstance(
            runtime.get("commit_sha"),
            str,
        )
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_runtime_"
            "identity_invalid"
        )

    runtime_sha = runtime[
        "commit_sha"
    ].strip().lower()

    if runtime_sha != identity.commit_sha:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_runtime_"
            "commit_mismatch"
        )


def _require_confirmations(
    confirmations: dict[str, bool],
):
    if set(confirmations) != set(
        CONFIRMATION_KEYS
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_explicit_"
            "confirmation_required"
        )

    if any(
        value is not True
        for value in confirmations.values()
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_explicit_"
            "confirmation_required"
        )

    return {
        key: True
        for key in CONFIRMATION_KEYS
    }


def _safe_pull(client, limit: int):
    try:
        client.status()
        result = client.pull_outlook(
            limit=limit
        )
    except (
        OperatorAPIError,
        OperatorConfigurationError,
    ) as exc:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_operator_pull_failed"
        ) from exc

    if not isinstance(result, dict):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_pull_invalid"
        )

    if (
        result.get("provider")
        != "microsoft_graph"
        or result.get("pull_status")
        != "complete"
        or result.get(
            "mailbox_write_performed"
        )
        is not False
        or result.get(
            "automated_send_performed"
        )
        is not False
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_prepare_"
            "pull_not_safe_complete"
        )

    return result


def _single_candidate(
    results,
    predicate,
):
    matches = []

    for item in results:
        if (
            isinstance(item, dict)
            and predicate(item)
        ):
            message_id = item.get(
                "external_message_id"
            )

            if (
                isinstance(
                    message_id,
                    str,
                )
                and message_id
            ):
                matches.append(message_id)

    if len(matches) != 1:
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_scenario_"
            "selection_ambiguous"
        )

    return matches[0]


def _scenario_ids(pull_result: dict):
    results = pull_result.get(
        "results"
    )

    if not isinstance(results, list):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_results_missing"
        )

    customer = _single_candidate(
        results,
        lambda item: (
            item.get("inbound_route")
            == "customer"
            and item.get(
                "ingestion_status"
            )
            in {
                "created",
                "duplicate_existing_proposal",
            }
            and bool(
                item.get("proposal_id")
            )
        ),
    )

    supplier = _single_candidate(
        results,
        lambda item: (
            item.get("inbound_route")
            == "supplier"
            and item.get(
                "ingestion_status"
            )
            in {
                "response_attached",
                "duplicate_response",
            }
        ),
    )

    wrong_sender = _single_candidate(
        results,
        lambda item: (
            item.get("inbound_route")
            == "manual_review"
            and item.get(
                "ingestion_status"
            )
            == "blocked"
            and item.get("reason_code")
            == (
                "sender_not_in_verified_"
                "inbound_scope"
            )
        ),
    )

    attachment = _single_candidate(
        results,
        lambda item: (
            item.get("inbound_route")
            == "manual_review"
            and item.get(
                "ingestion_status"
            )
            == "blocked"
            and item.get("reason_code")
            == (
                "outlook_attachments_"
                "not_supported"
            )
        ),
    )

    return {
        "trusted_customer": customer,
        "known_supplier_reply": supplier,
        "wrong_supplier_sender": (
            wrong_sender
        ),
        "attachment_manual_review": (
            attachment
        ),
    }


def prepare_live_smoke_manifest(
    *,
    client,
    release_identity: ReleaseIdentity,
    manifest_path: Path,
    pull_limit: int,
    confirmations: dict[str, bool],
):
    _require_confirmations(
        confirmations
    )
    _require_local_release(
        release_identity
    )
    _require_runtime_matches(
        client,
        release_identity,
    )

    pull = _safe_pull(
        client,
        pull_limit,
    )

    manifest = OutlookLiveSmokeManifest(
        pilot_commit_sha=(
            release_identity.commit_sha
        ),
        prepared_at=datetime.now(
            timezone.utc
        ),
        pull_limit=pull_limit,
        message_ids=_scenario_ids(pull),
    )

    write_manifest(
        manifest_path,
        manifest,
    )

    return manifest


def run_live_smoke(
    *,
    client,
    release_identity: ReleaseIdentity,
    manifest_path: Path,
    receipt_path: Path,
    confirmations: dict[str, bool],
):
    confirmed = _require_confirmations(
        confirmations
    )
    _require_local_release(
        release_identity
    )

    manifest = load_manifest(
        manifest_path
    )

    if (
        manifest.pilot_commit_sha
        != release_identity.commit_sha
    ):
        raise OutlookLiveSmokeRunnerError(
            "outlook_smoke_manifest_"
            "commit_mismatch"
        )

    _require_runtime_matches(
        client,
        release_identity,
    )

    pull = _safe_pull(
        client,
        manifest.pull_limit,
    )

    ids = manifest.message_ids

    evaluation = (
        evaluate_outlook_live_smoke_pull(
            pull,
            trusted_customer_message_id=(
                ids["trusted_customer"]
            ),
            known_supplier_message_id=(
                ids["known_supplier_reply"]
            ),
            wrong_supplier_message_id=(
                ids["wrong_supplier_sender"]
            ),
            attachment_message_id=(
                ids[
                    "attachment_manual_review"
                ]
            ),
        )
    )

    receipt = (
        build_outlook_live_smoke_receipt(
            evaluation,
            release_identity=(
                release_identity
            ),
            manifest_sha256=(
                manifest_sha256(
                    manifest_path
                )
            ),
            confirmations=confirmed,
        )
    )

    write_outlook_live_smoke_receipt(
        receipt_path,
        receipt,
    )

    return receipt


def _add_confirmations(parser):
    parser.add_argument(
        "--confirm-live-tenant-approved",
        action="store_true",
    )
    parser.add_argument(
        "--confirm-openai-data-use-approved",
        action="store_true",
    )
    parser.add_argument(
        "--confirm-four-test-messages-prepared",
        action="store_true",
    )
    parser.add_argument(
        "--confirm-no-autonomous-outbound",
        action="store_true",
    )


def _confirmations(args):
    return {
        "live_tenant_approved": (
            args.confirm_live_tenant_approved
        ),
        "openai_data_use_approved": (
            args.confirm_openai_data_use_approved
        ),
        "four_test_messages_prepared": (
            args.confirm_four_test_messages_prepared
        ),
        "no_autonomous_outbound": (
            args.confirm_no_autonomous_outbound
        ),
    }


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Controlled two-pass live Outlook "
            "smoke evidence runner."
        )
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    prepare = commands.add_parser(
        "prepare"
    )
    prepare.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    prepare.add_argument(
        "--limit",
        type=int,
        default=10,
        choices=range(4, 51),
        metavar="4-50",
    )
    _add_confirmations(prepare)

    run = commands.add_parser(
        "run"
    )
    run.add_argument(
        "--manifest",
        type=Path,
        required=True,
    )
    run.add_argument(
        "--receipt",
        type=Path,
        required=True,
    )
    _add_confirmations(run)

    return parser


def main(
    argv=None,
    *,
    client_factory=(
        PilotOperatorClient.from_environment
    ),
    release_identity_func=(
        collect_release_identity
    ),
):
    args = _parser().parse_args(argv)

    try:
        identity = (
            release_identity_func()
        )
        client = client_factory()

        if args.command == "prepare":
            prepare_live_smoke_manifest(
                client=client,
                release_identity=identity,
                manifest_path=(
                    args.manifest
                ),
                pull_limit=args.limit,
                confirmations=(
                    _confirmations(args)
                ),
            )

            print(
                "Live Outlook smoke prepare: PASS"
            )
            print(
                "External private manifest created."
            )
            return 0

        receipt = run_live_smoke(
            client=client,
            release_identity=identity,
            manifest_path=args.manifest,
            receipt_path=args.receipt,
            confirmations=(
                _confirmations(args)
            ),
        )

        for scenario, status in (
            receipt.scenarios.items()
        ):
            print(
                f"{status.upper()} {scenario}"
            )

        print(
            "Live Outlook smoke: "
            + receipt.result.upper()
        )

        return (
            0
            if receipt.result == "pass"
            else 1
        )

    except (
        OutlookLiveSmokeRunnerError,
        OutlookLiveSmokeReceiptError,
        ReplayReceiptError,
        OperatorAPIError,
        OperatorConfigurationError,
    ) as exc:
        code = getattr(
            exc,
            "code",
            "outlook_smoke_blocked",
        )

        print(
            f"Live Outlook smoke blocked: {code}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
