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
    create_air_rate_structure_review,
    decide_air_rate_structure_candidate,
)
from src.core.air_rate_surcharge_review_repository import (
    InMemoryAirRateSurchargeReviewRepository,
    SQLiteAirRateSurchargeReviewRepository,
)
from src.core.air_rate_surcharge_review_service import (
    AirRateSurchargeReviewTransitionError,
    create_air_rate_surcharge_review,
    decide_air_rate_surcharge_candidate,
    detect_air_rate_surcharge_candidates,
)
from src.core.air_shadow_repository import InMemoryAirShadowRepository, SQLiteAirShadowRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.attachment_safe_extraction_regressions import _pdf_with_text


SURCHARGE_TEXT = """GENERAL CARGO MIN +45 +100 USD
FRA 120 2.50 2.30
FSC USD 0.50 / KG
SECURITY 0.10 USD PER KG
HANDLING EUR 25 / SHIPMENT
AWB USD 30
WAR RISK 2%
"""


def _complete_structure(source, sources, structures, docs):
    review, _ = create_air_rate_structure_review(
        source_id=source.source_id,
        source_repository=sources,
        review_repository=structures,
        document_store=docs,
        requested_by="Pilot Operator",
    )
    for candidate in list(review.candidates):
        review = decide_air_rate_structure_candidate(
            review_id=review.review_id,
            candidate_id=candidate.candidate_id,
            decision="confirm",
            review_note="Verified against synthetic tariff source.",
            reviewed_by="Senior Air Operator",
            repository=structures,
        )
    return review


def evaluate_air_rate_surcharge_review_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    direct = detect_air_rate_surcharge_candidates(
        SURCHARGE_TEXT,
        confirmed_surcharge_lines={
            "FSC": [3], "SECURITY": [4], "HANDLING": [5], "AWB": [6], "WAR_RISK": [7]
        },
    )
    by_code = {item.surcharge_code: item for item in direct}
    check(
        set(by_code) == {"FSC", "SECURITY", "HANDLING"}
        and str(by_code["FSC"].amount) == "0.50"
        and by_code["FSC"].currency == "USD"
        and by_code["FSC"].basis == "per_kg"
        and by_code["HANDLING"].basis == "flat",
        "deterministic surcharge parser accepts only explicit amount currency and unit rows",
    )
    check(
        "AWB" not in by_code and "WAR_RISK" not in by_code,
        "unitless and percentage surcharge lines remain unparsed rather than guessed",
    )
    check(
        all(item.runtime_authoritative is False for item in direct),
        "surcharge amount candidates remain non-authoritative reference evidence",
    )

    pdf = _pdf_with_text(SURCHARGE_TEXT)
    with TemporaryDirectory() as temporary:
        docs = AirRateDocumentStore(Path(temporary) / "docs")
        sources = InMemoryAirShadowRepository()
        structures = InMemoryAirRateStructureReviewRepository()
        surcharges = InMemoryAirRateSurchargeReviewRepository()
        source, _ = register_commercial_air_rate_pdf(
            repository=sources,
            document_store=docs,
            entry_id="surcharge-thy-sep",
            airline_name="THY",
            document_name="thy-surcharge.pdf",
            content_type="application/pdf",
            content=pdf,
            cargo_scope="general_cargo",
            origin_airport="ADA",
            recorded_by="Pilot Operator",
        )
        create_air_rate_structure_review(
            source_id=source.source_id,
            source_repository=sources,
            review_repository=structures,
            document_store=docs,
            requested_by="Pilot Operator",
        )
        blocked = False
        try:
            create_air_rate_surcharge_review(
                source_id=source.source_id,
                source_repository=sources,
                structure_repository=structures,
                review_repository=surcharges,
                document_store=docs,
                requested_by="Pilot Operator",
            )
        except AirRateSurchargeReviewTransitionError as exc:
            blocked = str(exc) == "air_rate_structure_review_must_be_completed"
        check(blocked, "surcharge extraction waits for completed human structure review")

        structure = structures.find_by_source(source.source_id)
        assert structure is not None
        for candidate in list(structure.candidates):
            structure = decide_air_rate_structure_candidate(
                review_id=structure.review_id,
                candidate_id=candidate.candidate_id,
                decision="confirm",
                review_note="Verified before surcharge extraction.",
                reviewed_by="Senior Air Operator",
                repository=structures,
            )
        review, created = create_air_rate_surcharge_review(
            source_id=source.source_id,
            source_repository=sources,
            structure_repository=structures,
            review_repository=surcharges,
            document_store=docs,
            requested_by="Pilot Operator",
        )
        serialized = review.model_dump_json()
        check(
            created and review.ai_parser_called is False and review.runtime_authoritative is False
            and review.status == "pending" and len(review.candidates) == 3,
            "completed structure review unlocks bounded local surcharge proposals",
        )
        check(
            "FSC USD 0.50 / KG" not in serialized and "SECURITY 0.10 USD PER KG" not in serialized,
            "surcharge review stores structured values and source hashes rather than raw source lines",
        )
        check(
            all("application_weight" not in type(item).model_fields for item in review.candidates),
            "surcharge review does not invent an application weight policy",
        )
        retry, retry_created = create_air_rate_surcharge_review(
            source_id=source.source_id,
            source_repository=sources,
            structure_repository=structures,
            review_repository=surcharges,
            document_store=docs,
            requested_by="Another Operator",
        )
        check(not retry_created and retry.review_id == review.review_id,
              "surcharge extraction retry is idempotent per immutable tariff source")
        first = review.candidates[0]
        reviewed = decide_air_rate_surcharge_candidate(
            review_id=review.review_id,
            candidate_id=first.candidate_id,
            decision="confirm",
            review_note="Amount currency and unit match the source.",
            reviewed_by="Senior Air Operator",
            repository=surcharges,
        )
        confirmed = next(item for item in reviewed.candidates if item.candidate_id == first.candidate_id)
        check(
            confirmed.status == "confirmed" and confirmed.runtime_authoritative is False
            and reviewed.status == "partially_reviewed",
            "human surcharge confirmation remains reference-only",
        )
        duplicate_blocked = False
        try:
            decide_air_rate_surcharge_candidate(
                review_id=review.review_id,
                candidate_id=first.candidate_id,
                decision="reject",
                review_note="Conflicting second decision.",
                reviewed_by="Senior Air Operator",
                repository=surcharges,
            )
        except AirRateSurchargeReviewTransitionError:
            duplicate_blocked = True
        check(duplicate_blocked, "reviewed surcharge candidate cannot be silently re-decided")

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = SQLitePilotStore(root / "pilot.sqlite3")
        sources = SQLiteAirShadowRepository(store)
        structures = SQLiteAirRateStructureReviewRepository(store)
        surcharges = SQLiteAirRateSurchargeReviewRepository(store)
        docs = AirRateDocumentStore(root / "air-docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=sources, document_store=docs,
            entry_id="durable-air-surcharge", airline_name="THY",
            document_name="durable-surcharge.pdf", content_type="application/pdf", content=pdf,
            recorded_by="Pilot Operator",
        )
        _complete_structure(source, sources, structures, docs)
        review, _ = create_air_rate_surcharge_review(
            source_id=source.source_id, source_repository=sources,
            structure_repository=structures, review_repository=surcharges,
            document_store=docs, requested_by="Pilot Operator",
        )
        reopened = SQLiteAirRateSurchargeReviewRepository(SQLitePilotStore(root / "pilot.sqlite3"))
        durable = reopened.find_by_source(source.source_id)
        check(durable is not None and durable.review_id == review.review_id
              and durable.extracted_text_sha256 == review.extracted_text_sha256,
              "surcharge review survives SQLite repository reconstruction")
    check(
        "air_rate_surcharge_reviews" in PERSISTENT_STATE_NAMESPACES
        and "air_rate_surcharge_review_by_source" in PERSISTENT_STATE_NAMESPACES,
        "surcharge review evidence is protected from ordinary retention purge",
    )

    from src import api
    with TemporaryDirectory() as temporary:
        api_sources = InMemoryAirShadowRepository()
        api_structures = InMemoryAirRateStructureReviewRepository()
        api_surcharges = InMemoryAirRateSurchargeReviewRepository()
        api_docs = AirRateDocumentStore(Path(temporary) / "api-docs")
        source, _ = register_commercial_air_rate_pdf(
            repository=api_sources, document_store=api_docs,
            entry_id="api-surcharge", airline_name="THY",
            document_name="api-surcharge.pdf", content_type="application/pdf", content=pdf,
            recorded_by="API Operator",
        )
        _complete_structure(source, api_sources, api_structures, api_docs)
        request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
        request.state.pilot_operator = "API Operator"
        originals = (
            api.air_shadow_repository, api.air_rate_document_store,
            api.air_rate_structure_review_repository, api.air_rate_surcharge_review_repository,
        )
        try:
            api.air_shadow_repository = api_sources
            api.air_rate_document_store = api_docs
            api.air_rate_structure_review_repository = api_structures
            api.air_rate_surcharge_review_repository = api_surcharges
            extracted = api.extract_air_rate_surcharges(source.source_id, request)
            listing = api.list_air_rate_surcharge_reviews()
            candidate_id = extracted["review"]["candidates"][0]["candidate_id"]
            decision = api.decide_air_rate_surcharge_candidate_endpoint(
                extracted["review"]["review_id"], candidate_id,
                api.AirRateSurchargeCandidateDecisionRequest(
                    decision="confirm", review_note="Verified amount currency and unit."
                ),
                request,
            )
        finally:
            (
                api.air_shadow_repository, api.air_rate_document_store,
                api.air_rate_structure_review_repository, api.air_rate_surcharge_review_repository,
            ) = originals
        check(
            extracted["ai_parser_called"] is False
            and extracted["pricing_authority_enabled"] is False
            and extracted["calculation_consumption_enabled"] is False
            and listing["application_weight_authority_enabled"] is False
            and listing["calculation_consumption_enabled"] is False
            and decision["pricing_authority_enabled"] is False,
            "controlled API exposes surcharge review without calculation or quote authority",
        )

    check(
        route_allowed("GET", "/air-rate-surcharge-reviews")
        and route_allowed("POST", "/air-rate-sources/source-1/extract-surcharges")
        and route_allowed("POST", "/air-rate-surcharge-reviews/review-1/candidates/candidate-1/decision"),
        "pilot access admits only bounded air surcharge extraction and review routes",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_rate_surcharge_review_service.py").read_text(encoding="utf-8")
    check(
        "Surcharge Tutarlarını Çıkar" in js
        and "Surcharge Tutar İncelemeleri" in js
        and "Reviewed Surcharge Cost Preview" in js
        and "Base Navlun Önizleme surcharge içermez" in js
        and "openai" not in service.casefold(),
        "browser exposes human surcharge review while keeping calculation and AI boundaries explicit",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_surcharge_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir rate surcharge review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
