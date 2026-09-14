from __future__ import annotations

import os
from unittest.mock import patch

from src.core.pricing_policy import AGENCY_PRICING_POLICY_ENV
from src.simulation.atomic_transition_regressions import (
    evaluate_atomic_transition_regressions,
)
from src.simulation.human_operational_flow_regressions import (
    evaluate_human_operational_flow_regressions,
)
from src.simulation.provenance_recovery_regressions import (
    evaluate_provenance_recovery_regressions,
)
from src.simulation.test_reporter import (
    evaluate_quote_approval_repository_workflow_integration,
    evaluate_quote_approval_workflow_contract,
)


def evaluate_canonical_commercial_fixture_isolation_regressions() -> dict:
    failures: list[str] = []
    suites = (
        ("durable provenance recovery", evaluate_provenance_recovery_regressions),
        ("atomic workflow transitions", evaluate_atomic_transition_regressions),
        ("human operational flow", evaluate_human_operational_flow_regressions),
        ("quote approval workflow contract", evaluate_quote_approval_workflow_contract),
        (
            "quote approval repository/workflow integration",
            evaluate_quote_approval_repository_workflow_integration,
        ),
    )

    # A broken ambient agency policy must not be the hidden authority that makes
    # any of these offline commercial regressions pass or fail.
    with patch.dict(
        os.environ,
        {AGENCY_PRICING_POLICY_ENV: "{invalid-ambient-pricing-json"},
        clear=False,
    ):
        for label, evaluator in suites:
            result = evaluator()
            if result.get("passed") is not True:
                failures.append(
                    f"{label} depends on ambient agency pricing configuration"
                )

    return {
        "name": "Canonical commercial fixture isolation",
        "passed": not failures,
        "failures": failures,
    }
