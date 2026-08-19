"""Safe aggregate evidence for a controlled live Outlook smoke test."""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from src.paths import REPO_ROOT
from src.simulation.replay_receipt import (
    ReleaseIdentity,
    ReplayReceiptError,
    require_clean_release_identity,
)


OUTLOOK_LIVE_SMOKE_SCHEMA_VERSION = 1

SCENARIOS = (
    "trusted_customer",
    "known_supplier_reply",
    "wrong_supplier_sender",
    "attachment_manual_review",
)

CONFIRMATION_KEYS = (
    "live_tenant_approved",
    "openai_data_use_approved",
    "four_test_messages_prepared",
    "no_autonomous_outbound",
)

_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class OutlookLiveSmokeReceiptError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class OutlookLiveSmokeEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: Literal["pass", "fail"]
    scenarios: dict[
        str,
        Literal["pass", "fail"],
    ]
    failed_scenarios: list[str] = Field(
        default_factory=list
    )
    pull_status: str
    fetched_message_count: int = Field(ge=0)
    handled_message_count: int = Field(ge=0)
    mailbox_write_performed: bool
    automated_send_performed: bool

    @field_validator("scenarios")
    @classmethod
    def exact_scenarios(cls, value):
        if set(value) != set(SCENARIOS):
            raise ValueError(
                "invalid smoke scenario set"
            )
        return value

    @model_validator(mode="after")
    def result_reconciles(self):
        failures = sorted(
            name
            for name, status
            in self.scenarios.items()
            if status == "fail"
        )

        if (
            sorted(self.failed_scenarios)
            != failures
        ):
            raise ValueError(
                "failed scenario summary "
                "does not reconcile"
            )

        should_pass = (
            not failures
            and self.pull_status == "complete"
            and (
                self.mailbox_write_performed
                is False
            )
            and (
                self.automated_send_performed
                is False
            )
        )

        if (
            (self.result == "pass")
            != should_pass
        ):
            raise ValueError(
                "smoke evaluation result "
                "does not reconcile"
            )

        return self


class OutlookLiveSmokeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = (
        OUTLOOK_LIVE_SMOKE_SCHEMA_VERSION
    )
    pilot_commit_sha: str
    manifest_sha256: str
    completed_at: datetime
    result: Literal["pass", "fail"]
    provider: Literal[
        "microsoft_graph"
    ] = "microsoft_graph"
    scenario_count: Literal[4] = 4
    scenarios: dict[
        str,
        Literal["pass", "fail"],
    ]
    failed_scenarios: list[str]
    pull_status: str
    fetched_message_count: int = Field(ge=0)
    handled_message_count: int = Field(ge=0)
    confirmations: dict[str, Literal[True]]
    mailbox_write_performed: Literal[
        False
    ] = False
    automated_send_performed: Literal[
        False
    ] = False

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

    @field_validator("manifest_sha256")
    @classmethod
    def valid_manifest_hash(
        cls,
        value: str,
    ):
        normalized = value.strip().lower()

        if not _SHA256_RE.fullmatch(
            normalized
        ):
            raise ValueError(
                "invalid manifest sha256"
            )

        return normalized

    @field_validator("scenarios")
    @classmethod
    def exact_receipt_scenarios(
        cls,
        value,
    ):
        if set(value) != set(SCENARIOS):
            raise ValueError(
                "invalid smoke scenario set"
            )
        return value

    @field_validator("confirmations")
    @classmethod
    def exact_confirmations(
        cls,
        value,
    ):
        if set(value) != set(
            CONFIRMATION_KEYS
        ):
            raise ValueError(
                "invalid confirmation set"
            )

        if any(
            item is not True
            for item in value.values()
        ):
            raise ValueError(
                "all confirmations are required"
            )

        return value

    @model_validator(mode="after")
    def receipt_reconciles(self):
        failures = sorted(
            name
            for name, status
            in self.scenarios.items()
            if status == "fail"
        )

        if (
            sorted(self.failed_scenarios)
            != failures
        ):
            raise ValueError(
                "receipt failed scenarios "
                "do not reconcile"
            )

        should_pass = (
            not failures
            and self.pull_status == "complete"
        )

        if (
            (self.result == "pass")
            != should_pass
        ):
            raise ValueError(
                "receipt result does not reconcile"
            )

        return self


def _result_index(
    pull_result: dict,
) -> dict[str, dict]:
    raw_results = pull_result.get("results")

    if not isinstance(raw_results, list):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_results_missing"
        )

    indexed = {}

    for item in raw_results:
        if not isinstance(item, dict):
            raise OutlookLiveSmokeReceiptError(
                "outlook_smoke_result_invalid"
            )

        message_id = item.get(
            "external_message_id"
        )

        if (
            not isinstance(message_id, str)
            or not message_id
        ):
            raise OutlookLiveSmokeReceiptError(
                "outlook_smoke_message_id_missing"
            )

        if message_id in indexed:
            raise OutlookLiveSmokeReceiptError(
                "outlook_smoke_duplicate_message_id"
            )

        indexed[message_id] = item

    return indexed


def _trusted_customer_passes(item):
    return bool(
        item
        and item.get("inbound_route")
        == "customer"
        and item.get("ingestion_status")
        in {
            "created",
            "duplicate_existing_proposal",
        }
        and item.get("proposal_id")
    )


def _known_supplier_passes(item):
    if not item:
        return False

    if (
        item.get("inbound_route")
        != "supplier"
    ):
        return False

    status = item.get(
        "ingestion_status"
    )

    if status == "response_attached":
        return bool(item.get("rfq_id"))

    return status == "duplicate_response"


def _wrong_supplier_passes(item):
    return bool(
        item
        and item.get("inbound_route")
        == "manual_review"
        and item.get("ingestion_status")
        == "blocked"
        and item.get("reason_code")
        == (
            "sender_not_in_verified_"
            "inbound_scope"
        )
    )


def _attachment_passes(item):
    return bool(
        item
        and item.get("inbound_route")
        == "manual_review"
        and item.get("ingestion_status")
        == "blocked"
        and item.get("reason_code")
        == "outlook_attachments_not_supported"
    )


def evaluate_outlook_live_smoke_pull(
    pull_result: dict,
    *,
    trusted_customer_message_id: str,
    known_supplier_message_id: str,
    wrong_supplier_message_id: str,
    attachment_message_id: str,
):
    if not isinstance(pull_result, dict):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_pull_invalid"
        )

    if (
        pull_result.get("provider")
        != "microsoft_graph"
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_provider_invalid"
        )

    ids = (
        trusted_customer_message_id,
        known_supplier_message_id,
        wrong_supplier_message_id,
        attachment_message_id,
    )

    if any(
        not isinstance(value, str)
        or not value.strip()
        for value in ids
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_expected_"
            "message_id_invalid"
        )

    if len(set(ids)) != 4:
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_expected_"
            "message_ids_not_unique"
        )

    indexed = _result_index(pull_result)

    checks = {
        "trusted_customer": (
            _trusted_customer_passes(
                indexed.get(
                    trusted_customer_message_id
                )
            )
        ),
        "known_supplier_reply": (
            _known_supplier_passes(
                indexed.get(
                    known_supplier_message_id
                )
            )
        ),
        "wrong_supplier_sender": (
            _wrong_supplier_passes(
                indexed.get(
                    wrong_supplier_message_id
                )
            )
        ),
        "attachment_manual_review": (
            _attachment_passes(
                indexed.get(
                    attachment_message_id
                )
            )
        ),
    }

    scenarios = {
        name: (
            "pass" if passed else "fail"
        )
        for name, passed in checks.items()
    }

    failures = sorted(
        name
        for name, status
        in scenarios.items()
        if status == "fail"
    )

    pull_status = str(
        pull_result.get("pull_status")
        or "unknown"
    )

    mailbox_write = pull_result.get(
        "mailbox_write_performed"
    )
    automated_send = pull_result.get(
        "automated_send_performed"
    )

    fetched = pull_result.get(
        "fetched_message_count",
        0,
    )
    handled = pull_result.get(
        "handled_message_count",
        0,
    )

    if (
        isinstance(fetched, bool)
        or not isinstance(fetched, int)
        or fetched < 0
        or isinstance(handled, bool)
        or not isinstance(handled, int)
        or handled < 0
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_counts_invalid"
        )

    overall_pass = (
        not failures
        and pull_status == "complete"
        and mailbox_write is False
        and automated_send is False
    )

    return OutlookLiveSmokeEvaluation(
        result=(
            "pass"
            if overall_pass
            else "fail"
        ),
        scenarios=scenarios,
        failed_scenarios=failures,
        pull_status=pull_status,
        fetched_message_count=fetched,
        handled_message_count=handled,
        mailbox_write_performed=bool(
            mailbox_write
        ),
        automated_send_performed=bool(
            automated_send
        ),
    )


def build_outlook_live_smoke_receipt(
    evaluation,
    *,
    release_identity: ReleaseIdentity,
    manifest_sha256: str,
    confirmations: dict[str, bool],
    completed_at: datetime | None = None,
):
    try:
        require_clean_release_identity(
            release_identity
        )
    except ReplayReceiptError as exc:
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "requires_clean_release"
        ) from exc

    if (
        evaluation.mailbox_write_performed
        or evaluation.automated_send_performed
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_outbound_"
            "invariant_failed"
        )

    return OutlookLiveSmokeReceipt(
        pilot_commit_sha=(
            release_identity.commit_sha
        ),
        manifest_sha256=manifest_sha256,
        completed_at=(
            completed_at
            or datetime.now(timezone.utc)
        ),
        result=evaluation.result,
        scenarios=dict(
            evaluation.scenarios
        ),
        failed_scenarios=list(
            evaluation.failed_scenarios
        ),
        pull_status=(
            evaluation.pull_status
        ),
        fetched_message_count=(
            evaluation.fetched_message_count
        ),
        handled_message_count=(
            evaluation.handled_message_count
        ),
        confirmations={
            key: value
            for key, value
            in confirmations.items()
        },
    )


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


def _outside_repository_destination(
    path: Path,
):
    candidate = path.expanduser()

    if not candidate.is_absolute():
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "path_must_be_absolute"
        )

    if _path_has_symlink(
        candidate.parent
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "symlink_forbidden"
        )

    try:
        parent = candidate.parent.resolve(
            strict=True
        )
    except (OSError, RuntimeError) as exc:
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "parent_unavailable"
        ) from exc

    destination = parent / candidate.name

    try:
        destination.relative_to(
            REPO_ROOT.resolve()
        )
    except ValueError:
        return destination

    raise OutlookLiveSmokeReceiptError(
        "outlook_smoke_receipt_"
        "inside_repository"
    )


def write_outlook_live_smoke_receipt(
    path: Path,
    receipt,
):
    destination = (
        _outside_repository_destination(
            path
        )
    )

    if (
        destination.exists()
        or destination.is_symlink()
    ):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "already_exists"
        )

    payload = (
        json.dumps(
            receipt.model_dump(mode="json"),
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

    temp_path = Path(temp_name)

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
                temp_path,
                destination,
            )
        except FileExistsError as exc:
            raise OutlookLiveSmokeReceiptError(
                "outlook_smoke_receipt_"
                "already_exists"
            ) from exc

        if os.name == "posix":
            destination.chmod(0o600)

    except OutlookLiveSmokeReceiptError:
        raise

    except OSError as exc:
        destination.unlink(
            missing_ok=True
        )
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "write_failed"
        ) from exc

    finally:
        temp_path.unlink(
            missing_ok=True
        )

    return destination


def load_outlook_live_smoke_receipt(
    path: Path,
):
    candidate = path.expanduser()

    if not candidate.is_absolute():
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "path_must_be_absolute"
        )

    if _path_has_symlink(candidate):
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "symlink_forbidden"
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
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_unreadable"
        ) from exc

    else:
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_"
            "inside_repository"
        )

    try:
        raw = json.loads(
            resolved.read_text(
                encoding="utf-8"
            )
        )
        return (
            OutlookLiveSmokeReceipt
            .model_validate(raw)
        )

    except Exception as exc:
        raise OutlookLiveSmokeReceiptError(
            "outlook_smoke_receipt_invalid"
        ) from exc
