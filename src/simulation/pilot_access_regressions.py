from __future__ import annotations

import json

from src.core.pilot_access import (
    authorize_pilot_request,
    route_allowed,
)


def evaluate_pilot_access_regressions() -> dict:
    failures: list[str] = []
    operator_one_token = "a" * 40
    operator_two_token = "b" * 40
    env = {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32,10.42.0.0/16",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps(
            {
                "Pilot Operator One": operator_one_token,
                "Pilot Operator Two": operator_two_token,
            }
        ),
    }

    health = authorize_pilot_request(
        method="GET",
        path="/health",
        client_host="127.0.0.1",
        authorization=None,
        environ=env,
    )
    if not health.allowed:
        failures.append("pilot health endpoint was not network-accessible")

    no_auth = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="127.0.0.1",
        authorization=None,
        environ=env,
    )
    if no_auth.allowed or no_auth.status_code != 401:
        failures.append("pilot workflow accepted unauthenticated request")

    authenticated = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="10.42.1.25",
        authorization=f"Bearer {operator_one_token}",
        environ=env,
    )
    if not authenticated.allowed:
        failures.append("named pilot operator was rejected")
    if authenticated.operator_name != "Pilot Operator One":
        failures.append("authenticated operator identity was not retained")

    wrong_token = authorize_pilot_request(
        method="GET",
        path="/quote-cases",
        client_host="127.0.0.1",
        authorization="Bearer wrong-token",
        environ=env,
    )
    if wrong_token.allowed or wrong_token.status_code != 401:
        failures.append("invalid pilot token was accepted")

    public_network = authorize_pilot_request(
        method="GET",
        path="/quote-cases",
        client_host="8.8.8.8",
        authorization=f"Bearer {operator_one_token}",
        environ=env,
    )
    if public_network.allowed or public_network.status_code != 403:
        failures.append("public-network pilot request was accepted")

    disabled_routes = (
        ("GET", "/run-test-suite"),
        ("POST", "/supplier-rfqs/abc/simulate-response"),
        ("POST", "/supplier-rfqs/abc/send"),
        ("POST", "/supplier-responses/ingest"),
        ("POST", "/customer-memory/import/apply"),
        ("POST", "/customer-memory/backups/restore"),
        ("POST", "/customer-memory"),
        ("PUT", "/customer-memory"),
        ("PATCH", "/customer-memory/status"),
        ("POST", "/quotes/prepare-send"),
    )
    for method, path in disabled_routes:
        decision = authorize_pilot_request(
            method=method,
            path=path,
            client_host="127.0.0.1",
            authorization=f"Bearer {operator_one_token}",
            environ=env,
        )
        if decision.allowed or decision.status_code != 404:
            failures.append(
                f"dangerous pilot route remained enabled: {method} {path}"
            )

    expected_routes = (
        ("POST", "/process-email"),
        ("POST", "/extraction-proposals/p1/confirm"),
        ("POST", "/extraction-proposals/p1/resume"),
        ("POST", "/supplier-rfqs/r1/approve"),
        ("POST", "/supplier-rfqs/r1/responses"),
        ("POST", "/supplier-rfq-workflows/w1/resume-quote"),
        ("POST", "/quote-approvals/a1/approve"),
        ("GET", "/quote-cases/c1"),
    )
    for method, path in expected_routes:
        if not route_allowed(method, path):
            failures.append(
                f"required shadow-pilot route is disabled: {method} {path}"
            )

    missing_config = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="127.0.0.1",
        authorization=f"Bearer {operator_one_token}",
        environ={"MINAI_PILOT_MODE": "1"},
    )
    if missing_config.allowed or missing_config.status_code != 503:
        failures.append("pilot mode did not fail closed on missing config")

    # Authenticated identity must be authoritative over claimed body identity.
    from src.api import _authenticated_operator

    class _State:
        pilot_operator = "Pilot Operator One"

    class _Request:
        state = _State()

    resolved_operator = _authenticated_operator(
        _Request(),
        "Pilot Operator Two",
    )
    if resolved_operator != "Pilot Operator One":
        failures.append(
            "authenticated operator identity did not override claimed identity"
        )

    duplicate_token_env = dict(env)
    duplicate_token_env["MINAI_PILOT_OPERATORS_JSON"] = json.dumps(
        {
            "Pilot Operator One": operator_one_token,
            "Pilot Operator Two": operator_one_token,
        }
    )
    duplicate_tokens = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="127.0.0.1",
        authorization=f"Bearer {operator_one_token}",
        environ=duplicate_token_env,
    )
    if duplicate_tokens.allowed or duplicate_tokens.status_code != 503:
        failures.append("duplicate operator tokens did not fail closed")

    return {
        "name": "Authenticated isolated pilot profile",
        "passed": len(failures) == 0,
        "failures": failures,
    }
