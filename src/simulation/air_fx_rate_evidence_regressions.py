from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_fx_rate_evidence_repository import (
    InMemoryAirFxRateEvidenceRepository,
    SQLiteAirFxRateEvidenceRepository,
)
from src.core.air_fx_rate_evidence_service import (
    AirFxRateEvidenceTransitionError,
    record_air_fx_rate_evidence,
)
from src.core.air_reviewed_surcharge_cost_preview import build_air_reviewed_surcharge_cost_preview
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _source_repo, _standard_repo

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
EFFECTIVE = datetime(2026, 9, 13, 11, 30, tzinfo=timezone.utc)


def _record(repo, source_repo, **overrides):
    payload = {
        "source_id": "source-0001",
        "entry_id": "air-fx-evidence-0001",
        "inquiry_reference": "MINA2026/FX-1",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "rate": Decimal("1.10"),
        "effective_at": EFFECTIVE,
        "evidence_source": "bank",
        "evidence_reference": "Bank bulletin FX-0913",
        "evidence_note": "Exact pair and timestamp checked by operator.",
        "recorded_by": "Senior Air Operator",
        "recorded_at": NOW,
        "source_repository": source_repo,
        "repository": repo,
    }
    payload.update(overrides)
    return record_air_fx_rate_evidence(**payload)


def evaluate_air_fx_rate_evidence_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    repo = InMemoryAirFxRateEvidenceRepository()
    item, created = _record(repo, source_repo)
    check(
        created is True
        and item.base_currency == "EUR"
        and item.quote_currency == "USD"
        and item.rate == Decimal("1.10")
        and item.source_sha256 == source_repo.get_rate_source("source-0001").sha256_hex
        and item.runtime_authoritative is False
        and item.pricing_authority is False,
        "FX evidence preserves explicit 1 BASE = rate QUOTE direction without pricing authority",
    )

    same, created_again = _record(repo, source_repo)
    check(
        created_again is False and same.evidence_id == item.evidence_id,
        "FX evidence entry identity is idempotent for identical evidence",
    )

    conflict_blocked = False
    try:
        _record(repo, source_repo, rate=Decimal("1.11"))
    except AirFxRateEvidenceTransitionError:
        conflict_blocked = True
    check(conflict_blocked, "FX evidence entry identity fails closed when reused with a different rate")

    same_currency_blocked = False
    try:
        _record(
            InMemoryAirFxRateEvidenceRepository(),
            source_repo,
            entry_id="air-fx-same-currency",
            base_currency="USD",
            quote_currency="USD",
        )
    except AirFxRateEvidenceTransitionError:
        same_currency_blocked = True
    check(same_currency_blocked, "FX evidence rejects same-currency pairs instead of manufacturing a conversion")

    naive_time_blocked = False
    try:
        _record(
            InMemoryAirFxRateEvidenceRepository(),
            source_repo,
            entry_id="air-fx-naive-time",
            effective_at=datetime(2026, 9, 13, 11, 30),
        )
    except AirFxRateEvidenceTransitionError:
        naive_time_blocked = True
    check(naive_time_blocked, "FX evidence requires an explicit timezone-aware effective timestamp")

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirFxRateEvidenceRepository(SQLitePilotStore(db_path))
        persisted, _ = _record(sqlite_repo, source_repo, recorded_by="Persistence Operator")
        restored = SQLiteAirFxRateEvidenceRepository(SQLitePilotStore(db_path)).get(persisted.evidence_id)
        check(
            restored is not None
            and restored.entry_id == persisted.entry_id
            and restored.base_currency == "EUR"
            and restored.quote_currency == "USD"
            and restored.rate == Decimal("1.10")
            and restored.recorded_by == "Persistence Operator",
            "FX evidence survives SQLite repository reconstruction",
        )
    check(
        "air_fx_rate_evidence" in PERSISTENT_STATE_NAMESPACES
        and "air_fx_rate_evidence_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "FX evidence is protected from ordinary retention purge",
    )

    preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_standard_repo(),
        source_repository=source_repo,
    )
    reasons = {(entry.surcharge_code, entry.reason) for entry in preview.excluded_surcharges}
    check(
        ("SSC", "currency_mismatch_no_fx") in reasons
        and preview.fx_applied is False,
        "recorded FX evidence does not silently enter the existing cross-currency surcharge preview",
    )

    from src import api
    api_repo = InMemoryAirFxRateEvidenceRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (api.air_shadow_repository, api.air_fx_rate_evidence_repository)
    try:
        api.air_shadow_repository = source_repo
        api.air_fx_rate_evidence_repository = api_repo
        response = api.create_air_fx_rate_evidence(
            "source-0001",
            api.AirFxRateEvidenceRequest(
                entry_id="api-air-fx-0001",
                inquiry_reference="MINA2026/API-FX",
                base_currency="eur",
                quote_currency="usd",
                rate=1.10,
                effective_at=EFFECTIVE,
                evidence_source="bank",
                evidence_reference="Bank bulletin API-1",
                evidence_note="Pair and timestamp verified.",
            ),
            request,
        )
    finally:
        api.air_shadow_repository, api.air_fx_rate_evidence_repository = originals
    check(
        response["evidence"]["recorded_by"] == "API Air Operator"
        and response["evidence"]["base_currency"] == "EUR"
        and response["evidence"]["quote_currency"] == "USD"
        and response["pricing_authority_enabled"] is False
        and response["cost_preview_consumption_enabled"] is False
        and response["automatic_fx_enabled"] is False,
        "controlled API records authenticated directional FX evidence without calculation authority",
    )

    check(
        route_allowed("GET", "/air-fx-rate-evidence")
        and route_allowed("POST", "/air-rate-sources/source-1/fx-rate-evidence"),
        "pilot access admits only the bounded FX evidence read/write surfaces",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_fx_rate_evidence_service.py").read_text(encoding="utf-8")
    preview_source = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    check(
        "FX Rate Evidence" in js
        and "1 BASE = rate QUOTE" in js
        and "1 BASE = rate QUOTE" in js
        and "ISO-8601 + offset" in js
        and "explicit" in js.casefold()
        and "fx_evidence_ids" in preview_source
        and "openai" not in service.casefold(),
        "browser exposes directional timestamped FX evidence while automatic FX and AI consumption remain closed",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_fx_rate_evidence_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir FX rate evidence regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
