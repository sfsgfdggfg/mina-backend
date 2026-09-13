from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_service_availability_repository import (
    InMemoryAirServiceAvailabilityRepository,
    SQLiteAirServiceAvailabilityRepository,
)
from src.core.air_service_availability_service import (
    AirServiceAvailabilityTransitionError,
    record_air_service_availability_confirmation,
)
from src.core.air_rate_validity_review_repository import InMemoryAirRateValidityReviewRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_rate_validity_review_regressions import _preview
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _source_repo

NOW = datetime(2026, 9, 13, 12, 10, tzinfo=timezone.utc)


def _record(repo, source_repo, **overrides):
    payload = {
        "source_id": "source-0001",
        "entry_id": "availability-0001",
        "inquiry_reference": "AIR-INQ-20260913-001",
        "destination_code": "FRA",
        "routing_context": "direct",
        "service_date": date(2026, 9, 16),
        "capacity_status": "available",
        "schedule_status": "confirmed",
        "flight_reference": "TK-TEST",
        "evidence_channel": "email",
        "evidence_reference": "message-air-availability-1",
        "evidence_note": "Airline explicitly confirmed space and schedule for this inquiry/date.",
        "confirmed_by": "Senior Air Operator",
        "confirmed_at": NOW,
        "source_repository": source_repo,
        "repository": repo,
    }
    payload.update(overrides)
    return record_air_service_availability_confirmation(**payload)


def evaluate_air_service_availability_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    repo = InMemoryAirServiceAvailabilityRepository()
    item, created = _record(repo, source_repo)
    check(
        created is True
        and item.source_sha256 == source_repo.get_rate_source("source-0001").sha256_hex
        and item.destination_code == "FRA"
        and item.capacity_status == "available"
        and item.schedule_status == "confirmed"
        and item.runtime_authoritative is False
        and item.booking_authority is False,
        "airline availability evidence stays inquiry/date-bound and creates no booking authority",
    )

    same, created_again = _record(repo, source_repo)
    check(
        created_again is False and same.confirmation_id == item.confirmation_id,
        "availability evidence entry identity is idempotent for the same exact evidence",
    )

    conflict_blocked = False
    try:
        _record(repo, source_repo, capacity_status="unavailable")
    except AirServiceAvailabilityTransitionError:
        conflict_blocked = True
    check(conflict_blocked, "availability entry identity fails closed when reused with different evidence")

    direct_via_blocked = False
    try:
        _record(repo, source_repo, entry_id="availability-direct-via", via_airport="IST")
    except AirServiceAvailabilityTransitionError:
        direct_via_blocked = True
    check(direct_via_blocked, "direct availability confirmation cannot carry a via airport")

    unconfirmed_flight_blocked = False
    try:
        _record(
            repo, source_repo,
            entry_id="availability-unconfirmed-flight",
            schedule_status="not_confirmed",
            flight_reference="TK-TEST",
        )
    except AirServiceAvailabilityTransitionError:
        unconfirmed_flight_blocked = True
    check(
        unconfirmed_flight_blocked,
        "schedule-not-confirmed evidence cannot fabricate a flight reference",
    )

    second, second_created = _record(
        repo, source_repo,
        entry_id="availability-0002",
        inquiry_reference="AIR-INQ-20260913-002",
        service_date=date(2026, 9, 17),
        capacity_status="unavailable",
        schedule_status="not_confirmed",
        flight_reference=None,
        evidence_reference="message-air-availability-2",
    )
    check(
        second_created is True and second.confirmation_id != item.confirmation_id and len(repo.list_all()) == 2,
        "same tariff source may hold separate non-reusable availability evidence per inquiry and date",
    )
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirServiceAvailabilityRepository(SQLitePilotStore(db_path))
        persisted, _ = _record(sqlite_repo, source_repo, entry_id="availability-sqlite")
        restored = SQLiteAirServiceAvailabilityRepository(SQLitePilotStore(db_path)).get(persisted.confirmation_id)
        check(
            restored is not None
            and restored.inquiry_reference == persisted.inquiry_reference
            and restored.capacity_status == "available",
            "airline availability evidence survives SQLite repository reconstruction",
        )
    check(
        "air_service_availability_confirmations" in PERSISTENT_STATE_NAMESPACES
        and "air_service_availability_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "airline availability evidence is protected from ordinary retention purge",
    )

    preview = _preview(InMemoryAirRateValidityReviewRepository())
    check(
        preview.capacity_confirmed is False,
        "recorded availability evidence does not silently enter reviewed surcharge cost preview",
    )

    from src import api
    api_repo = InMemoryAirServiceAvailabilityRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (api.air_shadow_repository, api.air_service_availability_repository)
    try:
        api.air_shadow_repository = source_repo
        api.air_service_availability_repository = api_repo
        response = api.create_air_service_availability_confirmation(
            "source-0001",
            api.AirServiceAvailabilityRequest(
                entry_id="availability-api",
                inquiry_reference="AIR-INQ-API-001",
                destination_code="fra",
                routing_context="connecting",
                via_airport="ist",
                service_date=date(2026, 9, 18),
                capacity_status="available",
                schedule_status="confirmed",
                flight_reference="TK-API",
                evidence_channel="email",
                evidence_reference="message-api-air-1",
                evidence_note="Airline confirmation reviewed by operator.",
            ),
            request,
        )
    finally:
        api.air_shadow_repository, api.air_service_availability_repository = originals
    check(
        response["confirmation"]["confirmed_by"] == "API Air Operator"
        and response["confirmation"]["destination_code"] == "FRA"
        and response["booking_authority_enabled"] is False
        and response["cost_preview_consumption_enabled"] is False,
        "controlled API stores authenticated availability evidence without booking or pricing consumption authority",
    )
    check(
        route_allowed("GET", "/air-service-availability-confirmations")
        and route_allowed("POST", "/air-rate-sources/source-1/availability-confirmations"),
        "pilot access admits bounded airline availability evidence routes",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_service_availability_service.py").read_text(encoding="utf-8")
    check(
        "Kapasite / Schedule Evidence" in js
        and "Kapasite / Schedule Teyidi Kaydet" in js
        and "booking authority" in js.casefold()
        and "openai" not in service.casefold(),
        "browser captures explicit airline availability evidence while keeping booking and AI boundaries visible",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_service_availability_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir service availability regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
