"""Canonical deterministic regression gate for the controlled shadow pilot."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, Iterable, TextIO

from src.simulation.atomic_transition_regressions import evaluate_atomic_transition_regressions
from src.simulation.clarification_resolution_regressions import evaluate_clarification_resolution_regressions
from src.simulation.customer_identity_trust_regressions import evaluate_customer_identity_trust_regressions
from src.simulation.data_provenance_regressions import evaluate_data_provenance_regressions
from src.simulation.data_path_regressions import evaluate_data_path_regressions
from src.simulation.extraction_confirmation_regressions import evaluate_extraction_confirmation_regressions
from src.simulation.mail_adapter_regressions import evaluate_mail_adapter_regressions
from src.simulation.operational_data_injection_regressions import evaluate_operational_data_injection_regressions
from src.simulation.manual_rfq_sent_regressions import evaluate_manual_rfq_sent_regressions
from src.simulation.pilot_access_regressions import evaluate_pilot_access_regressions
from src.simulation.pilot_launcher_regressions import evaluate_pilot_launcher_regressions
from src.simulation.pilot_rehearsal_regressions import evaluate_pilot_rehearsal_regressions
from src.simulation.pilot_operator_regressions import evaluate_pilot_operator_regressions
from src.simulation.pilot_readiness_regressions import evaluate_pilot_readiness_regressions
from src.simulation.pilot_persistence_regressions import evaluate_pilot_persistence_regressions
from src.simulation.pilot_scope_regressions import evaluate_pilot_scope_regressions
from src.simulation.privacy_boundary_regressions import evaluate_privacy_boundary_regressions
from src.simulation.provenance_recovery_regressions import evaluate_provenance_recovery_regressions
from src.simulation.regulatory_compliance_regressions import evaluate_regulatory_compliance_regressions
from src.simulation.runtime_preflight_regressions import evaluate_runtime_preflight_regressions
from src.simulation.reliability_hardening_regressions import (
    evaluate_reliability_hardening_regressions,
)
from src.simulation.road_rfq_commercial_safety_regressions import (
    evaluate_road_rfq_commercial_safety_regressions,
)
from src.simulation.safe_api_entrypoint_regressions import evaluate_safe_api_entrypoint_regressions
from src.simulation.source_compile_regressions import evaluate_source_compile_regressions
from src.simulation.sanitized_replay_regressions import evaluate_sanitized_replay_regressions
from src.simulation.supplier_response_ingestion_regressions import evaluate_supplier_response_ingestion_regressions
from src.simulation.supplier_rfq_lifecycle_regressions import evaluate_supplier_rfq_lifecycle_regressions
from src.simulation import test_reporter


@dataclass(frozen=True)
class Suite:
    name: str
    run: Callable[[], object]


def _reporter_suite(function_name: str, display_name: str) -> Suite:
    return Suite(display_name, getattr(test_reporter, function_name))


# Membership is deliberately explicit. Do not replace this with file discovery.
CANONICAL_SUITES: tuple[Suite, ...] = (
    Suite("Privacy boundary", evaluate_privacy_boundary_regressions),
    Suite("Pilot access", evaluate_pilot_access_regressions),
    Suite("Pilot launcher", evaluate_pilot_launcher_regressions),
    Suite("Synthetic pilot rehearsal", evaluate_pilot_rehearsal_regressions),
    Suite("Sanitized historical replay harness", evaluate_sanitized_replay_regressions),
    Suite("Pilot readiness assessment", evaluate_pilot_readiness_regressions),
    Suite("Safe API entry point", evaluate_safe_api_entrypoint_regressions),
    Suite("Python source compilation", evaluate_source_compile_regressions),
    Suite("Extraction confirmation", evaluate_extraction_confirmation_regressions),
    Suite("Customer identity trust", evaluate_customer_identity_trust_regressions),
    Suite("Data provenance", evaluate_data_provenance_regressions),
    Suite("Repository data path normalization", evaluate_data_path_regressions),
    Suite("Operational data injection", evaluate_operational_data_injection_regressions),
    Suite("Pilot scope", evaluate_pilot_scope_regressions),
    Suite("Durable pilot persistence", evaluate_pilot_persistence_regressions),
    Suite("Durable provenance recovery", evaluate_provenance_recovery_regressions),
    Suite("Atomic workflow transitions", evaluate_atomic_transition_regressions),
    Suite("Supplier RFQ lifecycle", evaluate_supplier_rfq_lifecycle_regressions),
    Suite(
        "Road RFQ commercial safety",
        evaluate_road_rfq_commercial_safety_regressions,
    ),
    Suite("Mail adapter boundary", evaluate_mail_adapter_regressions),
    Suite("Manual RFQ sent evidence", evaluate_manual_rfq_sent_regressions),
    Suite("Supplier response ingestion", evaluate_supplier_response_ingestion_regressions),
    Suite("Pilot operator client", evaluate_pilot_operator_regressions),
    Suite("Clarification resolution", evaluate_clarification_resolution_regressions),
    Suite("Regulatory compliance", evaluate_regulatory_compliance_regressions),
    Suite("Runtime reproducibility preflight", evaluate_runtime_preflight_regressions),
    Suite(
        "Runtime reliability hardening",
        evaluate_reliability_hardening_regressions,
    ),
    _reporter_suite("evaluate_commodity_dictionary_validation", "Commodity dictionary validation"),
    _reporter_suite("evaluate_supplier_capability_validation", "Supplier capability validation"),
    _reporter_suite("evaluate_supplier_adr_capability_validation", "Supplier ADR capability validation"),
    _reporter_suite("evaluate_supplier_capability_registry_validation", "Supplier capability registry validation"),
    _reporter_suite("evaluate_supplier_capability_registry_runtime_integrity", "Supplier capability registry runtime integrity"),
    _reporter_suite("evaluate_customer_memory_validation", "Customer memory validation"),
    _reporter_suite("evaluate_strict_supplier_eligibility", "Strict supplier eligibility"),
    _reporter_suite("evaluate_inactive_customer_memory_matching", "Inactive customer memory matching"),
    _reporter_suite("evaluate_heavy_cargo_weight_logic", "Heavy cargo weight logic"),
    _reporter_suite("evaluate_customer_pricing_regression", "Customer pricing"),
    _reporter_suite("evaluate_hs_commodity_map_validation", "HS commodity map validation"),
    _reporter_suite("evaluate_data_health_summary", "Data health summary"),
    _reporter_suite("evaluate_data_health_label_mapping", "Data health label mapping"),
    _reporter_suite("evaluate_data_health_registry_integrity", "Data health registry integrity"),
    _reporter_suite("evaluate_data_health_summary_check_metadata", "Data health check metadata"),
    _reporter_suite("evaluate_workflow_result_contract", "Workflow result contract"),
    _reporter_suite("evaluate_quote_readiness_blocked_state", "Quote readiness blocked state"),
    _reporter_suite("evaluate_action_recommendation_result_contract", "Action recommendation contract"),
    _reporter_suite("evaluate_supplier_rfq_draft_generation", "Supplier RFQ draft generation"),
    _reporter_suite("evaluate_supplier_rfq_workflow_contract", "Supplier RFQ workflow contract"),
    _reporter_suite("evaluate_supplier_rfq_contact_propagation", "Supplier RFQ contact propagation"),
    _reporter_suite("evaluate_supplier_rfq_response_simulation", "Supplier RFQ response simulation"),
    _reporter_suite("evaluate_supplier_quote_selection", "Supplier quote selection"),
    _reporter_suite("evaluate_supplier_rfq_response_validation", "Supplier RFQ response validation"),
    _reporter_suite("evaluate_supplier_fallback_consistency", "Supplier fallback consistency"),
    _reporter_suite("evaluate_supplier_rfq_lifecycle_synchronization", "Supplier RFQ lifecycle synchronization"),
    _reporter_suite("evaluate_supplier_rfq_response_link_integrity", "Supplier response link integrity"),
    _reporter_suite("evaluate_supplier_rfq_response_validation_report", "Supplier response validation report"),
    _reporter_suite("evaluate_supplier_rfq_response_status_rules", "Supplier response status rules"),
    _reporter_suite("evaluate_supplier_rfq_api_contract", "Supplier RFQ API contract"),
    _reporter_suite("evaluate_supplier_quote_comparison_model", "Supplier quote comparison model"),
    _reporter_suite("evaluate_multi_criteria_supplier_quote_selection", "Multi-criteria quote selection"),
    _reporter_suite("evaluate_supplier_quote_selection_traceability", "Supplier quote selection traceability"),
    _reporter_suite("evaluate_supplier_rfq_repository", "Supplier RFQ repository"),
    _reporter_suite("evaluate_supplier_rfq_repository_workflow_integration", "Supplier RFQ repository/workflow integration"),
    _reporter_suite("evaluate_quote_approval_model", "Quote approval model"),
    _reporter_suite("evaluate_quote_approval_workflow_contract", "Quote approval workflow contract"),
    _reporter_suite("evaluate_quote_approval_repository", "Quote approval repository"),
    _reporter_suite("evaluate_quote_approval_repository_workflow_integration", "Quote approval repository/workflow integration"),
    _reporter_suite("evaluate_quote_approval_service", "Quote approval service"),
    _reporter_suite("evaluate_quote_approval_api_contract", "Quote approval API contract"),
    _reporter_suite("evaluate_quote_case_model", "Quote case model"),
    _reporter_suite("evaluate_quote_case_repository", "Quote case repository"),
)


def _failure_summary(result: object) -> str | None:
    if isinstance(result, dict):
        if result.get("passed") is True:
            return None
        failures = result.get("failures")
        if isinstance(failures, (list, tuple)) and failures:
            return f"reported {len(failures)} failure(s)"
        return "reported passed=false"
    if result is True or result is None:
        return None
    return f"unsupported result type: {type(result).__name__}"


def run_suites(suites: Iterable[Suite], stream: TextIO = sys.stdout) -> int:
    passed = 0
    failed_names: list[str] = []

    for suite in suites:
        try:
            failure = _failure_summary(suite.run())
        except Exception as exc:  # Keep the gate running, without leaking values.
            failure = f"raised {type(exc).__name__}"

        if failure is None:
            passed += 1
            print(f"PASS  {suite.name}", file=stream)
        else:
            failed_names.append(suite.name)
            print(f"FAIL  {suite.name}: {failure}", file=stream)

    print(f"\nSummary: {passed} passed, {len(failed_names)} failed", file=stream)
    if failed_names:
        print("Failed suites: " + ", ".join(failed_names), file=stream)
    return 0 if not failed_names else 1


def main() -> int:
    return run_suites(CANONICAL_SUITES)


if __name__ == "__main__":
    raise SystemExit(main())
