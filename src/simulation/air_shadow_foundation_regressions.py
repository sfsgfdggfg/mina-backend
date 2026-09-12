from __future__ import annotations

import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.core.air_shadow import AirModeObservation, AirRateSource
from src.core.air_shadow_repository import AirShadowConflictError, SQLiteAirShadowRepository
from src.core.pilot_store import SQLitePilotStore


def evaluate_air_shadow_foundation_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    observed_at = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    base_source = AirRateSource(
        entry_id="air-rate:thy:general:2026-09",
        airline_name="THY",
        document_name="thy-general-cargo-september.pdf",
        sha256_hex="a" * 64,
        cargo_scope="general_cargo",
        origin_airport="IST",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        recorded_by="Pilot Operator",
        recorded_at=observed_at,
    )
    check(base_source.mode == "commercial_air" and base_source.runtime_authoritative is False,
          "commercial-air tariff source is evidence-only and never runtime pricing authority")
    check("cost" not in AirRateSource.model_fields and "rate" not in AirRateSource.model_fields,
          "air tariff source identity stores no parsed commercial price")

    invalid_pdf = False
    try:
        AirRateSource(
            entry_id="bad-file", airline_name="THY", document_name="rates.xlsx",
            sha256_hex="b" * 64, recorded_by="Pilot Operator", recorded_at=observed_at,
        )
    except ValidationError:
        invalid_pdf = True
    check(invalid_pdf, "commercial-air tariff foundation accepts PDF source identity only")

    invalid_express_rate = False
    try:
        AirRateSource.model_validate({
            **base_source.model_dump(mode="json"),
            "source_id": "different", "entry_id": "express-rate", "mode": "express",
        })
    except ValidationError:
        invalid_express_rate = True
    check(invalid_express_rate, "express tariff ingestion is outside Air Rate Source v1")

    commercial_observation = AirModeObservation(
        entry_id="air-mode:inquiry-1", inquiry_reference="inquiry:sha256:001",
        selected_mode="commercial_air", evidence_basis="sent_quote",
        observed_by="Pilot Operator", observed_at=observed_at, airline_name="THY",
    )
    express_observation = AirModeObservation(
        entry_id="air-mode:inquiry-2", inquiry_reference="inquiry:sha256:002",
        selected_mode="express", evidence_basis="operator_action",
        observed_by="Pilot Operator", observed_at=observed_at, express_provider="FedEx",
    )
    check(commercial_observation.runtime_authoritative is False and express_observation.runtime_authoritative is False,
          "air-versus-express observations remain non-authoritative evidence")
    observation_fields = set(AirModeObservation.model_fields)
    check(not ({"cost", "rate", "price", "surcharge"} & observation_fields),
          "express classification observation has no pricing or surcharge contract")

    cross_mode_rejected = False
    try:
        AirModeObservation(
            entry_id="air-mode:bad", inquiry_reference="inquiry:bad",
            selected_mode="express", evidence_basis="sent_quote",
            observed_by="Pilot Operator", observed_at=observed_at, airline_name="THY",
        )
    except ValidationError:
        cross_mode_rejected = True
    check(cross_mode_rejected, "commercial airline and express provider evidence cannot be conflated")

    with tempfile.TemporaryDirectory(prefix="minai-air-shadow-") as directory:
        db_path = Path(directory) / "pilot.sqlite3"
        store = SQLitePilotStore(db_path, run_id="air-shadow-foundation")
        repo = SQLiteAirShadowRepository(store)

        stored_source, created = repo.create_rate_source(base_source)
        retry_source = base_source.model_copy(update={"source_id": "retry-source", "recorded_at": datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)})
        retried_source, retry_created = repo.create_rate_source(retry_source)
        check(created and not retry_created and stored_source.source_id == retried_source.source_id,
              "air tariff source entry identity is idempotent")

        source_conflict = False
        try:
            repo.create_rate_source(base_source.model_copy(update={"source_id": "conflict", "airline_name": "Other Airline"}))
        except AirShadowConflictError:
            source_conflict = True
        check(source_conflict, "air tariff source entry identity fails closed on conflicting evidence")

        stored_mode, mode_created = repo.create_mode_observation(express_observation)
        retry_mode = express_observation.model_copy(update={"observation_id": "retry-mode", "observed_at": datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)})
        retried_mode, mode_retry_created = repo.create_mode_observation(retry_mode)
        check(mode_created and not mode_retry_created and stored_mode.observation_id == retried_mode.observation_id,
              "air mode observation entry identity is idempotent")

        mode_conflict = False
        try:
            repo.create_mode_observation(express_observation.model_copy(update={"observation_id": "conflict-mode", "selected_mode": "commercial_air", "express_provider": None}))
        except AirShadowConflictError:
            mode_conflict = True
        check(mode_conflict, "air mode observation entry identity fails closed on conflicting classification")

        reopened = SQLiteAirShadowRepository(SQLitePilotStore(db_path, run_id="air-shadow-restart"))
        durable_source = reopened.find_rate_source_by_entry(base_source.entry_id)
        durable_mode = reopened.find_mode_observation_by_entry(express_observation.entry_id)
        check(durable_source is not None and durable_source.sha256_hex == "a" * 64,
              "commercial-air tariff source identity survives SQLite restart")
        check(durable_mode is not None and durable_mode.selected_mode == "express" and durable_mode.express_provider == "FedEx",
              "air-versus-express observation survives SQLite restart")

    for label in passes:
        print(f"PASS {label}")
    for label in failures:
        print(f"FAIL {label}")
    return {"passed": not failures, "passes": passes, "failures": failures}


def main() -> int:
    result = evaluate_air_shadow_foundation_regressions()
    print("\nAir shadow foundation regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
