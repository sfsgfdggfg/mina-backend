"""Deterministic offline rehearsal of the controlled shadow-pilot lifecycle."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import tempfile
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, TextIO
from unittest.mock import patch

from fastapi import HTTPException, Request

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.models import Package, Shipment
from src.core.operational_data import OperationalDataSources
from src.core.pilot_access import authorize_pilot_request, validate_pilot_configuration
from src.core.pilot_store import DEFAULT_PILOT_DB_PATH, SQLitePilotStore
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteMinaJobRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    resume_confirmed_extraction,
)
from src.workflow.mail_ingestion import process_customer_inquiry_mail
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow


OPERATOR = "Synthetic Pilot Operator"
CLAIMED_OPERATOR = "Untrusted Body Actor"
TOKEN = "synthetic-rehearsal-token-not-a-secret-0001"
VERIFIED_AT = "2026-08-14T00:00:00+00:00"


@dataclass
class RehearsalResult:
    passed: bool = False
    stage: str = "initialization"
    checks: dict[str, bool] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None

    def require(self, name: str, condition: bool) -> None:
        self.checks[name] = bool(condition)
        if not condition:
            raise RehearsalFailure(name)


class RehearsalFailure(RuntimeError):
    """A safe, stage-only rehearsal failure."""


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_synthetic_sources(root: Path) -> OperationalDataSources:
    customer_path = root / "customer_memory.json"
    supplier_path = root / "supplier_capabilities.json"
    registry_path = root / "provenance_registry.json"
    customer_bytes = json.dumps(
        [
            {
                "customer_name": "Synthetic Textile Customer",
                "active": True,
                "trusted_sender_addresses": [
                    "logistics@customer.invalid"
                ],
                "trusted_sender_domains": [
                    "customer.invalid"
                ],
                "default_commodity": "Tekstil",
                "default_equipment_type": "Tenteli",
            },
            {
                "customer_name": "Synthetic Backup Customer",
                "active": True,
                "trusted_sender_addresses": [
                    "ops@backup-customer.invalid"
                ],
                "trusted_sender_domains": [
                    "backup-customer.invalid"
                ],
                "default_commodity": "Tekstil",
                "default_equipment_type": "Tenteli",
            },
        ],
        sort_keys=True,
    ).encode("utf-8")
    suppliers = []
    for priority, name in enumerate(
        (
            "Synthetic Carrier A",
            "Synthetic Carrier B",
            "Synthetic Carrier C",
        ),
        1,
    ):
        suppliers.append({
            "supplier_name": name,
            "active": True,
            "role": "primary" if priority == 1 else "backup",
            "countries": ["Türkiye", "Almanya"],
            "equipment_types": ["Tenteli"],
            "service_types": ["FTL"],
            "route_regions": ["international"],
            "special_capabilities": [],
            "priority_routes": [],
            "reliability_score": 0.95 - priority / 100,
            "price_score": 0.85,
            "speed_score": 0.8,
            "notes": "Synthetic rehearsal supplier only.",
            "contacts": [{
                "email": f"quotes-{priority}@carrier.invalid",
                "active": True,
                "is_primary": True,
            }],
        })
    supplier_bytes = json.dumps(suppliers, sort_keys=True).encode("utf-8")
    customer_path.write_bytes(customer_bytes)
    supplier_path.write_bytes(supplier_bytes)

    def record(path: Path, content: bytes) -> dict[str, Any]:
        return {
            "path": str(path),
            "classification": "pilot_verified",
            "operational": True,
            "pilot_usable": True,
            "verified_by": "Synthetic Rehearsal Verifier",
            "verified_at": VERIFIED_AT,
            "verified_sha256": _sha256(content),
        }

    registry_path.write_text(json.dumps({
        "version": 1,
        "datasets": {
            "customer_memory": record(customer_path, customer_bytes),
            "supplier_capabilities": record(supplier_path, supplier_bytes),
        },
    }, sort_keys=True), encoding="utf-8")
    return OperationalDataSources(
        provenance_registry_path=registry_path,
        customer_memory_path=customer_path,
        supplier_capabilities_path=supplier_path,
    )


def _snapshot(*, adr: bool = False, reefer: bool = False) -> ShipmentProposalSnapshot:
    return ShipmentProposalSnapshot(
        customer_name="Synthetic Textile Customer",
        pickup_country="Türkiye",
        pickup_city="Istanbul",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=20_000,
        equipment_type="Tenteli",
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-08-20",
        required_delivery_date="2026-08-27",
        packages=[
            Package(
                package_type="pallet",
                quantity=10,
                length_cm=120,
                width_cm=80,
                height_cm=160,
                weight_kg=2000,
            )
        ],
        is_adr=adr,
        is_temperature_controlled=reefer,
        is_high_value=False,
    )


def _request(operator: str) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = operator
    return request


@contextmanager
def _api_repositories(api_module: Any, store: SQLitePilotStore) -> Iterator[None]:
    replacements = {
        "pilot_store": store,
        "extraction_proposal_repository": SQLiteExtractionProposalRepository(store),
        "mina_job_repository": SQLiteMinaJobRepository(store),
        "supplier_rfq_repository": SQLiteSupplierRFQRepository(store),
        "quote_approval_repository": SQLiteQuoteApprovalRepository(store),
        "quote_case_repository": SQLiteQuoteCaseRepository(store),
        "outbound_mail_sender": None,
    }
    originals = {name: getattr(api_module, name) for name in replacements}
    try:
        for name, value in replacements.items():
            setattr(api_module, name, value)
        yield
    finally:
        for name, value in originals.items():
            setattr(api_module, name, value)


def _expect_http(status: int, function, *args, **kwargs) -> bool:
    try:
        function(*args, **kwargs)
    except HTTPException as exc:
        return exc.status_code == status
    return False


def _expect_exception(exception_type, function, *args, **kwargs) -> bool:
    try:
        function(*args, **kwargs)
    except exception_type:
        return True
    return False


def _blocked_connection(*args, **kwargs):
    raise RehearsalFailure("network isolation")


@contextmanager
def _without_openai_key() -> Iterator[None]:
    present = "OPENAI_API_KEY" in os.environ
    value = os.environ.pop("OPENAI_API_KEY", None)
    try:
        yield
    finally:
        if present and value is not None:
            os.environ["OPENAI_API_KEY"] = value


def _run(root: Path, result: RehearsalResult, *, injected_failure: str | None) -> None:
    sources = _write_synthetic_sources(root)
    db_path = root / "synthetic-pilot.sqlite3"
    result.evidence["db_path"] = str(db_path)
    result.require("temporary DB only", db_path != DEFAULT_PILOT_DB_PATH and root in db_path.parents)
    result.require("exact source paths", all(path.parent == root for path in (
        sources.customer_memory_path,
        sources.supplier_capabilities_path,
        sources.provenance_registry_path,
    )))
    registry = json.loads(sources.provenance_registry_path.read_text(encoding="utf-8"))
    result.require("synthetic provenance", all(
        item["classification"] == "pilot_verified"
        and item["pilot_usable"] is True
        and item["verified_by"] == "Synthetic Rehearsal Verifier"
        and item["verified_at"] == VERIFIED_AT
        and Path(item["path"]).is_absolute()
        for item in registry["datasets"].values()
    ))

    env = {
        "MINAI_PILOT_MODE": "true",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps({OPERATOR: TOKEN}),
        "MINAI_PILOT_DB_PATH": str(db_path),
    }
    result.require("no OPENAI_API_KEY", "OPENAI_API_KEY" not in os.environ)
    validate_pilot_configuration(env)
    auth = authorize_pilot_request(
        method="GET", path="/quote-cases/example", client_host="127.0.0.1",
        authorization=f"Bearer {TOKEN}", environ=env,
    )
    result.require("pilot authentication", auth.allowed and auth.operator_name == OPERATOR)
    authenticated_operator = auth.operator_name
    result.require("authenticated synthetic operator", bool(authenticated_operator)
                   and authenticated_operator == OPERATOR)
    result.require("body identity conflicts with authenticated identity",
                   CLAIMED_OPERATOR != authenticated_operator)
    trusted_request = _request(authenticated_operator)
    supplier_send_allowed = authorize_pilot_request(
        method="POST", path="/supplier-rfqs/example/send", client_host="127.0.0.1",
        authorization=f"Bearer {TOKEN}", environ=env,
    ).allowed
    customer_send_blocked = not authorize_pilot_request(
        method="POST", path="/quotes/prepare-send", client_host="127.0.0.1",
        authorization=f"Bearer {TOKEN}", environ=env,
    ).allowed
    result.require(
        "controlled outbound surface",
        supplier_send_allowed and customer_send_blocked,
    )

    with patch.dict(os.environ, env, clear=False):
        from src import api
    store = SQLitePilotStore(db_path, run_id="synthetic-rehearsal")
    with _api_repositories(api, store):
        mail = InboundMailEnvelope(
            body_text="Synthetic freight inquiry; no real customer data.",
            sender_address="logistics@customer.invalid",
            sender_name="Synthetic Contact",
            subject="Synthetic Türkiye Germany FTL inquiry",
            external_message_id="synthetic-message-001",
            source="manual",
        )
        proposal_result = process_customer_inquiry_mail(
            mail=mail,
            shipment_parser=lambda _safe_text: _snapshot(),
            proposal_repository=api.extraction_proposal_repository,
        )
        proposal = proposal_result["extraction_proposal"]
        result.require("extraction proposal", proposal.extraction_status == "proposed")
        result.require("no RFQ before confirmation", not api.supplier_rfq_repository.list_drafts())
        result.require("unconfirmed extraction blocked", _expect_exception(
            ExtractionConfirmationTransitionError,
            resume_confirmed_extraction,
            repository=api.extraction_proposal_repository,
            proposal_id=proposal.proposal_id,
            rfq_repository=api.supplier_rfq_repository,
            operational_data_sources=sources,
        ))
        confirmed = api.confirm_extraction_proposal_endpoint(
            proposal.proposal_id,
            api.ConfirmExtractionRequest(operator_identity=CLAIMED_OPERATOR, corrections={}),
            trusted_request,
        )
        result.require("authenticated authority overrides body", confirmed["confirmed_by"] == authenticated_operator
                       and confirmed["confirmed_at"] is not None)
        if injected_failure == "after-confirmation":
            raise RehearsalFailure("injected failure")
        resumed = resume_confirmed_extraction(
            repository=api.extraction_proposal_repository,
            proposal_id=proposal.proposal_id,
            rfq_repository=api.supplier_rfq_repository,
            approval_repository=api.quote_approval_repository,
            quote_case_repository=api.quote_case_repository,
            evidence_recorder=store,
            operational_data_sources=sources,
        )
        drafts = resumed.get("supplier_rfq_drafts") or []
        workflow = resumed.get("supplier_rfq_workflow")
        selected_names = [item["supplier_name"] for item in resumed["supplier_selection"]["selected_suppliers"]]
        result.require(
            "confirmed resume injected data",
            selected_names
            == [
                "Synthetic Carrier A",
                "Synthetic Carrier B",
                "Synthetic Carrier C",
            ],
        )
        result.require(
            "RFQ workflow",
            workflow is not None
            and len(drafts) == 1,
        )
        draft = drafts[0]
        result.require("manual send requires approval", _expect_http(
            409, api.record_supplier_rfq_manually_sent_endpoint, draft.rfq_id,
            api.SupplierRFQManualSentRequest(recorded_by=CLAIMED_OPERATOR), trusted_request,
        ))
        result.require("response prerequisite", _expect_http(
            409, api.attach_supplier_rfq_response_endpoint, draft.rfq_id,
            api.SupplierRFQResponseRequest(
                supplier_name=draft.supplier_name,
                rfq_priority=draft.priority,
                status="quoted",
                cost=1800,
                currency="EUR",
                recorded_by=CLAIMED_OPERATOR,
            ),
            trusted_request,
        ))
        result.require("quote approval prerequisite", _expect_http(
            404, api.approve_quote_approval, "missing-approval",
            api.QuoteApprovalApproveRequest(approved_by=CLAIMED_OPERATOR), trusted_request,
        ))
        approved_rfq = api.approve_supplier_rfq_endpoint(
            draft.rfq_id, api.SupplierRFQApproveRequest(approved_by=CLAIMED_OPERATOR), trusted_request
        )
        result.require("RFQ authenticated approval", approved_rfq["approved_by"] == authenticated_operator)
        sent = api.record_supplier_rfq_manually_sent_endpoint(
            draft.rfq_id, api.SupplierRFQManualSentRequest(recorded_by=CLAIMED_OPERATOR), trusted_request
        )
        result.require("manual send evidence", sent["supplier_rfq"]["status"] == "awaiting_response"
                       and sent["manual_sent_evidence"]["recorded_by"] == authenticated_operator
                       and sent["manual_sent_evidence"]["recorded_at"] is not None)
        response_request = api.SupplierRFQResponseRequest(
            supplier_name=draft.supplier_name, rfq_priority=draft.priority,
            status="quoted", cost=1800, currency="EUR", transit_time="4 days",
            validity_date="2099-12-31",
            vehicle_available_date="2026-08-20",
            equipment_type="Tenteli",
            pricing_basis="all_in",
            included_costs=["road freight"],
            excluded_costs=[],
            recorded_by=CLAIMED_OPERATOR,
        )
        response = api.attach_supplier_rfq_response_endpoint(
            draft.rfq_id,
            response_request,
            trusted_request,
        )
        result.require(
            "supplier response",
            response["supplier_rfq"]["status"] == "responded",
        )
        result.require(
            "supplier response authenticated provenance",
            response["response"]["source"] == "manual"
            and response["response"]["recorded_by"]
            == authenticated_operator,
        )
        result.require("duplicate response blocked", _expect_http(
            409,
            api.attach_supplier_rfq_response_endpoint,
            draft.rfq_id,
            response_request,
            trusted_request,
        ))
        result.require("response linkage blocked", _expect_http(
            409,
            api.attach_supplier_rfq_response_endpoint,
            draft.rfq_id,
            api.SupplierRFQResponseRequest(
                supplier_name="Mismatched Synthetic Carrier",
                rfq_priority=draft.priority,
                status="quoted",
                cost=1700,
                currency="EUR",
                recorded_by=CLAIMED_OPERATOR,
            ),
            trusted_request,
        ))
        progressed = resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=api.supplier_rfq_repository,
            approval_repository=api.quote_approval_repository,
            quote_case_repository=api.quote_case_repository,
            operational_data_sources=sources,
        )
        approval = progressed.get("quote_approval")
        quote_case = progressed.get("quote_case")
        progression_names = [item["supplier_name"] for item in progressed["supplier_selection"]["selected_suppliers"]]
        result.require("quote progression injected data", progression_names == selected_names)
        result.require("pending approval and case", approval is not None and approval.approval_status == "pending" and quote_case is not None)
        approved = api.approve_quote_approval(
            approval.approval_id, api.QuoteApprovalApproveRequest(approved_by=CLAIMED_OPERATOR), trusted_request
        )
        current_case = api.get_quote_case(quote_case.case_id)
        safety = current_case["quote_send_safety"]
        result.require("quote approval", approved["approval_status"] == "approved" and approved["approved_by"] == authenticated_operator and approved["approved_at"] is not None)
        result.require("current quote case", current_case["quote_approval"]["approval_status"] == "approved")
        result.require("quote send safety recomputed", safety is not None and safety["can_send"] is True and safety["approved_by"] == authenticated_operator)

        final_output = api.get_quote_case_final_output(
            quote_case.case_id
        )
        result.require(
            "final manual handoff",
            final_output["case_id"] == quote_case.case_id
            and final_output["approval_id"] == approved["approval_id"]
            and final_output["approved_by"] == authenticated_operator
            and final_output["approved_at"] is not None
            and final_output["subject"]
            == current_case["quote_draft"]["subject"]
            and final_output["body"]
            == current_case["quote_draft"]["body"]
            and final_output["final_price"]
            == current_case["customer_quote"]["final_price"]
            and final_output["currency"]
            == current_case["customer_quote"]["currency"]
            and final_output["delivery_mode"]
            == "manual_external_operation"
            and final_output["automated_send_performed"] is False,
        )

        result.evidence.update({
            "proposal_id": proposal.proposal_id, "workflow_id": workflow.workflow_id,
            "rfq_id": draft.rfq_id, "approval_id": approval.approval_id,
            "case_id": quote_case.case_id, "supplier_names": selected_names,
        })

        for label, special in (("ADR scope", _snapshot(adr=True)), ("reefer scope", _snapshot(reefer=True))):
            scoped = process_shipment(
                Shipment.model_validate(special.model_dump()),
                sender_address="logistics@customer.invalid",
                operational_data_sources=sources,
            )
            result.require(label, scoped.get("result_type") == "pilot_scope_excluded" and not scoped.get("supplier_rfq_drafts"))

        tamper_store = SQLitePilotStore(root / "tamper.sqlite3", run_id="tamper")
        tamper_rfqs = SQLiteSupplierRFQRepository(tamper_store)
        tamper_initial = process_shipment(
            Shipment.model_validate(_snapshot().model_dump()),
            sender_address="logistics@customer.invalid",
            rfq_repository=tamper_rfqs, operational_data_sources=sources,
        )
        tamper_draft = tamper_initial["supplier_rfq_drafts"][0]
        from src.core.supplier_rfq_lifecycle import approve_supplier_rfq, attach_supplier_rfq_response, record_supplier_rfq_manually_sent
        from src.core.supplier_rfq import SupplierRFQResponse
        approve_supplier_rfq(tamper_rfqs, tamper_draft.rfq_id, OPERATOR)
        record_supplier_rfq_manually_sent(tamper_rfqs, tamper_draft.rfq_id, OPERATOR)
        attach_supplier_rfq_response(tamper_rfqs, SupplierRFQResponse(
            rfq_id=tamper_draft.rfq_id, supplier_name=tamper_draft.supplier_name,
            rfq_priority=tamper_draft.priority, status="quoted", cost=1900,
            currency="EUR", source="manual",
        ))
        sources.supplier_capabilities_path.write_bytes(b"[]")
        tampered = resume_supplier_rfq_workflow(
            workflow_id=tamper_initial["supplier_rfq_workflow"].workflow_id,
            rfq_repository=tamper_rfqs,
            approval_repository=SQLiteQuoteApprovalRepository(tamper_store),
            quote_case_repository=SQLiteQuoteCaseRepository(tamper_store),
            operational_data_sources=sources,
        )
        durable_tamper = tamper_rfqs.get_workflow(tamper_initial["supplier_rfq_workflow"].workflow_id)
        result.require("provenance fail-closed", tampered.get("result_type") == "data_provenance_blocked"
                       and durable_tamper.quote_progression_status == "provenance_blocked")

    reopened = SQLitePilotStore(db_path, run_id="synthetic-rehearsal-restart")
    with _api_repositories(api, reopened):
        durable_proposal = api.extraction_proposal_repository.get(result.evidence["proposal_id"])
        durable_workflow = api.supplier_rfq_repository.get_workflow(result.evidence["workflow_id"])
        durable_rfq = api.supplier_rfq_repository.get_draft(result.evidence["rfq_id"])
        durable_manual_send_evidence = api.supplier_rfq_repository.list_manual_sent_evidence(
            result.evidence["rfq_id"]
        )
        durable_supplier_responses = (
            api.supplier_rfq_repository.list_responses(
                result.evidence["rfq_id"]
            )
        )
        durable_approval = api.quote_approval_repository.get(result.evidence["approval_id"])
        durable_case = api.get_quote_case(result.evidence["case_id"])
        durable_final_output = api.get_quote_case_final_output(
            result.evidence["case_id"]
        )
        result.require("durable restart", all((durable_proposal, durable_workflow, durable_rfq, durable_approval, durable_case))
                       and durable_proposal.resume_status == "completed"
                       and durable_rfq.status == "responded"
                       and durable_workflow.quote_progression_status == "completed")
        result.require("durable approved current case", durable_approval.approval_status == "approved"
                       and durable_case["quote_approval"]["approval_status"] == "approved"
                       and durable_case["quote_send_safety"]["can_send"] is True)
        result.require(
            "durable final manual handoff",
            durable_final_output == final_output
            and durable_final_output["delivery_mode"]
            == "manual_external_operation"
            and durable_final_output["automated_send_performed"] is False,
        )
        result.require("durable authenticated authority", durable_proposal.confirmed_by == authenticated_operator
                       and durable_rfq.approved_by == authenticated_operator
                       and len(durable_manual_send_evidence) == 1
                       and durable_manual_send_evidence[0].recorded_by == authenticated_operator
                       and len(durable_supplier_responses) == 1
                       and durable_supplier_responses[0].source == "manual"
                       and durable_supplier_responses[0].recorded_by == authenticated_operator
                       and durable_approval.approved_by == authenticated_operator)


def run_rehearsal(*, injected_failure: str | None = None) -> RehearsalResult:
    """Run the full rehearsal and return structured, non-sensitive evidence."""
    result = RehearsalResult()
    try:
        with tempfile.TemporaryDirectory(prefix="minai-synthetic-pilot-") as directory:
            temporary_root = Path(directory)
            with ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"MINAI_PILOT_MODE": "true"}, clear=False))
                stack.enter_context(_without_openai_key())
                stack.enter_context(patch.object(socket, "create_connection", _blocked_connection))
                stack.enter_context(patch.object(socket.socket, "connect", _blocked_connection))
                _run(temporary_root, result, injected_failure=injected_failure)
                try:
                    socket.create_connection(("example.invalid", 443))
                except RehearsalFailure:
                    create_blocked = True
                else:
                    create_blocked = False
                try:
                    socket.socket.connect(None, ("192.0.2.1", 443))
                except RehearsalFailure:
                    connect_blocked = True
                else:
                    connect_blocked = False
                result.require("network isolation", create_blocked and connect_blocked)
        result.require("temporary cleanup", not temporary_root.exists())
        result.stage = "complete"
        result.passed = all(result.checks.values())
    except RehearsalFailure as exc:
        result.stage = str(exc)
        result.failure_reason = "controlled rehearsal check failed"
    except Exception:
        result.failure_reason = "unexpected controlled rehearsal failure"
    return result


CLI_STAGES = (
    ("pilot authentication", "pilot authentication"),
    ("extraction confirmation enforced", "unconfirmed extraction blocked"),
    ("RFQ lifecycle", "RFQ workflow"),
    ("manual-send evidence", "manual send evidence"),
    ("supplier response", "supplier response"),
    ("quote progression", "quote progression injected data"),
    ("quote approval", "quote approval"),
    ("quote-case refresh", "current quote case"),
    ("final manual handoff", "final manual handoff"),
    ("durable restart", "durable restart"),
    ("provenance fail-closed", "provenance fail-closed"),
    ("scope fail-closed", "ADR scope"),
    ("network isolation", "network isolation"),
)


def main(stream: TextIO = sys.stdout, *, injected_failure: str | None = None) -> int:
    result = run_rehearsal(injected_failure=injected_failure)
    if not result.passed:
        print(f"FAIL {result.stage}: {result.failure_reason or 'controlled failure'}", file=stream)
        return 1
    for label, check in CLI_STAGES:
        if result.checks.get(check):
            print(f"PASS {label}", file=stream)
    print("\nSynthetic pilot rehearsal: PASS", file=stream)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
