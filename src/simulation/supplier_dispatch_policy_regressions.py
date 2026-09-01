from __future__ import annotations

from unittest.mock import patch

from src.core.pilot_access import PilotAccessConfigurationError
from src.core.supplier_dispatch_policy import (
    AGENCY_SUPPLIER_DISPATCH_POLICY_ENV,
    SupplierDispatchPolicy,
    resolve_supplier_dispatch_policy,
)
from src import pilot_launcher


def evaluate_supplier_dispatch_policy_regressions() -> dict:
    failures: list[str] = []

    default_policy = resolve_supplier_dispatch_policy({})
    if default_policy != SupplierDispatchPolicy():
        failures.append("missing config did not preserve sequential-1 default")

    parallel = resolve_supplier_dispatch_policy({
        AGENCY_SUPPLIER_DISPATCH_POLICY_ENV:
            '{"mode":"parallel","initial_supplier_count":2}'
    })
    if parallel.mode != "parallel" or parallel.initial_supplier_count != 2:
        failures.append("parallel agency policy was not resolved")

    invalid_values = [
        '{"mode":"sequential","initial_supplier_count":2}',
        '{"mode":"parallel","initial_supplier_count":1}',
        '{"mode":"parallel","initial_supplier_count":4}',
        '{"mode":"hybrid","initial_supplier_count":2}',
        '{not-json}',
    ]
    for raw in invalid_values:
        try:
            resolve_supplier_dispatch_policy({
                AGENCY_SUPPLIER_DISPATCH_POLICY_ENV: raw
            })
        except ValueError:
            pass
        else:
            failures.append(f"invalid dispatch config was accepted: {raw}")

    launcher_env = {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_TOKEN": "synthetic-token-with-sufficient-length",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        AGENCY_SUPPLIER_DISPATCH_POLICY_ENV:
            '{"mode":"parallel","initial_supplier_count":1}',
    }
    with patch.object(pilot_launcher, "validate_pilot_configuration"), patch.object(
        pilot_launcher, "operational_data_sources_from_environment"
    ), patch.object(pilot_launcher.uvicorn, "run"):
        try:
            pilot_launcher.run(launcher_env)
        except PilotAccessConfigurationError:
            pass
        else:
            failures.append("pilot launcher did not fail closed on invalid dispatch config")

    return {"passed": not failures, "failures": failures}


if __name__ == "__main__":
    outcome = evaluate_supplier_dispatch_policy_regressions()
    print(outcome)
    raise SystemExit(0 if outcome["passed"] else 1)
