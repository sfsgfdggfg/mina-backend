from __future__ import annotations

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
    AirRateStructureReviewTransitionError,
    create_air_rate_structure_review,
    decide_air_rate_structure_candidate,
    detect_air_rate_structure_candidates,
)
from src.core.air_shadow_repository import (
    InMemoryAirShadowRepository,
    SQLiteAirShadowRepository,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.attachment_safe_extraction_regressions import _pdf_with_text


STRUCTURE_TEXT = (
    "GENERAL CARGO MIN +45 +100 +300 +500 +1000 USD FSC SECURITY AWB HANDLING "
    "VOLUMETRIC / 6000 RATE 9.99"
)


def evaluate_air_rate_structure_review_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    candidates = detect_air_rate_structure_candidates(STRUCTURE_TEXT)
    found = {(item.kind, item.value) for item in candidates}
    check(
        {
            ("weight_break", "MIN"), ("weight_break", "+45"),
            ("weight_break", "+100"), ("weight_break", "+300"),
            ("weight_break", "+500"), ("weight_break", "+1000"),
            ("currency", "USD"), ("surcharge_label", "FSC"),
            ("surcharge_label", "SECURITY"), ("surcharge_label", "AWB"),
            ("surcharge_label", "HANDLING"), ("volumetric_divisor", "6000"),
            ("cargo_scope_hint", "general_cargo"),
        }.issubset(found),
        "deterministic local parser detects bounded air-tariff structure labels",
    )
    check(all(item.runtime_authoritative is False for item in candidates),
          "detected structure candidates never carry pricing authority")

    pdf = _pdf_with_text(STRUCTURE_TEXT)
    with TemporaryDirectory() as temporary:
        doc_store = AirRateDocumentStore(Path(temporary) / "docs")
        sources = InMemoryAirShadowRepository()
        reviews = InMemoryAirRateStructureReviewRepository()
        source, _ = register_commercial_air_rate_pdf(
            repository=sources, document_store=doc_store,
            entry_id="structure-thy-sep", airline_name="THY",
            document_name="thy-structure.pdf", content_type="application/pdf",
            content=pdf, cargo_scope="general_cargo", origin_airport="ADA",
            recorded_by="Pilot Operator",
        )
        review, created = create_air_rate_structure_review(
            source_id=source.source_id, source_repository=sources,
            review_repository=reviews, document_store=doc_store,
            requested_by="Pilot Operator",
        )
        serialized = review.model_dump_json()
        check(created and review.ai_parser_called is False and review.runtime_authoritative is False
              and review.status == "pending" and len(review.candidates) >= 10,
              "stored commercial-air PDF yields non-AI proposed structure review")
        check(STRUCTURE_TEXT not in serialized and "RATE 9.99" not in serialized and "9.99" not in serialized,
              "full extracted tariff text and numeric rate row are not persisted in structure review")
        retry, retry_created = create_air_rate_structure_review(
            source_id=source.source_id, source_repository=sources,
            review_repository=reviews, document_store=doc_store,
            requested_by="Another Operator",
        )
        check(not retry_created and retry.review_id == review.review_id,
              "structure extraction retry is idempotent per immutable air-rate source")

        first = review.candidates[0]
        reviewed = decide_air_rate_structure_candidate(
            review_id=review.review_id, candidate_id=first.candidate_id,
            decision="confirm", review_note="Label matches the tariff header.",
            reviewed_by="Senior Air Operator", repository=reviews,
        )
        confirmed = next(item for item in reviewed.candidates if item.candidate_id == first.candidate_id)
        check(confirmed.status == "confirmed" and confirmed.runtime_authoritative is False
              and reviewed.status == "partially_reviewed",
              "human confirmation records review evidence but remains reference-only")
        duplicate_blocked = False
        try:
            decide_air_rate_structure_candidate(
                review_id=review.review_id, candidate_id=first.candidate_id,
                decision="reject", review_note="Conflicting second decision.",
                reviewed_by="Senior Air Operator", repository=reviews,
            )
        except AirRateStructureReviewTransitionError:
            duplicate_blocked = True
        check(duplicate_blocked, "reviewed air-rate structure candidate cannot be silently re-decided")

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        sqlite_store = SQLitePilotStore(root / "pilot.sqlite3")
        sources = SQLiteAirShadowRepository(sqlite_store)
        reviews = SQLiteAirRateStructureReviewRepository(sqlite_store)
        doc_store = AirRateDocumentStore(root / "air-docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=sources, document_store=doc_store,
            entry_id="durable-air-structure", airline_name="THY",
            document_name="durable.pdf", content_type="application/pdf", content=pdf,
            recorded_by="Pilot Operator",
        )
        review, _ = create_air_rate_structure_review(
            source_id=source.source_id, source_repository=sources,
            review_repository=reviews, document_store=doc_store,
            requested_by="Pilot Operator",
        )
        reopened = SQLiteAirRateStructureReviewRepository(SQLitePilotStore(root / "pilot.sqlite3"))
        durable = reopened.find_by_source(source.source_id)
        check(durable is not None and durable.review_id == review.review_id
              and durable.extracted_text_sha256 == review.extracted_text_sha256,
              "air-rate structure review survives SQLite repository reconstruction")
    check(
        "air_rate_structure_reviews" in PERSISTENT_STATE_NAMESPACES
        and "air_rate_structure_review_by_source" in PERSISTENT_STATE_NAMESPACES,
        "air-rate structure review evidence is protected from ordinary retention purge",
    )

    from src import api
    with TemporaryDirectory() as temporary:
        api_sources = InMemoryAirShadowRepository()
        api_reviews = InMemoryAirRateStructureReviewRepository()
        api_docs = AirRateDocumentStore(Path(temporary) / "api-docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=api_sources, document_store=api_docs,
            entry_id="api-structure", airline_name="THY",
            document_name="api-structure.pdf", content_type="application/pdf", content=pdf,
            recorded_by="API Operator",
        )
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.pilot_operator = "API Operator"
        originals = (
            api.air_shadow_repository,
            api.air_rate_document_store,
            api.air_rate_structure_review_repository,
        )
        try:
            api.air_shadow_repository = api_sources
            api.air_rate_document_store = api_docs
            api.air_rate_structure_review_repository = api_reviews
            extracted = api.extract_air_rate_structure(source.source_id, request)
            listing = api.list_air_rate_structure_reviews()
            candidate_id = extracted["review"]["candidates"][0]["candidate_id"]
            decision = api.decide_air_rate_structure_candidate_endpoint(
                extracted["review"]["review_id"], candidate_id,
                api.AirRateStructureCandidateDecisionRequest(
                    decision="confirm", review_note="Verified against visible tariff label."
                ),
                request,
            )
        finally:
            (
                api.air_shadow_repository,
                api.air_rate_document_store,
                api.air_rate_structure_review_repository,
            ) = originals
        check(
            extracted["ai_parser_called"] is False
            and extracted["runtime_authoritative"] is False
            and listing["ai_interpretation_enabled"] is False
            and listing["raw_extracted_text_persisted"] is False
            and decision["pricing_authority_enabled"] is False,
            "controlled API exposes deterministic review flow without AI or pricing authority",
        )

    check(
        route_allowed("POST", "/air-rate-sources/source-1/extract-structure")
        and route_allowed("GET", "/air-rate-structure-reviews")
        and route_allowed("POST", "/air-rate-structure-reviews/review-1/candidates/candidate-1/decision"),
        "pilot access admits only bounded air-rate structure extraction and review routes",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_rate_structure_review_service.py").read_text(encoding="utf-8")
    check(
        "Yapıyı Çıkar" in js
        and "/extract-structure" in js
        and "/air-rate-structure-reviews/" in js
        and "AI parser: hayır" in js
        and "İnceleme notu gerekli." in js
        and "openai" not in service.casefold(),
        "browser exposes human structure review while local service has no OpenAI dependency",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_structure_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir rate structure review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
