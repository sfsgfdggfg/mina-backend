"""Explicitly authorized execution adapter for pre-sanitized historical replay.

The provider-neutral replay harness remains offline-safe. This module is the
only CLI boundary that may call the production AI email parser, and only after
explicit human confirmations plus verified external operational data.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.ai.email_parser import (
    EmailParserUnavailableError,
    parse_email_with_ai,
)
from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.data_provenance import (
    DataProvenanceError,
    require_pilot_operational_dataset,
)
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.models import Shipment
from src.core.operational_data import (
    OperationalDataSourceConfigurationError,
    OperationalDataSources,
    operational_data_sources_from_environment,
)
from src.core.pilot_access import route_allowed
from src.core.privacy import (
    PrivacyBoundaryError,
    PrivacySafeText,
    prepare_privacy_safe_text,
)
from src.core.supplier_capability_validator import (
    validate_supplier_capabilities_file,
)
from src.simulation.sanitized_replay import (
    DISPOSITIONS,
    SCORED_FIELDS,
    ReplayActual,
    ReplayAggregateResult,
    ReplayCase,
    ReplayValidationError,
    load_cases,
    print_summary,
    replay_exit_code,
    run_replay,
)
from src.simulation.replay_receipt import (
    ReleaseIdentity,
    ReplayReceiptError,
    ReplaySourceIdentity,
    build_replay_receipt,
    collect_release_identity,
    collect_replay_source_identity,
    require_clean_release_identity,
    require_same_replay_source_identity,
    write_replay_receipt,
)
from src.workflow.pipeline import process_shipment


ParserCallable = Callable[[PrivacySafeText], ShipmentProposalSnapshot]
_REQUIRED_CONFIRMED_SAFETY_FIELDS = (
    "is_adr",
    "is_temperature_controlled",
    "is_high_value",
)


class AuthorizedReplayExecutionError(RuntimeError):
    """Safe execution block whose code contains no replay/customer values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validate_operational_sources(
    sources: OperationalDataSources,
) -> None:
    pilot_env = {"MINAI_PILOT_MODE": "true"}
    for dataset_key, dataset_path in (
        ("customer_memory", sources.customer_memory_path),
        ("supplier_capabilities", sources.supplier_capabilities_path),
    ):
        require_pilot_operational_dataset(
            dataset_key,
            environ=pilot_env,
            path=sources.provenance_registry_path,
            dataset_path=dataset_path,
        )

    customer = validate_customer_memory_file(
        sources.customer_memory_path
    )
    supplier = validate_supplier_capabilities_file(
        sources.supplier_capabilities_path
    )
    if customer.get("valid") is not True:
        raise AuthorizedReplayExecutionError(
            "customer_operational_data_invalid"
        )
    if supplier.get("valid") is not True:
        raise AuthorizedReplayExecutionError(
            "supplier_operational_data_invalid"
        )


def _assert_outbound_disabled() -> None:
    if route_allowed(
        "POST", "/supplier-rfqs/readiness-probe/send"
    ) or route_allowed(
        "POST", "/quotes/prepare-send"
    ):
        raise AuthorizedReplayExecutionError(
            "automated_outbound_must_remain_disabled"
        )


@contextmanager
def _pilot_mode() -> Iterator[None]:
    previous = os.environ.get("MINAI_PILOT_MODE")
    os.environ["MINAI_PILOT_MODE"] = "true"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("MINAI_PILOT_MODE", None)
        else:
            os.environ["MINAI_PILOT_MODE"] = previous


def _proposal_facts(
    proposal: ShipmentProposalSnapshot,
) -> dict[str, Any]:
    data = proposal.model_dump(mode="json")
    facts = {
        field_name: data.get(field_name)
        for field_name in SCORED_FIELDS
        if field_name in data
    }

    explicit_project_values = [
        proposal.commodity,
        proposal.equipment_type,
        proposal.special_notes,
    ]
    explicit_project_values.extend(
        package.package_type
        for package in proposal.packages
    )
    explicit_project_text = " ".join(
        str(value)
        for value in explicit_project_values
        if value
    ).lower()
    has_project_text = any(
        marker in explicit_project_text
        for marker in (
            "project cargo",
            "oversize",
            "lowbed",
            "heavy haul",
            "gabari",
            "proje yük",
            "proje yuk",
            "ağır yük",
            "agir yuk",
        )
    )
    has_oversize_dimensions = any(
        (
            package.width_cm is not None
            and package.width_cm > 250
        )
        or (
            package.height_cm is not None
            and package.height_cm > 300
        )
        for package in proposal.packages
    )
    if has_project_text or has_oversize_dimensions:
        facts["is_oversize_or_project"] = True

    return facts


def _confirmed_truth_shipment(
    case: ReplayCase,
) -> Shipment | None:
    for field_name in _REQUIRED_CONFIRMED_SAFETY_FIELDS:
        expected = case.expected.facts.get(field_name)
        if expected is None or expected.state != "known":
            return None

    values: dict[str, Any] = {}
    shipment_fields = set(Shipment.model_fields)
    for field_name, expected in case.expected.facts.items():
        if (
            field_name in shipment_fields
            and expected.state == "known"
        ):
            values[field_name] = expected.value

    try:
        return Shipment.model_validate(values)
    except ValueError as exc:
        raise AuthorizedReplayExecutionError(
            "operator_ground_truth_invalid"
        ) from exc


def _operational_disposition(
    result: dict[str, Any],
) -> str:
    result_type = result.get("result_type")
    if result_type in {
        "pilot_scope_excluded",
        "data_provenance_blocked",
        "supplier_rfq_approval_required",
    }:
        return str(result_type)

    quote_readiness = result.get("quote_readiness")
    quote_result_type = getattr(
        quote_readiness,
        "result_type",
        None,
    )
    if quote_result_type == "clarification":
        return "clarification_required"

    raise AuthorizedReplayExecutionError(
        "unsupported_operational_replay_disposition"
    )


def build_authorized_replay_actual(
    case: ReplayCase,
    *,
    parser: ParserCallable,
    operational_data_sources: OperationalDataSources,
) -> ReplayActual:
    transformed = prepare_privacy_safe_text(case.body_text)
    proposal = parser(transformed.safe_text)
    if not isinstance(proposal, ShipmentProposalSnapshot):
        raise AuthorizedReplayExecutionError(
            "parser_result_contract_invalid"
        )

    facts = _proposal_facts(proposal)
    confirmed_truth = _confirmed_truth_shipment(case)
    if confirmed_truth is None:
        return ReplayActual(
            facts=facts,
            disposition="extraction_confirmation_required",
            equipment=None,
            supplier_progressed=False,
        )

    result = process_shipment(
        confirmed_truth,
        email_text=str(transformed.safe_text),
        sender_address=case.sender_address,
        _persist_rfq_transition=False,
        operational_data_sources=operational_data_sources,
    )
    disposition = _operational_disposition(result)
    if disposition not in DISPOSITIONS:
        raise AuthorizedReplayExecutionError(
            "replay_disposition_contract_invalid"
        )

    equipment_decision = result.get("equipment_decision")
    equipment = getattr(
        equipment_decision,
        "selected_equipment",
        None,
    )
    supplier_progressed = bool(
        result.get("supplier_rfq_drafts")
    )
    return ReplayActual(
        facts=facts,
        disposition=disposition,
        equipment=equipment,
        supplier_progressed=supplier_progressed,
    )


def run_authorized_replay(
    cases: Iterable[ReplayCase],
    *,
    parser: ParserCallable,
    operational_data_sources: OperationalDataSources,
) -> ReplayAggregateResult:
    _validate_operational_sources(operational_data_sources)
    with _pilot_mode():
        _assert_outbound_disabled()
        return run_replay(
            cases,
            lambda case: build_authorized_replay_actual(
                case,
                parser=parser,
                operational_data_sources=(
                    operational_data_sources
                ),
            ),
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Execute an explicitly authorized replay of a "
            "pre-sanitized external historical JSONL dataset."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="external pre-sanitized JSONL path",
    )
    parser.add_argument(
        "--confirm-pre-sanitized",
        action="store_true",
        help=(
            "Confirm the input has already passed the approved "
            "human sanitization process."
        ),
    )
    parser.add_argument(
        "--confirm-openai-data-use-approved",
        action="store_true",
        help=(
            "Confirm organizational/legal approval exists for "
            "this sanitized replay to use the configured OpenAI service."
        ),
    )
    parser.add_argument(
        "--confirm-no-autonomous-outbound",
        action="store_true",
        help=(
            "Confirm supplier/customer outbound remains disabled "
            "for this replay."
        ),
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        help=(
            "Optional absolute external path for a create-only, "
            "commit-bound replay evidence receipt."
        ),
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    parser_func: ParserCallable | None = None,
    release_identity_func: Callable[[], ReleaseIdentity] = collect_release_identity,
) -> int:
    args = _parser().parse_args(argv)
    if not (
        args.confirm_pre_sanitized
        and args.confirm_openai_data_use_approved
        and args.confirm_no_autonomous_outbound
    ):
        print(
            "Authorized replay blocked: explicit_confirmation_required",
            file=sys.stderr,
        )
        return 2

    release_identity: ReleaseIdentity | None = None
    if args.receipt is not None:
        try:
            release_identity = release_identity_func()
            require_clean_release_identity(release_identity)
        except ReplayReceiptError as exc:
            print(
                f"Authorized replay blocked: {exc.code}",
                file=sys.stderr,
            )
            return 2

    source_identity: ReplaySourceIdentity | None = None
    try:
        sources = operational_data_sources_from_environment(
            require_external=True,
        )
        if args.receipt is not None:
            source_identity = collect_replay_source_identity(
                args.input,
                sources,
            )
        cases = load_cases(args.input)
        if source_identity is not None:
            require_same_replay_source_identity(
                source_identity,
                collect_replay_source_identity(args.input, sources),
            )
        result = run_authorized_replay(
            cases,
            parser=parser_func or parse_email_with_ai,
            operational_data_sources=sources,
        )
    except ReplayValidationError as exc:
        print(
            f"Authorized replay rejected: {exc}",
            file=sys.stderr,
        )
        return 2
    except (
        DataProvenanceError,
        OperationalDataSourceConfigurationError,
    ):
        print(
            "Authorized replay blocked: "
            "operational_data_not_verified",
            file=sys.stderr,
        )
        return 2
    except ReplayReceiptError as exc:
        print(
            f"Authorized replay blocked: {exc.code}",
            file=sys.stderr,
        )
        return 2
    except AuthorizedReplayExecutionError as exc:
        print(
            f"Authorized replay blocked: {exc.code}",
            file=sys.stderr,
        )
        return 2
    except (
        EmailParserUnavailableError,
        PrivacyBoundaryError,
        ValueError,
    ):
        print(
            "Authorized replay failed: "
            "ai_or_privacy_boundary_unavailable",
            file=sys.stderr,
        )
        return 3
    except Exception:
        print(
            "Authorized replay failed: execution_error",
            file=sys.stderr,
        )
        return 3

    if args.receipt is not None:
        try:
            current_identity = release_identity_func()
            require_clean_release_identity(current_identity)
            if (
                release_identity is None
                or current_identity.commit_sha != release_identity.commit_sha
            ):
                raise ReplayReceiptError("repository_changed_during_replay")
            if source_identity is None:
                raise ReplayReceiptError("replay_source_identity_unavailable")
            require_same_replay_source_identity(
                source_identity,
                collect_replay_source_identity(args.input, sources),
            )
            receipt = build_replay_receipt(
                result,
                input_path=args.input,
                operational_data_sources=sources,
                release_identity=release_identity,
                source_identity=source_identity,
            )
            write_replay_receipt(args.receipt, receipt)
        except ReplayReceiptError as exc:
            print(
                f"Authorized replay blocked: {exc.code}",
                file=sys.stderr,
            )
            return 2
        print("Replay evidence receipt written.")

    print_summary(result)
    return replay_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
