"""Focused regressions for explicit operational-data source injection."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import api
from src.api import ProcessEmailRequest
from src.core.customer_memory import load_customer_memory
from src.core.data_provenance import (
    DataProvenanceBlockedError,
    calculate_bytes_sha256,
    require_pilot_operational_dataset,
)
from src.core.models import Package, Shipment
from src.core.operational_data import (
    DEFAULT_OPERATIONAL_DATA_SOURCES,
    OperationalDataSources,
)
from src.core.supplier_selection import select_suppliers_for_shipment
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import (
    approve_supplier_rfq,
    attach_supplier_rfq_response,
    record_supplier_rfq_manually_sent,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.paths import data_path
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow


def _shipment(customer_name: str = "Synthetic Customer") -> Shipment:
    return Shipment(
        customer_name=customer_name,
        pickup_country="Türkiye",
        pickup_city="Adana",
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
        is_adr=False,
        is_temperature_controlled=False,
    )


def _supplier(name: str) -> list[dict]:
    return [{
        "supplier_name": name,
        "active": True,
        "role": "primary",
        "countries": ["Türkiye", "Almanya"],
        "equipment_types": ["Tenteli"],
        "service_types": ["FTL"],
        "route_regions": ["international"],
        "special_capabilities": [],
        "priority_routes": [],
        "reliability_score": 0.9,
        "price_score": 0.8,
        "speed_score": 0.8,
        "notes": "Synthetic regression supplier.",
        "contacts": [{
            "email": f"{name.lower().replace(' ', '.')}@synthetic.invalid",
            "active": True,
            "is_primary": True,
        }],
    }]


def _build_responded_workflow(
    sources: OperationalDataSources,
) -> tuple[dict, InMemorySupplierRFQRepository]:
    repository = InMemorySupplierRFQRepository()
    initial = process_shipment(
        _shipment(),
        sender_address="operator@synthetic.invalid",
        rfq_repository=repository,
        operational_data_sources=sources,
    )
    drafts = initial.get("supplier_rfq_drafts") or []
    if not drafts:
        return initial, repository
    draft = drafts[0]
    approve_supplier_rfq(repository, draft.rfq_id, "Synthetic Operator")
    awaiting, _ = record_supplier_rfq_manually_sent(
        repository,
        draft.rfq_id,
        "Synthetic Operator",
    )
    attach_supplier_rfq_response(
        repository,
        SupplierRFQResponse(
            rfq_id=awaiting.rfq_id,
            supplier_name=awaiting.supplier_name,
            rfq_priority=awaiting.priority,
            status="quoted",
            cost=2_000,
            currency="EUR",
            transit_time="4-5 days",
            validity_date="2099-12-31",
            vehicle_available_date="2026-08-20",
            equipment_type="Tenteli",
            pricing_basis="all_in",
            included_costs=["road freight"],
            excluded_costs=[],
            source="simulation",
        ),
    )
    return initial, repository


def _write_sources(
    root: Path,
    *,
    customer_name: str = "Synthetic Customer",
    supplier_name: str = "Synthetic Supplier A",
    classification: str = "pilot_verified",
    pilot_usable: bool = True,
) -> OperationalDataSources:
    data_dir = root / "data"
    data_dir.mkdir()
    customer_path = data_dir / "customer_memory.json"
    supplier_path = data_dir / "supplier_capabilities.json"
    customer_content = json.dumps([{
        "customer_name": customer_name,
        "active": True,
        "aliases": [],
        "trusted_sender_addresses": [],
        "trusted_sender_domains": ["synthetic.invalid"],
        "operational_notes": [],
    }]).encode()
    supplier_content = json.dumps(_supplier(supplier_name)).encode()
    customer_path.write_bytes(customer_content)
    supplier_path.write_bytes(supplier_content)

    def record(relative_path: str, content: bytes) -> dict:
        return {
            "path": relative_path,
            "classification": classification,
            "operational": True,
            "pilot_usable": pilot_usable,
            "verified_by": "Synthetic Data Owner",
            "verified_at": "2026-08-14T00:00:00+00:00",
            "verified_sha256": calculate_bytes_sha256(content),
        }

    registry_path = data_dir / "provenance_registry.json"
    registry_path.write_text(json.dumps({
        "version": 1,
        "datasets": {
            "customer_memory": record(
                "data/customer_memory.json", customer_content
            ),
            "supplier_capabilities": record(
                "data/supplier_capabilities.json", supplier_content
            ),
        },
    }), encoding="utf-8")
    return OperationalDataSources(
        provenance_registry_path=registry_path,
        customer_memory_path=customer_path,
        supplier_capabilities_path=supplier_path,
    )


def evaluate_operational_data_injection_regressions() -> dict:
    failures: list[str] = []
    expected_defaults = (
        data_path("provenance_registry.json"),
        data_path("customer_memory.json"),
        data_path("supplier_capabilities.json"),
    )
    actual_defaults = (
        DEFAULT_OPERATIONAL_DATA_SOURCES.provenance_registry_path,
        DEFAULT_OPERATIONAL_DATA_SOURCES.customer_memory_path,
        DEFAULT_OPERATIONAL_DATA_SOURCES.supplier_capabilities_path,
    )
    if actual_defaults != expected_defaults:
        failures.append("default sources do not resolve to repository data")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        default_before = process_shipment(_shipment())

    with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
        first = _write_sources(Path(first_dir), supplier_name="Injected Supplier A")
        second = _write_sources(Path(second_dir), supplier_name="Injected Supplier B")
        pilot_env = {"MINAI_PILOT_MODE": "1"}
        with patch.dict(os.environ, pilot_env, clear=False):
            profiles = load_customer_memory(first)
            if [profile.customer_name for profile in profiles] != ["Synthetic Customer"]:
                failures.append("injected customer memory was not read")

            first_selection = select_suppliers_for_shipment(
                _shipment(), operational_data_sources=first
            )
            second_selection = select_suppliers_for_shipment(
                _shipment(), operational_data_sources=second
            )
            if [item["supplier_name"] for item in first_selection["selected_suppliers"]] != ["Injected Supplier A"]:
                failures.append("first injected supplier dataset was not used")
            if [item["supplier_name"] for item in second_selection["selected_suppliers"]] != ["Injected Supplier B"]:
                failures.append("supplier data leaked across injected executions")

            workflow = process_shipment(
                _shipment(),
                sender_address="operator@synthetic.invalid",
                operational_data_sources=first,
            )
            if workflow.get("result_type") == "data_provenance_blocked":
                failures.append("verified injected workflow was blocked")

            injected_consistency = (
                workflow.get("operational_consistency") or {}
            )
            if (
                injected_consistency.get("capability_data_source")
                != str(first.supplier_capabilities_path)
            ):
                failures.append(
                    "operational consistency did not use injected supplier data"
                )
            if injected_consistency.get("passed") is not True:
                failures.append(
                    "injected supplier selection and consistency disagreed"
                )

            progression_initial, progression_repository = (
                _build_responded_workflow(first)
            )
            blocked_initial, blocked_repository = _build_responded_workflow(
                first
            )
            initial_names = [
                item["supplier_name"]
                for item in (
                    progression_initial.get("supplier_selection") or {}
                ).get("selected_suppliers", [])
            ]
            if initial_names != ["Injected Supplier A"]:
                failures.append(
                    "initial RFQ workflow did not use injected Supplier A"
                )
            progression_workflow = progression_initial.get(
                "supplier_rfq_workflow"
            )
            if progression_workflow is None:
                failures.append("injected RFQ workflow was not created")
            else:
                progressed = resume_supplier_rfq_workflow(
                    workflow_id=progression_workflow.workflow_id,
                    rfq_repository=progression_repository,
                    approval_repository=InMemoryQuoteApprovalRepository(),
                    quote_case_repository=InMemoryQuoteCaseRepository(),
                    operational_data_sources=first,
                )
                progressed_names = [
                    item["supplier_name"]
                    for item in (
                        progressed.get("supplier_selection") or {}
                    ).get("selected_suppliers", [])
                ]
                if progressed_names != ["Injected Supplier A"]:
                    failures.append(
                        "quote progression did not retain injected Supplier A"
                    )
                progressed_memory = progressed.get("customer_memory")
                progressed_profile = (
                    progressed_memory.profile
                    if progressed_memory is not None
                    else None
                ) or (
                    progressed_memory.candidate_profile
                    if progressed_memory is not None
                    else None
                )
                if (
                    progressed_profile is None
                    or progressed_profile.customer_name != "Synthetic Customer"
                ):
                    failures.append(
                        "quote progression fell back from injected customer data"
                    )

            first.supplier_capabilities_path.write_bytes(
                json.dumps(_supplier("Tampered Supplier")).encode()
            )
            try:
                select_suppliers_for_shipment(
                    _shipment(), operational_data_sources=first
                )
            except DataProvenanceBlockedError:
                pass
            else:
                failures.append("fingerprint-mismatched supplier data was accepted")

            blocked_workflow = blocked_initial.get("supplier_rfq_workflow")
            if blocked_workflow is None:
                failures.append("tamper-check RFQ workflow was not created")
            else:
                blocked_progression = resume_supplier_rfq_workflow(
                    workflow_id=blocked_workflow.workflow_id,
                    rfq_repository=blocked_repository,
                    approval_repository=InMemoryQuoteApprovalRepository(),
                    quote_case_repository=InMemoryQuoteCaseRepository(),
                    operational_data_sources=first,
                )
                durable = blocked_repository.get_workflow(
                    blocked_workflow.workflow_id
                )
                if (
                    blocked_progression.get("result_type")
                    != "data_provenance_blocked"
                    or durable is None
                    or durable.quote_progression_status
                    != "provenance_blocked"
                    or durable.last_provenance_blocked_result_type
                    != "data_provenance_blocked"
                ):
                    failures.append(
                        "tampered quote progression did not fail durably closed"
                    )

        mismatched = OperationalDataSources(
            provenance_registry_path=second.provenance_registry_path,
            customer_memory_path=second.customer_memory_path,
            supplier_capabilities_path=first.supplier_capabilities_path,
        )
        try:
            require_pilot_operational_dataset(
                "supplier_capabilities",
                environ=pilot_env,
                path=mismatched.provenance_registry_path,
                dataset_path=mismatched.supplier_capabilities_path,
                dataset_bytes=mismatched.supplier_capabilities_path.read_bytes(),
            )
        except DataProvenanceBlockedError:
            pass
        else:
            failures.append("registry/dataset path disagreement was accepted")

    with tempfile.TemporaryDirectory() as demo_dir:
        demo = _write_sources(
            Path(demo_dir), classification="demo", pilot_usable=False
        )
        with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
            blocked = process_shipment(
                _shipment(), operational_data_sources=demo
            )
        if blocked.get("result_type") != "data_provenance_blocked":
            failures.append("demo injected operational data was pilot-usable")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        default_after = process_shipment(_shipment())
    before_selection = default_before.get("supplier_selection") or {}
    after_selection = default_after.get("supplier_selection") or {}
    before_names = [
        x["supplier_name"]
        for x in before_selection.get("selected_suppliers", [])
    ]
    after_names = [
        x["supplier_name"]
        for x in after_selection.get("selected_suppliers", [])
    ]
    if (
        default_before.get("result_type") != default_after.get("result_type")
        or before_names != after_names
    ):
        failures.append("default workflow changed after injected execution")

    request_fields = set(ProcessEmailRequest.model_fields)
    if request_fields.intersection({
        "operational_data_sources", "provenance_registry_path",
        "customer_memory_path", "supplier_capabilities_path",
    }):
        failures.append("HTTP request body exposes operational filesystem paths")

    with tempfile.TemporaryDirectory() as api_dir:
        api_sources = _write_sources(
            Path(api_dir),
            supplier_name="API Injected Supplier",
        )
        with patch.object(
            api,
            "operational_data_sources",
            api_sources,
        ):
            with patch.object(
                api,
                "resume_confirmed_extraction",
                return_value={"result_type": "wiring_probe"},
            ) as extraction_resume:
                api.resume_extraction_proposal_endpoint(
                    "wiring-proposal"
                )
            if (
                extraction_resume.call_args is None
                or extraction_resume.call_args.kwargs.get(
                    "operational_data_sources"
                )
                is not api_sources
            ):
                failures.append(
                    "extraction resume API did not use resolved operational data"
                )

            with patch.object(
                api,
                "resume_supplier_rfq_workflow",
                return_value={"result_type": "wiring_probe"},
            ) as rfq_resume:
                api.resume_supplier_rfq_quote(
                    "wiring-workflow"
                )
            if (
                rfq_resume.call_args is None
                or rfq_resume.call_args.kwargs.get(
                    "operational_data_sources"
                )
                is not api_sources
            ):
                failures.append(
                    "RFQ quote resume API did not use resolved operational data"
                )

    return {
        "name": "Explicit operational data injection",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_operational_data_injection_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
