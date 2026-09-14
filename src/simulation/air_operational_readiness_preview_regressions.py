from __future__ import annotations

from datetime import date
from pathlib import Path

from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.air_operational_readiness_preview import (
    AirOperationalReadinessPreviewError,
    build_air_operational_readiness_preview,
)
from src.core.air_rate_validity_review_repository import InMemoryAirRateValidityReviewRepository
from src.core.air_service_availability_repository import InMemoryAirServiceAvailabilityRepository
from src.core.pilot_access import route_allowed
from src.simulation.air_fx_rate_evidence_regressions import _record as _record_fx
from src.simulation.air_rate_validity_review_regressions import _review
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _source_repo,
    _standard_repo,
    _structure_repo,
    _table_repo,
)
from src.simulation.air_service_availability_regressions import _record as _record_availability


SERVICE_DATE = date(2026, 9, 16)
INQUIRY = "AIR-INQ-20260913-001"


def _validity_repo(source_repo):
    repo = InMemoryAirRateValidityReviewRepository()
    _review(repo, source_repo)
    return repo


def _preview(source_repo, validity_repo, availability_repo, *, fx_repo=None, **overrides):
    payload = {
        "review_id": "table-review-0001",
        "candidate_id": "table-row-fra-0001",
        "inquiry_reference": INQUIRY,
        "service_date": SERVICE_DATE,
        "actual_weight_kg": 287,
        "volumetric_weight_kg": 250,
        "cargo_context": "general_cargo",
        "routing_context": "direct",
        "table_repository": _table_repo(),
        "structure_repository": _structure_repo(),
        "surcharge_repository": _standard_repo(),
        "source_repository": source_repo,
        "validity_repository": validity_repo,
        "availability_repository": availability_repo,
        "fx_repository": fx_repo,
    }
    payload.update(overrides)
    return build_air_operational_readiness_preview(**payload)


def evaluate_air_operational_readiness_preview_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    validity_repo = _validity_repo(source_repo)
    availability_repo = InMemoryAirServiceAvailabilityRepository()
    availability, _ = _record_availability(availability_repo, source_repo)

    ready = _preview(source_repo, validity_repo, availability_repo)
    check(
        ready.operational_evidence_complete is True
        and ready.tariff_validity_confirmed is True
        and ready.capacity_confirmed is True
        and ready.schedule_confirmed is True
        and ready.availability_evidence_found is True
        and ready.availability_confirmation_id == availability.confirmation_id
        and ready.operational_blockers == []
        and ready.partial_cost_only is True
        and ready.customer_quote_ready is False
        and ready.booking_ready is False
        and ready.outbound_authority is False
        and ready.runtime_authoritative is False,
        "matching source inquiry date validity and availability evidence can complete only operational evidence",
    )
    check(
        ready.cost_preview.customer_quote_eligible is False
        and ready.cost_preview.all_in_cost is False
        and ready.cost_preview.fx_applied is False
        and any(x.reason == "currency_mismatch_no_fx" for x in ready.cost_preview.excluded_surcharges),
        "operational evidence completeness never upgrades the partial cost preview or silently supplies FX",
    )

    fx_repo = InMemoryAirFxRateEvidenceRepository()
    fx, _ = _record_fx(
        fx_repo,
        source_repo,
        inquiry_reference=INQUIRY,
    )
    ready_fx = _preview(
        source_repo,
        validity_repo,
        availability_repo,
        fx_repo=fx_repo,
        fx_evidence_ids=[fx.evidence_id],
        fx_reference_at=fx.effective_at,
    )
    check(
        ready_fx.operational_evidence_complete is True
        and ready_fx.fx_applied is True
        and ready_fx.fx_evidence_ids_used == [fx.evidence_id]
        and ready_fx.cost_preview.fx_evidence_ids_used == [fx.evidence_id],
        "P2-33 preserves explicit P2-32 FX provenance while aggregating operational evidence",
    )

    missing = _preview(
        source_repo,
        validity_repo,
        InMemoryAirServiceAvailabilityRepository(),
    )
    check(
        missing.operational_evidence_complete is False
        and missing.availability_evidence_found is False
        and missing.operational_blockers == ["availability_evidence_missing"],
        "missing airline availability evidence remains an explicit operational blocker",
    )

    blocked_repo = InMemoryAirServiceAvailabilityRepository()
    _record_availability(
        blocked_repo,
        source_repo,
        entry_id="availability-blocked",
        capacity_status="unavailable",
        schedule_status="not_confirmed",
        flight_reference=None,
    )
    blocked = _preview(source_repo, validity_repo, blocked_repo)
    check(
        blocked.capacity_status == "unavailable"
        and blocked.schedule_status == "not_confirmed"
        and blocked.capacity_confirmed is False
        and blocked.schedule_confirmed is False
        and blocked.operational_blockers == ["capacity_unavailable", "schedule_not_confirmed"]
        and blocked.operational_evidence_complete is False,
        "negative capacity and unconfirmed schedule evidence stay visible as blockers",
    )

    wrong_context_repo = InMemoryAirServiceAvailabilityRepository()
    _record_availability(
        wrong_context_repo,
        source_repo,
        entry_id="availability-other-inquiry",
        inquiry_reference="AIR-INQ-OTHER",
    )
    wrong_context = _preview(source_repo, validity_repo, wrong_context_repo)
    check(
        wrong_context.availability_evidence_found is False
        and wrong_context.operational_blockers == ["availability_evidence_missing"],
        "availability evidence never leaks across inquiry context",
    )

    ambiguous_repo = InMemoryAirServiceAvailabilityRepository()
    _record_availability(ambiguous_repo, source_repo, entry_id="availability-a")
    _record_availability(
        ambiguous_repo,
        source_repo,
        entry_id="availability-b",
        evidence_reference="message-air-availability-2",
    )
    ambiguous_blocked = False
    try:
        _preview(source_repo, validity_repo, ambiguous_repo)
    except AirOperationalReadinessPreviewError as exc:
        ambiguous_blocked = str(exc) == "air_service_availability_context_ambiguous"
    check(
        ambiguous_blocked,
        "multiple availability confirmations for one exact context fail closed instead of choosing latest",
    )

    expired_blocked = False
    try:
        _preview(
            source_repo,
            validity_repo,
            availability_repo,
            service_date=date(2026, 10, 1),
        )
    except AirOperationalReadinessPreviewError as exc:
        expired_blocked = str(exc) == "air_rate_tariff_not_valid_for_reference_date"
    check(
        expired_blocked,
        "operational readiness fails closed when service date is outside reviewed tariff validity",
    )

    orphan_fx_time_blocked = False
    try:
        _preview(
            source_repo,
            validity_repo,
            availability_repo,
            fx_reference_at=fx.effective_at,
        )
    except AirOperationalReadinessPreviewError as exc:
        orphan_fx_time_blocked = str(exc) == "fx_evidence_ids_required_for_fx_context"
    check(
        orphan_fx_time_blocked,
        "readiness preview never accepts an FX timestamp without explicit selected FX evidence",
    )

    from src import api
    request = api.AirOperationalReadinessPreviewRequest(
        inquiry_reference=INQUIRY,
        service_date=SERVICE_DATE,
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
    )
    originals = (
        api.air_shadow_repository,
        api.air_rate_validity_review_repository,
        api.air_service_availability_repository,
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_fx_rate_evidence_repository,
    )
    try:
        api.air_shadow_repository = source_repo
        api.air_rate_validity_review_repository = validity_repo
        api.air_service_availability_repository = availability_repo
        api.air_rate_table_review_repository = _table_repo()
        api.air_rate_structure_review_repository = _structure_repo()
        api.air_rate_surcharge_review_repository = _standard_repo()
        api.air_fx_rate_evidence_repository = InMemoryAirFxRateEvidenceRepository()
        response = api.preview_air_operational_readiness(
            "table-review-0001",
            "table-row-fra-0001",
            request,
        )
    finally:
        (
            api.air_shadow_repository,
            api.air_rate_validity_review_repository,
            api.air_service_availability_repository,
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_fx_rate_evidence_repository,
        ) = originals

    check(
        response["operational_evidence_complete"] is True
        and response["customer_quote_ready"] is False
        and response["booking_ready"] is False
        and response["outbound_authority"] is False,
        "controlled API exposes matched operational evidence without quote booking or outbound authority",
    )
    check(
        route_allowed(
            "POST",
            "/air-rate-table-reviews/table-review/rows/row-1/operational-readiness-preview",
        ),
        "pilot access admits bounded operational-readiness preview route",
    )

    root = Path(__file__).resolve().parents[2]
    service_text = (root / "src" / "core" / "air_operational_readiness_preview.py").read_text(encoding="utf-8")
    ui_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "openai" not in service_text.casefold()
        and "Operational Readiness Preview" in ui_text
        and "booking authority" in ui_text.casefold()
        and "Müşteri teklifi hazır değil" in ui_text,
        "browser exposes readiness as evidence-only and service has no OpenAI dependency",
    )
    check(
        "insert_once" not in service_text
        and ".create(" not in service_text
        and "upsert" not in service_text
        and "save(" not in service_text,
        "operational readiness remains ephemeral and introduces no persistence write path",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_operational_readiness_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir operational readiness preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
