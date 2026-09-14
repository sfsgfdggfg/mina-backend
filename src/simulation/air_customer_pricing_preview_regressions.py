from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.air_customer_pricing_preview import (
    AirCustomerPricingPreviewError,
    build_air_customer_pricing_preview,
)
from src.core.master_data import CustomerMasterProfile
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.pricing_policy import AGENCY_PRICING_POLICY_ENV, PricingFormula
from src.core.pilot_access import route_allowed
from src.simulation.air_cost_completeness_preview_regressions import (
    INQUIRY,
    _rounding_repo,
    _setup,
)
from src.simulation.air_additional_cost_consumption_regressions import _simple_surcharges
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo


NOW = datetime(2026, 9, 14, 11, 20, tzinfo=timezone.utc)
AGENCY_15_NO_ROUNDING = '{"default_formula":{"method":"cost_markup_percentage","value":15},"default_rounding":{"mode":"none"}}'
AGENCY_15_USD_UP_10 = '{"default_formula":{"method":"cost_markup_percentage","value":15},"default_rounding":{"mode":"none"},"currency_rounding":{"USD":{"mode":"up","increment":10}}}'


def _customer_repo(*, formula: PricingFormula | None, active: bool = True, name: str = "Air Customer"):
    repo = InMemoryMasterDataRepository()
    profile = CustomerMasterProfile(
        entry_id=f"master-{name.lower().replace(' ', '-')}",
        customer_name=name,
        active=active,
        pricing_policy=formula,
        created_at=NOW,
        updated_at=NOW,
        updated_by="Pricing Admin",
    )
    repo.create_customer(profile)
    return repo, profile


def _preview(*, customer_repo, customer_id, additional_ids, quote_override=None, environ=None, setup=None):
    source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo, pickup, delivery = setup or _setup()
    return build_air_customer_pricing_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        cost_scope_review_id=scope.review_id,
        unsupported_cost_semantics_review_id=semantics.review_id,
        inquiry_reference=INQUIRY,
        customer_id=customer_id,
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        shipment_count=1,
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=source_repo,
        scope_repository=scope_repo,
        unsupported_semantics_repository=semantics_repo,
        additional_cost_repository=additional_repo,
        additional_cost_evidence_ids=additional_ids,
        rounding_repository=_rounding_repo(),
        master_data_repository=customer_repo,
        quote_pricing_override=quote_override,
        environ=environ,
    )


def evaluate_air_customer_pricing_preview_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    setup = _setup()
    pickup, delivery = setup[-2], setup[-1]
    ids = [pickup.evidence_id, delivery.evidence_id]

    customer_repo, customer = _customer_repo(formula=PricingFormula(method="fixed_profit", value=100))
    priced = _preview(customer_repo=customer_repo, customer_id=customer.customer_id, additional_ids=ids, environ={}, setup=setup)
    quote = priced.customer_price_preview
    check(
        priced.pricing_status == "priced_preview"
        and priced.customer_price_preview_available is True
        and quote is not None
        and quote.supplier_cost == 943.5
        and quote.final_price == 1043.5
        and priced.pricing_policy is not None
        and priced.pricing_policy.policy_source == "customer_policy",
        "confirmed air cost basis reuses verified customer master pricing policy through the existing pricing engine",
    )
    check(
        priced.quote_ready is False
        and priced.quote_created is False
        and priced.quote_send_authority is False
        and priced.booking_authority is False
        and priced.outbound_authority is False
        and priced.runtime_authoritative is False,
        "air customer price remains preview-only with no quote send booking outbound or runtime authority",
    )

    override = _preview(
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        additional_ids=ids,
        quote_override=PricingFormula(method="fixed_profit", value=250),
        environ={AGENCY_PRICING_POLICY_ENV: AGENCY_15_NO_ROUNDING},
        setup=setup,
    )
    check(
        override.customer_price_preview is not None
        and override.customer_price_preview.final_price == 1193.5
        and override.pricing_policy.policy_source == "quote_override",
        "explicit quote pricing override outranks customer and agency pricing policy",
    )

    agency_repo, agency_customer = _customer_repo(formula=None, name="Agency Default Customer")
    agency = _preview(
        customer_repo=agency_repo,
        customer_id=agency_customer.customer_id,
        additional_ids=ids,
        environ={AGENCY_PRICING_POLICY_ENV: AGENCY_15_NO_ROUNDING},
        setup=setup,
    )
    check(
        agency.customer_price_preview is not None
        and agency.customer_price_preview.final_price == 1085.025
        and agency.pricing_policy.policy_source == "agency_default",
        "agency default pricing is used only when no quote override or customer policy exists",
    )

    rounded = _preview(
        customer_repo=agency_repo,
        customer_id=agency_customer.customer_id,
        additional_ids=ids,
        environ={AGENCY_PRICING_POLICY_ENV: AGENCY_15_USD_UP_10},
        setup=setup,
    )
    check(
        rounded.customer_price_preview is not None
        and rounded.customer_price_preview.final_price == 1090.0
        and rounded.pricing_policy.rounding.mode == "up"
        and rounded.pricing_policy.rounding.increment == 10,
        "air pricing inherits the existing currency rounding policy instead of inventing air-specific rounding",
    )

    gross_repo, gross_customer = _customer_repo(
        formula=PricingFormula(method="gross_margin_percentage", value=20), name="Gross Margin Customer"
    )
    gross = _preview(customer_repo=gross_repo, customer_id=gross_customer.customer_id, additional_ids=ids, environ={}, setup=setup)
    check(
        gross.customer_price_preview is not None
        and gross.customer_price_preview.final_price == 1179.375
        and gross.customer_price_preview.markup_type == "gross_margin_percentage",
        "gross-margin pricing semantics remain identical to the shared pricing engine",
    )

    manual = _preview(
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        additional_ids=ids,
        quote_override=PricingFormula(method="manual_sell_price", value=1500),
        environ={AGENCY_PRICING_POLICY_ENV: AGENCY_15_USD_UP_10},
        setup=setup,
    )
    check(
        manual.customer_price_preview is not None
        and manual.customer_price_preview.final_price == 1500
        and manual.pricing_policy.policy_source == "quote_override",
        "explicit manual sell-price override remains auditable and bypasses formula rounding exactly as shared policy defines",
    )

    missing_policy = _preview(
        customer_repo=agency_repo,
        customer_id=agency_customer.customer_id,
        additional_ids=ids,
        environ={},
        setup=setup,
    )
    check(
        missing_policy.pricing_status == "pricing_policy_required"
        and missing_policy.customer_price_preview is None
        and missing_policy.customer_price_preview_available is False,
        "missing quote customer and agency pricing policy blocks air customer-price creation",
    )

    invalid_policy = _preview(
        customer_repo=agency_repo,
        customer_id=agency_customer.customer_id,
        additional_ids=ids,
        environ={AGENCY_PRICING_POLICY_ENV: "{invalid-json"},
        setup=setup,
    )
    check(
        invalid_policy.pricing_status == "pricing_policy_invalid"
        and invalid_policy.customer_price_preview is None,
        "invalid agency pricing configuration fails closed for air pricing",
    )

    incomplete = _preview(
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        additional_ids=[pickup.evidence_id],
        environ={},
        setup=setup,
    )
    check(
        incomplete.pricing_status == "cost_incomplete"
        and incomplete.customer_price_preview is None
        and "required_cost_missing:delivery" in incomplete.blockers,
        "P2-39 cost completeness must be confirmed before any air customer price is calculated",
    )

    inactive_repo, inactive_customer = _customer_repo(
        formula=PricingFormula(method="fixed_profit", value=100), active=False, name="Inactive Customer"
    )
    inactive_blocked = False
    try:
        _preview(customer_repo=inactive_repo, customer_id=inactive_customer.customer_id, additional_ids=ids, environ={}, setup=setup)
    except AirCustomerPricingPreviewError as exc:
        inactive_blocked = str(exc) == "customer_master_profile_inactive"
    check(inactive_blocked, "inactive customer master profile cannot authorize air pricing")

    missing_customer = False
    try:
        _preview(customer_repo=customer_repo, customer_id="missing-customer", additional_ids=ids, environ={}, setup=setup)
    except AirCustomerPricingPreviewError as exc:
        missing_customer = str(exc) == "customer_master_profile_not_found"
    check(missing_customer, "air pricing requires an explicit existing customer master identity")

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
        api.air_cost_scope_review_repository,
        api.air_unsupported_cost_semantics_review_repository,
        api.air_additional_cost_evidence_repository,
        api.air_rate_weight_rounding_review_repository,
        api.master_data_repository,
    )
    try:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_cost_scope_review_repository,
            api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository,
            api.air_rate_weight_rounding_review_repository,
            api.master_data_repository,
        ) = (_table_repo(), _structure_repo(), _simple_surcharges(), setup[0], setup[1], setup[3], setup[5], _rounding_repo(), customer_repo)
        with patch.dict("os.environ", {}, clear=True):
            response = api.preview_air_customer_pricing(
                "table-review-0001",
                "table-row-fra-0001",
                api.AirCustomerPricingPreviewRequest(
                    cost_scope_review_id=setup[2].review_id,
                    unsupported_cost_semantics_review_id=setup[4].review_id,
                    inquiry_reference=INQUIRY,
                    customer_id=customer.customer_id,
                    actual_weight_kg=287,
                    volumetric_weight_kg=250,
                    cargo_context="general_cargo",
                    routing_context="direct",
                    shipment_count=1,
                    additional_cost_evidence_ids=ids,
                ),
            )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_cost_scope_review_repository,
            api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository,
            api.air_rate_weight_rounding_review_repository,
            api.master_data_repository,
        ) = originals
    check(
        response["pricing_status"] == "priced_preview"
        and response["customer_price_preview"]["final_price"] == 1043.5
        and response["quote_created"] is False
        and response["quote_send_authority"] is False,
        "controlled API exposes air customer price preview without creating a quote or send authority",
    )

    check(
        route_allowed("POST", "/air-rate-table-reviews/r1/rows/c1/customer-pricing-preview"),
        "pilot access admits only the bounded air customer-pricing preview route",
    )

    root = Path(__file__).resolve().parents[2]
    service = (root / "src" / "core" / "air_customer_pricing_preview.py").read_text(encoding="utf-8")
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "calculate_customer_quote" in service
        and "resolve_pricing_policy" in service
        and "accepted_markup" not in service
        and "learning_fact" not in service
        and "insert_once" not in service
        and ".create(" not in service,
        "air pricing reuses authoritative shared pricing policy and ignores advisory learning without persistence writes",
    )
    check(
        "Air Customer Pricing Preview" in ui
        and "Customer Price Preview Hesapla" in ui
        and "quote override > verified customer master policy > agency default" in ui
        and "QUOTE OLUŞMADI" in ui
        and "SEND AUTHORITY YOK" in ui,
        "browser exposes explicit customer pricing preview while keeping quote/send boundaries visible",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_customer_pricing_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir customer pricing preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
