from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_additional_cost_evidence_repository import (
    InMemoryAirAdditionalCostEvidenceRepository,
    SQLiteAirAdditionalCostEvidenceRepository,
)
from src.core.air_additional_cost_evidence_service import (
    AirAdditionalCostEvidenceTransitionError,
    record_air_additional_cost_evidence,
)
from src.core.air_reviewed_surcharge_cost_preview import build_air_reviewed_surcharge_cost_preview
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _source_repo,
    _standard_repo,
    _structure_repo,
    _table_repo,
)


NOW = datetime(2026, 9, 14, 8, 15, tzinfo=timezone.utc)


def _record(repo, source_repo, **overrides):
    payload = {
        "source_id": "source-0001",
        "entry_id": "air-additional-cost-0001",
        "inquiry_reference": "AIR-INQ-20260914-001",
        "cost_category": "pickup",
        "provider_name": "Adana Air Cargo Services",
        "amount": Decimal("85.50"),
        "currency": "eur",
        "quantity_basis": "per_shipment",
        "evidence_source": "email",
        "evidence_reference": "message-local-cost-1",
        "evidence_note": "Pickup flat fee explicitly quoted for this inquiry.",
        "recorded_by": "Senior Air Operator",
        "recorded_at": NOW,
        "source_repository": source_repo,
        "repository": repo,
    }
    payload.update(overrides)
    return record_air_additional_cost_evidence(**payload)


def _partial_cost_preview():
    return build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_standard_repo(),
        source_repository=_source_repo(),
    )


def evaluate_air_additional_cost_evidence_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    repo = InMemoryAirAdditionalCostEvidenceRepository()
    item, created = _record(repo, source_repo)
    check(
        created is True
        and item.source_id == "source-0001"
        and item.source_sha256 == source_repo.get_rate_source("source-0001").sha256_hex
        and item.inquiry_reference == "AIR-INQ-20260914-001"
        and item.cost_category == "pickup"
        and item.amount == Decimal("85.50")
        and item.currency == "EUR"
        and item.quantity_basis == "per_shipment"
        and item.runtime_authoritative is False
        and item.pricing_authority is False,
        "flat additional-cost evidence preserves inquiry source amount unit and non-authority provenance",
    )

    same, created_again = _record(repo, source_repo)
    check(
        created_again is False and same.evidence_id == item.evidence_id,
        "additional-cost evidence entry identity is idempotent for identical evidence",
    )

    conflict_blocked = False
    try:
        _record(repo, source_repo, amount=Decimal("99.00"))
    except AirAdditionalCostEvidenceTransitionError:
        conflict_blocked = True
    check(
        conflict_blocked,
        "additional-cost evidence entry identity fails closed when reused with another amount",
    )

    per_kg_blocked = False
    try:
        _record(
            InMemoryAirAdditionalCostEvidenceRepository(),
            source_repo,
            entry_id="air-additional-cost-perkg",
            quantity_basis="per_kg",
        )
    except AirAdditionalCostEvidenceTransitionError:
        per_kg_blocked = True
    check(
        per_kg_blocked,
        "weight-based additional costs remain outside flat-only P2-35 evidence capture",
    )

    duty_blocked = False
    try:
        _record(
            InMemoryAirAdditionalCostEvidenceRepository(),
            source_repo,
            entry_id="air-additional-cost-duty",
            cost_category="customs_duty",
        )
    except AirAdditionalCostEvidenceTransitionError:
        duty_blocked = True
    check(
        duty_blocked,
        "customs duties and taxes cannot be disguised as customs service-fee evidence",
    )

    second_repo = InMemoryAirAdditionalCostEvidenceRepository()
    second, _ = _record(
        second_repo,
        source_repo,
        entry_id="air-additional-cost-delivery",
        inquiry_reference="AIR-INQ-20260914-002",
        cost_category="delivery",
        provider_name="Frankfurt Delivery Partner",
        amount=Decimal("140"),
        currency="USD",
        quantity_basis="per_awb",
        evidence_source="portal",
        evidence_reference="portal-quote-42",
    )
    check(
        second.inquiry_reference != item.inquiry_reference
        and second.source_id == item.source_id
        and second.cost_category == "delivery"
        and second.quantity_basis == "per_awb",
        "same tariff context may hold separate inquiry-bound local-cost evidence without reuse",
    )

    before = _partial_cost_preview()
    _record(
        repo,
        source_repo,
        entry_id="air-additional-cost-not-consumed",
        cost_category="origin_terminal",
        amount=Decimal("55"),
    )
    after = _partial_cost_preview()
    check(
        after.base_plus_reviewed_surcharges == before.base_plus_reviewed_surcharges
        and after.all_in_cost is False
        and after.customer_quote_eligible is False,
        "stored local-cost evidence never enters the existing partial cost preview automatically",
    )

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirAdditionalCostEvidenceRepository(SQLitePilotStore(db_path))
        persisted, _ = _record(
            sqlite_repo,
            source_repo,
            entry_id="air-additional-cost-sqlite",
            cost_category="documentation",
            amount=Decimal("30"),
        )
        restored = SQLiteAirAdditionalCostEvidenceRepository(
            SQLitePilotStore(db_path)
        ).get(persisted.evidence_id)
        check(
            restored is not None
            and restored.inquiry_reference == persisted.inquiry_reference
            and restored.amount == Decimal("30")
            and restored.cost_category == "documentation",
            "additional-cost evidence survives SQLite repository reconstruction",
        )

    check(
        "air_additional_cost_evidence" in PERSISTENT_STATE_NAMESPACES
        and "air_additional_cost_evidence_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "additional-cost evidence and entry identity are protected from ordinary retention purge",
    )

    from src import api
    api_repo = InMemoryAirAdditionalCostEvidenceRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (api.air_shadow_repository, api.air_additional_cost_evidence_repository)
    try:
        api.air_shadow_repository = source_repo
        api.air_additional_cost_evidence_repository = api_repo
        response = api.create_air_additional_cost_evidence(
            "source-0001",
            api.AirAdditionalCostEvidenceRequest(
                entry_id="air-additional-cost-api",
                inquiry_reference="AIR-INQ-API-001",
                cost_category="destination_handling",
                provider_name="Destination Handler",
                amount=65.25,
                currency="usd",
                quantity_basis="per_awb",
                evidence_source="email",
                evidence_reference="message-air-cost-api",
                evidence_note="Destination handling fee explicitly quoted.",
            ),
            request,
        )
    finally:
        api.air_shadow_repository, api.air_additional_cost_evidence_repository = originals

    check(
        response["evidence"]["recorded_by"] == "API Air Operator"
        and response["evidence"]["currency"] == "USD"
        and response["created"] is True
        and response["pricing_authority_enabled"] is False
        and response["cost_preview_consumption_enabled"] is False
        and response["customer_quote_eligible"] is False
        and response["duties_and_taxes_supported"] is False,
        "controlled API captures authenticated local-cost evidence without calculation or quote authority",
    )

    check(
        route_allowed("GET", "/air-additional-cost-evidence")
        and route_allowed("POST", "/air-rate-sources/source-1/additional-cost-evidence"),
        "pilot access admits only bounded additional-cost evidence read/write surfaces",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_additional_cost_evidence_service.py").read_text(encoding="utf-8")
    check(
        "Additional / Local Cost Evidence" in js
        and "cost preview'a otomatik eklemez" in js
        and "customs duties/taxes desteklenmez" in js
        and "openai" not in service.casefold(),
        "browser exposes flat local-cost capture while unsupported and non-consumption boundaries stay visible",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_additional_cost_evidence_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir additional-cost evidence regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
