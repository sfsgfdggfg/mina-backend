from datetime import datetime, timezone
from pathlib import Path
from starlette.requests import Request
from src.core.air_shadow import AirRateSource
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.air_rate_surcharge_review import AirRateSurchargeCandidate, AirRateSurchargeReview
from src.core.air_rate_surcharge_review_repository import InMemoryAirRateSurchargeReviewRepository
from src.core.air_rate_surcharge_review_service import AirRateSurchargeReviewTransitionError, decide_air_rate_surcharge_operational_conditions
from src.core.pilot_access import route_allowed

NOW=datetime(2026,9,13,9,20,tzinfo=timezone.utc)

def _source(cargo_scope="general_cargo"):
    repo=InMemoryAirShadowRepository(); src=AirRateSource(source_id="air-source-conditions",entry_id="conditions-source",airline_name="THY",document_name="conditions.pdf",sha256_hex="a"*64,cargo_scope=cargo_scope,origin_airport="ADA",recorded_by="Air Operator",recorded_at=NOW); repo.create_rate_source(src); return repo

def _review():
    c=AirRateSurchargeCandidate(candidate_id="conditions-candidate-001",surcharge_code="FSC",amount="0.50",currency="USD",basis="per_kg",source_line_number=3,source_line_sha256="b"*64,status="confirmed",reviewed_by="Air Operator",reviewed_at=NOW,review_note="Amount verified.",application_basis="chargeable_weight",application_basis_reviewed_by="Air Operator",application_basis_reviewed_at=NOW,application_basis_review_note="Basis verified.",applicability_scope="source_wide",applicability_reviewed_by="Air Operator",applicability_reviewed_at=NOW,applicability_review_note="Scope verified.")
    return AirRateSurchargeReview(review_id="conditions-review-001",source_id="air-source-conditions",source_sha256="a"*64,structure_review_id="structure-1",extracted_text_sha256="c"*64,candidates=[c],status="completed",requested_by="Air Operator",created_at=NOW)

def evaluate_air_rate_surcharge_operational_conditions_regressions():
    passes=[]; failures=[]
    def check(x,label):(passes if x else failures).append(label)
    repo=InMemoryAirRateSurchargeReviewRepository(); review,_=repo.create(_review()); sources=_source()
    out=decide_air_rate_surcharge_operational_conditions(review_id=review.review_id,candidate_id=review.candidates[0].candidate_id,cargo_applicability="source_scope",routing_applicability="direct_only",via_airport=None,review_note="Source cargo scope and direct routing verified.",reviewed_by="Senior Air Operator",repository=repo,source_repository=sources,reviewed_at=NOW)
    item=out.candidates[0]
    check(item.cargo_applicability=="source_scope" and item.routing_applicability=="direct_only" and item.runtime_authoritative is False,"human review records bounded cargo and routing conditions without runtime authority")
    dup=False
    try: decide_air_rate_surcharge_operational_conditions(review_id=review.review_id,candidate_id=item.candidate_id,cargo_applicability="source_scope",routing_applicability="connecting_only",via_airport=None,review_note="second",reviewed_by="Air Operator",repository=repo,source_repository=sources)
    except AirRateSurchargeReviewTransitionError: dup=True
    check(dup,"reviewed surcharge operational conditions cannot be silently re-decided")
    via_repo=InMemoryAirRateSurchargeReviewRepository(); vr,_=via_repo.create(_review().model_copy(update={"review_id":"via-review"})); via=decide_air_rate_surcharge_operational_conditions(review_id=vr.review_id,candidate_id=vr.candidates[0].candidate_id,cargo_applicability="general_cargo",routing_applicability="via_airport",via_airport="ist",review_note="Via IST verified.",reviewed_by="Air Operator",repository=via_repo,source_repository=sources,reviewed_at=NOW)
    check(via.candidates[0].routing_via_airport=="IST","via-airport routing condition requires and normalizes explicit airport evidence")
    bad=False
    try:
        r=InMemoryAirRateSurchargeReviewRepository(); rr,_=r.create(_review().model_copy(update={"review_id":"bad-cargo"})); decide_air_rate_surcharge_operational_conditions(review_id=rr.review_id,candidate_id=rr.candidates[0].candidate_id,cargo_applicability="special_cargo",routing_applicability="direct_only",via_airport=None,review_note="conflict",reviewed_by="Air Operator",repository=r,source_repository=sources)
    except AirRateSurchargeReviewTransitionError: bad=True
    check(bad,"operational review fails closed on cargo scope conflicting with immutable source")
    unknown=False
    try:
        r=InMemoryAirRateSurchargeReviewRepository(); rr,_=r.create(_review().model_copy(update={"review_id":"unknown-cargo"})); decide_air_rate_surcharge_operational_conditions(review_id=rr.review_id,candidate_id=rr.candidates[0].candidate_id,cargo_applicability="source_scope",routing_applicability="direct_only",via_airport=None,review_note="unknown",reviewed_by="Air Operator",repository=r,source_repository=_source("unknown"))
    except AirRateSurchargeReviewTransitionError: unknown=True
    check(unknown,"unknown source cargo scope cannot become calculation-ready condition evidence")
    from src import api
    api_repo=InMemoryAirRateSurchargeReviewRepository(); ar,_=api_repo.create(_review().model_copy(update={"review_id":"api-conditions"})); req=Request({"type":"http","method":"POST","path":"/","headers":[]}); req.state.pilot_operator="API Air Operator"; orig=(api.air_rate_surcharge_review_repository,api.air_shadow_repository)
    try:
        api.air_rate_surcharge_review_repository=api_repo; api.air_shadow_repository=sources; response=api.decide_air_rate_surcharge_operational_conditions_endpoint(ar.review_id,ar.candidates[0].candidate_id,api.AirRateSurchargeOperationalConditionsRequest(cargo_applicability="general_cargo",routing_applicability="connecting_only",review_note="Verified connecting condition."),req)
    finally: api.air_rate_surcharge_review_repository,api.air_shadow_repository=orig
    check(response["calculation_consumption_enabled"] is False and response["pricing_authority_enabled"] is False,"controlled API stores operational-condition evidence without calculation authority")
    check(route_allowed("POST","/air-rate-surcharge-reviews/r/candidates/c/operational-conditions"),"pilot access admits bounded surcharge operational-condition review")
    root=Path(__file__).resolve().parents[2]; js=(root/"ui/web_shell/app.js").read_text(); preview=(root/"src/core/air_freight_calculation_preview.py").read_text()
    check("Operasyon Koşullarını Doğrula" in js and "Bu review de surcharge hesap tüketimini açmaz" in js,"browser exposes explicit cargo and routing review with authority boundary")
    check("air_rate_surcharge" not in preview and "AirRateSurcharge" not in preview,"freight preview still does not consume operational-condition evidence")
    return {"passed":not failures,"passes":passes,"failures":failures}

if __name__=="__main__":
    r=evaluate_air_rate_surcharge_operational_conditions_regressions()
    [print("PASS "+x) for x in r["passes"]]; [print("FAIL "+x) for x in r["failures"]]
    print("\nAir surcharge operational-condition regressions: "+("PASS" if r["passed"] else "FAIL")); raise SystemExit(0 if r["passed"] else 1)
