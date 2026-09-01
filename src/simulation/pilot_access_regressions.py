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

    runtime_no_auth = authorize_pilot_request(
        method="GET",
        path="/runtime/release",
        client_host="127.0.0.1",
        authorization=None,
        environ=env,
    )
    if (
        runtime_no_auth.allowed
        or runtime_no_auth.status_code != 401
    ):
        failures.append(
            "runtime release identity was exposed "
            "without operator authentication"
        )

    private_env = {
        **env,
        "MINAI_PILOT_BIND_HOST": "10.42.1.9",
        "MINAI_PILOT_TLS_CERTFILE": (
            "/external/pilot-cert.pem"
        ),
        "MINAI_PILOT_TLS_KEYFILE": (
            "/external/pilot-key.pem"
        ),
    }

    insecure_private = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="10.42.1.25",
        authorization=f"Bearer {operator_one_token}",
        request_scheme="http",
        environ=private_env,
    )
    if (
        insecure_private.allowed
        or insecure_private.status_code != 426
    ):
        failures.append(
            "private-network bearer request "
            "was accepted without HTTPS"
        )

    authenticated = authorize_pilot_request(
        method="POST",
        path="/process-email",
        client_host="10.42.1.25",
        authorization=f"Bearer {operator_one_token}",
        request_scheme="https",
        environ=private_env,
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
        ("GET", "/runtime/release"),
        ("POST", "/process-email"),
        ("GET", "/attachment-review-queue"),
        ("GET", "/operational-work-queue"),
        ("GET", "/attachment-reviews"),
        ("GET", "/attachment-reviews/ar1"),
        ("POST", "/attachment-reviews/ar1/preview"),
        ("POST", "/attachment-reviews/ar1/apply"),
        ("POST", "/attachment-reviews/ar1/reject"),
        ("POST", "/extraction-proposals/p1/confirm"),
        ("POST", "/extraction-proposals/p1/resume"),
        ("POST", "/supplier-rfqs/r1/approve"),
        ("POST", "/supplier-rfqs/r1/record-manually-sent"),
        ("POST", "/supplier-rfqs/r1/responses"),
        ("GET", "/supplier-rfqs/r1/follow-ups"),
        ("GET", "/supplier-rfq-follow-ups/f1"),
        ("POST", "/supplier-rfq-follow-ups/f1/approve"),
        ("POST", "/supplier-rfq-follow-ups/f1/send"),
        ("POST", "/supplier-rfq-follow-ups/f1/record-manually-sent"),
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

    for wildcard_host in ("0.0.0.0", "::"):
        wildcard_bind_env = dict(env)
        wildcard_bind_env["MINAI_PILOT_BIND_HOST"] = wildcard_host

        wildcard_bind = authorize_pilot_request(
            method="POST",
            path="/process-email",
            client_host="127.0.0.1",
            authorization=f"Bearer {operator_one_token}",
            environ=wildcard_bind_env,
        )

        if wildcard_bind.allowed or wildcard_bind.status_code != 503:
            failures.append(
                f"wildcard pilot bind host was accepted: {wildcard_host}"
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
