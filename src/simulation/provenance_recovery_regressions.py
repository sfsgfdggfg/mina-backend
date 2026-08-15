from __future__ import annotations

import json
import os
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.data_provenance import (
    calculate_dataset_sha256,
    require_pilot_operational_dataset,
)
from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    InMemoryExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Package, Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    confirm_extraction_proposal,
    resume_confirmed_extraction,
)
from src.workflow.supplier_rfq_progression import (
    SupplierRFQWorkflowProgressionError,
    resume_supplier_rfq_workflow,
)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Pilot Provenance Recovery",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=12000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-09-15",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=12,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )


def _proposal(repository) -> ShipmentExtractionProposal:
    proposed = repository.save(
        ShipmentExtractionProposal(
            inbound_mail=InboundMailEnvelope(
                body_text="Privacy-safe synthetic road freight inquiry.",
                privacy_transformed=True,
            ),
            proposed_shipment=ShipmentProposalSnapshot.model_validate(
                _shipment().model_dump()
            ),
        )
    )
    return confirm_extraction_proposal(
        repository=repository,
        proposal_id=proposed.proposal_id,
        operator_identity="provenance-recovery-regression",
    )


def _write_registry(
    registry_path: Path,
    *,
    fingerprint_matches: bool,
) -> None:
    data_dir = registry_path.parent
    supplier_path = data_dir / "supplier_capabilities.json"
    customer_path = data_dir / "customer_memory.json"
    supplier_path.write_text('[{"supplier_name":"Verified"}]', encoding="utf-8")
    customer_path.write_text("[]", encoding="utf-8")

    def fingerprint(path: Path) -> str:
        if fingerprint_matches:
            return calculate_dataset_sha256(path)
        return "0" * 64

    registry_path.write_text(
        json.dumps(
            {
                "version": 1,
                "datasets": {
                    "supplier_capabilities": {
                        "path": "data/supplier_capabilities.json",
                        "classification": "pilot_verified",
                        "operational": True,
                        "pilot_usable": True,
                        "verified_by": "Regression Data Owner",
                        "verified_at": "2026-08-13T18:00:00+03:00",
                        "verified_sha256": fingerprint(supplier_path),
                    },
                    "customer_memory": {
                        "path": "data/customer_memory.json",
                        "classification": "pilot_verified",
                        "operational": True,
                        "pilot_usable": True,
                        "verified_by": "Regression Data Owner",
                        "verified_at": "2026-08-13T18:00:00+03:00",
                        "verified_sha256": fingerprint(customer_path),
                    },
                },
            }
        ),
        encoding="utf-8",
    )


def _provenance_patches(registry_path: Path) -> ExitStack:
    stack = ExitStack()

    def require(
        dataset_key: str,
        *,
        environ=None,
        path=None,
        dataset_path=None,
        dataset_bytes=None,
    ):
        return require_pilot_operational_dataset(
            dataset_key,
            environ=environ,
            path=registry_path,
            dataset_path=dataset_path,
            dataset_bytes=dataset_bytes,
        )

    stack.enter_context(
        patch(
            "src.core.customer_memory.require_pilot_operational_dataset",
            side_effect=require,
        )
    )
    stack.enter_context(
        patch(
            "src.core.supplier_selection.require_pilot_operational_dataset",
            side_effect=require,
        )
    )
    return stack


def _assert_no_quote_artifacts(failures: list[str], result: dict) -> None:
    if result.get("supplier_rfq_drafts"):
        failures.append("provenance-blocked attempt created RFQ drafts")
    if any(
        result.get(key) is not None
        for key in (
            "supplier_quote_selection_decision",
            "supplier_quote",
            "customer_quote",
            "quote_approval",
            "quote_case",
        )
    ):
        failures.append("provenance-blocked attempt created quote artifacts")


def _blocked_result_builder_and_initial_path(
    failures: list[str],
    temp_root: Path,
) -> None:
    from src.workflow.pipeline import (
        build_data_provenance_blocked_result,
        process_shipment,
    )

    registry_path = temp_root / "initial" / "data" / "provenance_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{malformed", encoding="utf-8")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            direct = build_data_provenance_blocked_result(_shipment())
            initial = process_shipment(
                _shipment(),
                rfq_repository=InMemorySupplierRFQRepository(),
                approval_repository=InMemoryQuoteApprovalRepository(),
                quote_case_repository=InMemoryQuoteCaseRepository(),
            )

    for path_name, result in (("builder", direct), ("initial", initial)):
        if result.get("result_type") != "data_provenance_blocked":
            failures.append(
                f"malformed provenance escaped the {path_name} blocked result"
            )
        _assert_no_quote_artifacts(failures, result)


def _legacy_resume_state_is_fail_closed(failures: list[str]) -> None:
    repository = InMemoryExtractionProposalRepository()
    confirmed = _proposal(repository)
    legacy_payload = confirmed.model_dump(
        exclude={
            "resume_status",
            "resume_attempt_count",
            "unknown_fields",
            "unknown_safety_fields",
        }
    )
    legacy_payload["resume_started_at"] = datetime.now(timezone.utc)
    legacy = ShipmentExtractionProposal.model_validate(legacy_payload)
    repository.save(legacy)

    if (
        legacy.resume_status != "in_progress"
        or legacy.resume_attempt_count != 1
    ):
        failures.append("legacy started resume was not inferred as in progress")
    try:
        resume_confirmed_extraction(
            repository=repository,
            proposal_id=legacy.proposal_id,
            rfq_repository=InMemorySupplierRFQRepository(),
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
        )
    except ExtractionConfirmationTransitionError:
        pass
    else:
        failures.append("legacy in-progress resume was retried automatically")


def _extraction_malformed_recovery(
    failures: list[str],
    temp_root: Path,
) -> None:
    db_path = temp_root / "extraction.sqlite3"
    store = SQLitePilotStore(db_path, run_id="p0-9")
    proposals = SQLiteExtractionProposalRepository(store)
    rfqs = SQLiteSupplierRFQRepository(store)
    approvals = SQLiteQuoteApprovalRepository(store)
    cases = SQLiteQuoteCaseRepository(store)
    confirmed = _proposal(proposals)
    registry_path = temp_root / "malformed" / "data" / "provenance_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{malformed", encoding="utf-8")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            blocked = resume_confirmed_extraction(
                repository=proposals,
                proposal_id=confirmed.proposal_id,
                rfq_repository=rfqs,
                approval_repository=approvals,
                quote_case_repository=cases,
                evidence_recorder=store,
            )

    retry_store = SQLitePilotStore(db_path, run_id="p0-9-retry")
    proposals = SQLiteExtractionProposalRepository(retry_store)
    rfqs = SQLiteSupplierRFQRepository(retry_store)
    approvals = SQLiteQuoteApprovalRepository(retry_store)
    cases = SQLiteQuoteCaseRepository(retry_store)
    durable_block = proposals.get(confirmed.proposal_id)
    if blocked.get("result_type") != "data_provenance_blocked":
        failures.append("malformed provenance did not return a stable block")
    _assert_no_quote_artifacts(failures, blocked)
    if rfqs.list_drafts() or approvals.list_all() or cases.list_all():
        failures.append("malformed provenance persisted downstream artifacts")
    if (
        durable_block is None
        or durable_block.resume_status != "provenance_blocked"
        or durable_block.last_resume_blocked_result_type
        != "data_provenance_blocked"
        or durable_block.resumed_at is not None
    ):
        failures.append("extraction provenance block was not durably retryable")

    _write_registry(registry_path, fingerprint_matches=True)
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            recovered = resume_confirmed_extraction(
                repository=proposals,
                proposal_id=confirmed.proposal_id,
                rfq_repository=rfqs,
                approval_repository=approvals,
                quote_case_repository=cases,
                evidence_recorder=retry_store,
            )
    completed = proposals.get(confirmed.proposal_id)
    draft_count = len(rfqs.list_drafts())
    if recovered.get("result_type") == "data_provenance_blocked":
        failures.append("repaired extraction provenance did not recover")
    if (
        completed is None
        or completed.resume_status != "completed"
        or completed.resume_attempt_count != 2
        or completed.resumed_at is None
    ):
        failures.append("successful extraction retry was not completed once")
    try:
        resume_confirmed_extraction(
            repository=proposals,
            proposal_id=confirmed.proposal_id,
            rfq_repository=rfqs,
            approval_repository=approvals,
            quote_case_repository=cases,
        )
    except ExtractionConfirmationTransitionError:
        pass
    else:
        failures.append("completed extraction allowed a duplicate retry")
    if len(rfqs.list_drafts()) != draft_count:
        failures.append("completed extraction retry duplicated RFQ drafts")


def _fingerprint_mismatch_recovery(
    failures: list[str],
    temp_root: Path,
) -> None:
    proposals = InMemoryExtractionProposalRepository()
    rfqs = InMemorySupplierRFQRepository()
    confirmed = _proposal(proposals)
    registry_path = temp_root / "mismatch" / "data" / "provenance_registry.json"
    registry_path.parent.mkdir(parents=True)
    _write_registry(registry_path, fingerprint_matches=False)

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            blocked = resume_confirmed_extraction(
                repository=proposals,
                proposal_id=confirmed.proposal_id,
                rfq_repository=rfqs,
                approval_repository=InMemoryQuoteApprovalRepository(),
                quote_case_repository=InMemoryQuoteCaseRepository(),
            )
    if blocked.get("result_type") != "data_provenance_blocked":
        failures.append("fingerprint mismatch did not block extraction resume")
    _write_registry(registry_path, fingerprint_matches=True)
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            recovered = resume_confirmed_extraction(
                repository=proposals,
                proposal_id=confirmed.proposal_id,
                rfq_repository=rfqs,
                approval_repository=InMemoryQuoteApprovalRepository(),
                quote_case_repository=InMemoryQuoteCaseRepository(),
            )
    if recovered.get("result_type") == "data_provenance_blocked":
        failures.append("fingerprint repair did not permit extraction retry")


def _rfq_progression_recovery(failures: list[str], temp_root: Path) -> None:
    db_path = temp_root / "rfq.sqlite3"
    store = SQLitePilotStore(db_path, run_id="p0-9-rfq")
    repository = SQLiteSupplierRFQRepository(store)
    approvals = SQLiteQuoteApprovalRepository(store)
    cases = SQLiteQuoteCaseRepository(store)
    workflow = SupplierRFQWorkflow(shipment=_shipment())
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Verified Regression Supplier",
        priority=1,
        subject="Synthetic RFQ",
        body="Synthetic RFQ body",
        status="responded",
    )
    workflow.rfq_ids = [draft.rfq_id]
    repository.save_workflow(workflow)
    repository.save_drafts([draft])
    repository.save_responses(
        [
            SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=1,
                status="quoted",
                cost=1000,
                currency="EUR",
            )
        ]
    )
    registry_path = temp_root / "rfq" / "data" / "provenance_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{malformed", encoding="utf-8")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            blocked = resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=repository,
                approval_repository=approvals,
                quote_case_repository=cases,
            )
    retry_store = SQLitePilotStore(db_path, run_id="p0-9-rfq-retry")
    repository = SQLiteSupplierRFQRepository(retry_store)
    approvals = SQLiteQuoteApprovalRepository(retry_store)
    cases = SQLiteQuoteCaseRepository(retry_store)
    durable_block = repository.get_workflow(workflow.workflow_id)
    if blocked.get("result_type") != "data_provenance_blocked":
        failures.append("RFQ progression provenance failure was not explicit")
    if approvals.list_all() or cases.list_all():
        failures.append("blocked RFQ progression persisted quote artifacts")
    if (
        durable_block is None
        or durable_block.quote_progression_status != "provenance_blocked"
        or durable_block.last_provenance_blocked_result_type
        != "data_provenance_blocked"
    ):
        failures.append("RFQ progression block was not durably retryable")

    _write_registry(registry_path, fingerprint_matches=True)
    supplier_selection = {
        "selected_suppliers": [
            {
                "supplier_name": draft.supplier_name,
                "priority": 1,
                "route_score": 1.0,
                "equipment_score": 1.0,
                "risk_score": 1.0,
                "price_score": 0.8,
                "speed_score": 0.8,
                "total_score": 0.9,
            }
        ],
        "rejected_suppliers": [],
        "source": "provenance_recovery_regression",
    }
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        with _provenance_patches(registry_path):
            with patch(
                "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
                return_value=supplier_selection,
            ):
                recovered = resume_supplier_rfq_workflow(
                    workflow_id=workflow.workflow_id,
                    rfq_repository=repository,
                    approval_repository=approvals,
                    quote_case_repository=cases,
                )
    completed = repository.get_workflow(workflow.workflow_id)
    if recovered.get("quote_case") is None:
        failures.append("repaired RFQ provenance did not continue to quote")
    if (
        completed is None
        or completed.quote_progression_status != "completed"
        or completed.quote_progression_attempt_count != 2
    ):
        failures.append("RFQ retry did not persist one successful completion")
    approval_count = len(approvals.list_all())
    case_count = len(cases.list_all())
    try:
        resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=repository,
            approval_repository=approvals,
            quote_case_repository=cases,
        )
    except SupplierRFQWorkflowProgressionError:
        pass
    else:
        failures.append("completed RFQ progression allowed a duplicate retry")
    if (
        len(approvals.list_all()) != approval_count
        or len(cases.list_all()) != case_count
    ):
        failures.append("completed RFQ retry duplicated quote artifacts")


def _api_and_development_behavior(
    failures: list[str],
    temp_root: Path,
) -> None:
    from src import api
    from src.workflow.pipeline import process_shipment

    proposals = InMemoryExtractionProposalRepository()
    confirmed = _proposal(proposals)
    registry_path = temp_root / "api" / "data" / "provenance_registry.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("{malformed", encoding="utf-8")
    original = (
        api.extraction_proposal_repository,
        api.supplier_rfq_repository,
        api.quote_approval_repository,
        api.quote_case_repository,
        api.pilot_store,
    )
    api.extraction_proposal_repository = proposals
    api.supplier_rfq_repository = InMemorySupplierRFQRepository()
    api.quote_approval_repository = InMemoryQuoteApprovalRepository()
    api.quote_case_repository = InMemoryQuoteCaseRepository()
    api.pilot_store = None
    try:
        with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
            with _provenance_patches(registry_path):
                result = api.resume_extraction_proposal_endpoint(
                    confirmed.proposal_id
                )
        if result.get("result_type") != "data_provenance_blocked":
            failures.append("API did not serialize the provenance block")
        reason = (result.get("supplier_selection") or {}).get(
            "provenance_reason"
        )
        if reason is None or "malformed" in reason or "/" in reason:
            failures.append("API exposed provenance exception internals")

        api_workflow = SupplierRFQWorkflow(shipment=_shipment())
        api.supplier_rfq_repository.save_workflow(api_workflow)
        with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
            with _provenance_patches(registry_path):
                quote_result = api.resume_supplier_rfq_quote(
                    api_workflow.workflow_id
                )
        if quote_result.get("result_type") != "data_provenance_blocked":
            failures.append("RFQ resume API did not serialize provenance block")
    finally:
        (
            api.extraction_proposal_repository,
            api.supplier_rfq_repository,
            api.quote_approval_repository,
            api.quote_case_repository,
            api.pilot_store,
        ) = original

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        development = process_shipment(_shipment())
    if development.get("result_type") == "data_provenance_blocked":
        failures.append("valid development workflow gained pilot enforcement")


def evaluate_provenance_recovery_regressions() -> dict:
    failures: list[str] = []
    with TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        _blocked_result_builder_and_initial_path(failures, temp_root)
        _extraction_malformed_recovery(failures, temp_root)
        _fingerprint_mismatch_recovery(failures, temp_root)
        _rfq_progression_recovery(failures, temp_root)
        _api_and_development_behavior(failures, temp_root)
        _legacy_resume_state_is_fail_closed(failures)
    return {
        "name": "Durable provenance failure recovery",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    regression = evaluate_provenance_recovery_regressions()
    print(json.dumps(regression, indent=2))
    raise SystemExit(0 if regression["passed"] else 1)
