from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_rate_document_store import AirRateDocumentStore
from src.core.air_rate_source_service import register_commercial_air_rate_pdf
from src.core.air_rate_structure_review_repository import (
    InMemoryAirRateStructureReviewRepository,
    SQLiteAirRateStructureReviewRepository,
)
from src.core.air_rate_structure_review_service import (
    create_air_rate_structure_review,
    decide_air_rate_structure_candidate,
)
from src.core.air_rate_table_review_repository import (
    InMemoryAirRateTableReviewRepository,
    SQLiteAirRateTableReviewRepository,
)
from src.core.air_rate_table_review_service import (
    AirRateTableReviewTransitionError,
    create_air_rate_table_review,
    decide_air_rate_table_row,
    detect_air_rate_table_candidates,
)
from src.core.air_shadow_repository import InMemoryAirShadowRepository, SQLiteAirShadowRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.attachment_safe_extraction_regressions import _pdf_with_text


TABLE_TEXT = """GENERAL CARGO USD MIN +45 +100 +300 +500 +1000
FRA 120.00 2.50 2.30 2.10 1.90 1.70
MUC 125 2,60 2,40 2,20 2,00 1,80
FSC 0.50 0.50 0.50 0.50 0.50 0.50
BROKEN 100 2.1 1.9
"""
BREAKS = ["MIN", "+45", "+100", "+300", "+500", "+1000"]


def _complete_structure(source_id, sources, structures, docs):
    review, _ = create_air_rate_structure_review(
        source_id=source_id,
        source_repository=sources,
        review_repository=structures,
        document_store=docs,
        requested_by="Pilot Operator",
    )
    for candidate in list(review.candidates):
        decision = "confirm" if candidate.kind in {"weight_break", "currency"} else "reject"
        review = decide_air_rate_structure_candidate(
            review_id=review.review_id,
            candidate_id=candidate.candidate_id,
            decision=decision,
            review_note="Synthetic table-review prerequisite decision.",
            reviewed_by="Senior Air Operator",
            repository=structures,
        )
    return review


def evaluate_air_rate_table_review_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    rows = detect_air_rate_table_candidates(
        TABLE_TEXT,
        confirmed_weight_breaks=BREAKS,
        confirmed_currencies=["USD"],
    )
    check(
        len(rows) == 2 and [item.destination_code for item in rows] == ["FRA", "MUC"]
        and rows[0].rates["MIN"] == Decimal("120.00")
        and rows[0].rates["+1000"] == Decimal("1.70"),
        "deterministic table parser accepts only exact-width destination rows",
    )
    check(
        all(item.destination_label != "FSC" for item in rows)
        and all(item.destination_label != "BROKEN" for item in rows),
        "surcharge and incomplete numeric lines are not misclassified as tariff rows",
    )
    check(all(item.runtime_authoritative is False for item in rows),
          "numeric tariff row candidates are reference-only")

    pdf = _pdf_with_text(TABLE_TEXT)
    with TemporaryDirectory() as temporary:
        docs = AirRateDocumentStore(Path(temporary) / "docs")
        sources = InMemoryAirShadowRepository()
        structures = InMemoryAirRateStructureReviewRepository()
        tables = InMemoryAirRateTableReviewRepository()
        source, _ = register_commercial_air_rate_pdf(
            repository=sources, document_store=docs,
            entry_id="table-thy-sep", airline_name="THY",
            document_name="thy-table.pdf", content_type="application/pdf",
            content=pdf, cargo_scope="general_cargo", origin_airport="ADA",
            recorded_by="Pilot Operator",
        )
        create_air_rate_structure_review(
            source_id=source.source_id, source_repository=sources,
            review_repository=structures, document_store=docs,
            requested_by="Pilot Operator",
        )
        blocked = False
        try:
            create_air_rate_table_review(
                source_id=source.source_id, source_repository=sources,
                structure_repository=structures, review_repository=tables,
                document_store=docs, requested_by="Pilot Operator",
            )
        except AirRateTableReviewTransitionError as exc:
            blocked = str(exc) == "air_rate_structure_review_must_be_completed"
        check(blocked, "numeric row extraction waits for completed human structure review")

        structure = structures.find_by_source(source.source_id)
        for candidate in list(structure.candidates):
            structure = decide_air_rate_structure_candidate(
                review_id=structure.review_id, candidate_id=candidate.candidate_id,
                decision="confirm" if candidate.kind in {"weight_break", "currency"} else "reject",
                review_note="Verified prerequisite structure.", reviewed_by="Senior Air Operator",
                repository=structures,
            )
        review, created = create_air_rate_table_review(
            source_id=source.source_id, source_repository=sources,
            structure_repository=structures, review_repository=tables,
            document_store=docs, requested_by="Pilot Operator",
        )
        serialized = review.model_dump_json()
        check(
            created and review.ai_parser_called is False and review.runtime_authoritative is False
            and review.status == "pending" and len(review.candidates) == 2,
            "completed structure review unlocks bounded local tariff-row proposals",
        )
        check(
            "FRA 120.00 2.50" not in serialized and "MUC 125 2,60" not in serialized,
            "table review stores structured rates and source hashes rather than raw tariff lines",
        )
        retry, retry_created = create_air_rate_table_review(
            source_id=source.source_id, source_repository=sources,
            structure_repository=structures, review_repository=tables,
            document_store=docs, requested_by="Another Operator",
        )
        check(not retry_created and retry.review_id == review.review_id,
              "tariff-row extraction retry is idempotent per immutable source")

        first = review.candidates[0]
        decided = decide_air_rate_table_row(
            review_id=review.review_id, candidate_id=first.candidate_id,
            decision="confirm", review_note="Destination and every weight-break column match the PDF.",
            reviewed_by="Senior Air Operator", repository=tables,
        )
        confirmed = next(item for item in decided.candidates if item.candidate_id == first.candidate_id)
        check(
            confirmed.status == "confirmed" and confirmed.runtime_authoritative is False
            and decided.status == "partially_reviewed",
            "human row confirmation remains non-authoritative reference evidence",
        )

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = SQLitePilotStore(root / "pilot.sqlite3")
        sources = SQLiteAirShadowRepository(store)
        structures = SQLiteAirRateStructureReviewRepository(store)
        tables = SQLiteAirRateTableReviewRepository(store)
        docs = AirRateDocumentStore(root / "docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=sources, document_store=docs,
            entry_id="durable-table", airline_name="THY", document_name="durable-table.pdf",
            content_type="application/pdf", content=pdf, recorded_by="Pilot Operator",
        )
        _complete_structure(source.source_id, sources, structures, docs)
        review, _ = create_air_rate_table_review(
            source_id=source.source_id, source_repository=sources,
            structure_repository=structures, review_repository=tables,
            document_store=docs, requested_by="Pilot Operator",
        )
        reopened_store = SQLitePilotStore(root / "pilot.sqlite3")
        durable = SQLiteAirRateTableReviewRepository(reopened_store).find_by_source(source.source_id)
        check(durable is not None and durable.review_id == review.review_id and len(durable.candidates) == 2,
              "structured tariff-row review survives SQLite repository reconstruction")
    check(
        "air_rate_table_reviews" in PERSISTENT_STATE_NAMESPACES
        and "air_rate_table_review_by_source" in PERSISTENT_STATE_NAMESPACES,
        "structured tariff-row review evidence is protected from ordinary retention purge",
    )

    from src import api
    with TemporaryDirectory() as temporary:
        api_sources = InMemoryAirShadowRepository()
        api_structures = InMemoryAirRateStructureReviewRepository()
        api_tables = InMemoryAirRateTableReviewRepository()
        api_docs = AirRateDocumentStore(Path(temporary) / "api-docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=api_sources, document_store=api_docs,
            entry_id="api-table", airline_name="THY", document_name="api-table.pdf",
            content_type="application/pdf", content=pdf, recorded_by="API Operator",
        )
        _complete_structure(source.source_id, api_sources, api_structures, api_docs)
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.pilot_operator = "API Operator"
        originals = (
            api.air_shadow_repository, api.air_rate_document_store,
            api.air_rate_structure_review_repository, api.air_rate_table_review_repository,
        )
        try:
            api.air_shadow_repository = api_sources
            api.air_rate_document_store = api_docs
            api.air_rate_structure_review_repository = api_structures
            api.air_rate_table_review_repository = api_tables
            extracted = api.extract_air_rate_table(source.source_id, request)
            listing = api.list_air_rate_table_reviews()
            candidate_id = extracted["review"]["candidates"][0]["candidate_id"]
            decision = api.decide_air_rate_table_row_endpoint(
                extracted["review"]["review_id"], candidate_id,
                api.AirRateTableRowDecisionRequest(
                    decision="confirm", review_note="Checked against synthetic tariff."
                ), request,
            )
        finally:
            (
                api.air_shadow_repository, api.air_rate_document_store,
                api.air_rate_structure_review_repository, api.air_rate_table_review_repository,
            ) = originals
        check(
            extracted["ai_parser_called"] is False
            and extracted["pricing_authority_enabled"] is False
            and listing["structured_numeric_reference_enabled"] is True
            and listing["quote_calculation_enabled"] is False
            and decision["pricing_authority_enabled"] is False,
            "controlled API exposes row review without opening air pricing authority",
        )

    check(
        route_allowed("POST", "/air-rate-sources/source-1/extract-table")
        and route_allowed("GET", "/air-rate-table-reviews")
        and route_allowed("POST", "/air-rate-table-reviews/review-1/rows/row-1/decision"),
        "pilot access admits only bounded air-rate table extraction and review routes",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_rate_table_review_service.py").read_text(encoding="utf-8")
    check(
        "Tarife Satırlarını Çıkar" in js and "/extract-table" in js
        and "/air-rate-table-reviews/" in js and "Satırı Doğrula" in js
        and "quote hesabına" in js and "openai" not in service.casefold(),
        "browser exposes row review and makes the no-pricing boundary explicit",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_table_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir rate table review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
