from __future__ import annotations

import hmac
import ipaddress
import json
import os
import re
from dataclasses import dataclass
from typing import Mapping


class PilotAccessConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PilotOperator:
    name: str
    token: str


@dataclass(frozen=True)
class PilotAccessDecision:
    allowed: bool
    status_code: int
    reason: str
    operator_name: str | None = None


_ALLOWED_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("GET", re.compile(r"^/health$")),
    ("GET", re.compile(r"^/runtime/release$")),
    ("POST", re.compile(r"^/process-email$")),
    ("POST", re.compile(r"^/inbound/outlook/pull$")),
    ("GET", re.compile(r"^/attachment-review-queue$")),
    ("GET", re.compile(r"^/operational-work-queue$")),
    ("GET", re.compile(r"^/operational-work-my$")),
    ("GET", re.compile(r"^/operational-work-shift-summary$")),
    ("GET", re.compile(r"^/operational-work-items/[^/]+$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/assign-to-me$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/acknowledge$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/renew$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/takeover$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/handoff$")),
    ("POST", re.compile(r"^/operational-work-items/[^/]+/release$")),
    ("GET", re.compile(r"^/attachment-reviews$")),
    ("GET", re.compile(r"^/attachment-reviews/[^/]+$")),
    ("POST", re.compile(r"^/attachment-reviews/[^/]+/preview$")),
    ("POST", re.compile(r"^/attachment-reviews/[^/]+/apply$")),
    ("POST", re.compile(r"^/attachment-reviews/[^/]+/reject$")),
    ("GET", re.compile(r"^/extraction-proposals/[^/]+$")),
    ("POST", re.compile(r"^/extraction-proposals/[^/]+/confirm$")),
    ("POST", re.compile(r"^/extraction-proposals/[^/]+/resume$")),
    ("GET", re.compile(r"^/supplier-rfqs$")),
    ("GET", re.compile(r"^/supplier-rfqs/[^/]+$")),
    ("POST", re.compile(r"^/supplier-rfqs/[^/]+/approve$")),
    ("POST", re.compile(r"^/supplier-rfqs/[^/]+/send$")),
    ("POST", re.compile(r"^/supplier-rfqs/[^/]+/record-manually-sent$")),
    ("POST", re.compile(r"^/supplier-rfqs/[^/]+/responses$")),
    ("GET", re.compile(r"^/supplier-rfqs/[^/]+/follow-ups$")),
    ("GET", re.compile(r"^/supplier-rfq-follow-ups/[^/]+$")),
    ("POST", re.compile(r"^/supplier-rfq-follow-ups/[^/]+/approve$")),
    ("POST", re.compile(r"^/supplier-rfq-follow-ups/[^/]+/send$")),
    ("POST", re.compile(r"^/supplier-rfq-follow-ups/[^/]+/record-manually-sent$")),
    ("POST", re.compile(r"^/supplier-rfq-workflows/[^/]+/resume-quote$")),
    ("GET", re.compile(r"^/quote-approvals$")),
    ("GET", re.compile(r"^/quote-approvals/[^/]+$")),
    ("POST", re.compile(r"^/quote-approvals/[^/]+/approve$")),
    ("POST", re.compile(r"^/quote-approvals/[^/]+/reject$")),
    ("POST", re.compile(r"^/quote-approvals/[^/]+/invalidate$")),
    ("GET", re.compile(r"^/quote-cases$")),
    ("GET", re.compile(r"^/quote-cases/[^/]+$")),
    ("GET", re.compile(r"^/quote-cases/[^/]+/final-output$")),
    ("POST", re.compile(r"^/quote-cases/[^/]+/record-manually-sent$")),
    ("POST", re.compile(r"^/quote-cases/[^/]+/send$")),
    ("POST", re.compile(r"^/quote-cases/[^/]+/revise$")),
)

_AUTH_EXEMPT_ROUTES = {("GET", "/health")}


def _env_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def pilot_mode_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    return _env_truthy(env.get("MINAI_PILOT_MODE"))


def _load_operators(env: Mapping[str, str]) -> list[PilotOperator]:
    raw = (env.get("MINAI_PILOT_OPERATORS_JSON") or "").strip()
    if not raw:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_OPERATORS_JSON is required in pilot mode."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_OPERATORS_JSON must be valid JSON."
        ) from exc
    if not isinstance(parsed, dict) or not parsed:
        raise PilotAccessConfigurationError(
            "Pilot operators must be a non-empty JSON object."
        )

    operators: list[PilotOperator] = []
    seen_tokens: set[str] = set()
    for raw_name, raw_token in parsed.items():
        name = str(raw_name).strip()
        token = str(raw_token).strip()
        if len(name) < 3:
            raise PilotAccessConfigurationError(
                "Pilot operator names must be explicit named identities."
            )
        if len(token) < 32:
            raise PilotAccessConfigurationError(
                "Pilot operator tokens must contain at least 32 characters."
            )
        if token in seen_tokens:
            raise PilotAccessConfigurationError(
                "Pilot operator tokens must be unique."
            )
        seen_tokens.add(token)
        operators.append(PilotOperator(name=name, token=token))
    return operators


def _load_allowed_networks(
    env: Mapping[str, str],
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = env.get("MINAI_PILOT_ALLOWED_NETWORKS") or "127.0.0.1/32,::1/128"
    networks = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise PilotAccessConfigurationError(
                f"Invalid pilot network: {value}"
            ) from exc
        if (
            network.prefixlen == 0
            or not (
                network.network_address.is_private
                or network.network_address.is_loopback
            )
        ):
            raise PilotAccessConfigurationError(
                "Pilot networks must be private or loopback CIDRs."
            )
        networks.append(network)
    if not networks:
        raise PilotAccessConfigurationError(
            "At least one pilot network is required."
        )
    return networks


def validate_pilot_configuration(
    environ: Mapping[str, str] | None = None,
) -> None:
    env = environ if environ is not None else os.environ
    if not pilot_mode_enabled(env):
        return

    _load_operators(env)
    _load_allowed_networks(env)

    bind_host = (env.get("MINAI_PILOT_BIND_HOST") or "").strip()
    if not bind_host:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_BIND_HOST is required in pilot mode."
        )
    try:
        bind_ip = ipaddress.ip_address(bind_host)
    except ValueError as exc:
        raise PilotAccessConfigurationError(
            "MINAI_PILOT_BIND_HOST must be an explicit IP address."
        ) from exc
    if (
        bind_ip.is_unspecified
        or bind_ip.is_multicast
        or not (bind_ip.is_private or bind_ip.is_loopback)
    ):
        raise PilotAccessConfigurationError(
            "Pilot bind host must be a specific private or loopback address."
        )

    if not bind_ip.is_loopback:
        tls_cert = (
            env.get("MINAI_PILOT_TLS_CERTFILE")
            or ""
        ).strip()
        tls_key = (
            env.get("MINAI_PILOT_TLS_KEYFILE")
            or ""
        ).strip()

        if not tls_cert or not tls_key:
            raise PilotAccessConfigurationError(
                "Private-network pilot binding requires "
                "TLS certificate and key configuration."
            )


def route_allowed(method: str, path: str) -> bool:
    normalized_method = method.upper()
    return any(
        normalized_method == allowed_method
        and pattern.fullmatch(path) is not None
        for allowed_method, pattern in _ALLOWED_ROUTES
    )


def _client_network_allowed(client_host: str | None, networks) -> bool:
    if not client_host:
        return False
    try:
        address = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    return any(
        address.version == network.version and address in network
        for network in networks
    )


def _operator_from_authorization(
    authorization: str | None,
    operators: list[PilotOperator],
) -> PilotOperator | None:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token:
        return None
    for operator in operators:
        if hmac.compare_digest(token.strip(), operator.token):
            return operator
    return None


def authorize_pilot_request(
    *,
    method: str,
    path: str,
    client_host: str | None,
    authorization: str | None,
    request_scheme: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> PilotAccessDecision:
    env = environ if environ is not None else os.environ

    if not pilot_mode_enabled(env):
        return PilotAccessDecision(True, 200, "pilot_mode_disabled")

    try:
        validate_pilot_configuration(env)
        networks = _load_allowed_networks(env)
        operators = _load_operators(env)
    except PilotAccessConfigurationError as exc:
        return PilotAccessDecision(False, 503, str(exc))

    if not _client_network_allowed(client_host, networks):
        return PilotAccessDecision(False, 403, "pilot_network_denied")

    client_address = ipaddress.ip_address(
        client_host
    )

    if (
        not client_address.is_loopback
        and (request_scheme or "").lower()
        != "https"
    ):
        return PilotAccessDecision(
            False,
            426,
            "pilot_https_required",
        )

    if not route_allowed(method, path):
        return PilotAccessDecision(False, 404, "pilot_route_disabled")

    if (method.upper(), path) in _AUTH_EXEMPT_ROUTES:
        return PilotAccessDecision(True, 200, "pilot_health_allowed")

    operator = _operator_from_authorization(authorization, operators)
    if operator is None:
        return PilotAccessDecision(
            False, 401, "pilot_authentication_required"
        )

    return PilotAccessDecision(
        True,
        200,
        "pilot_operator_authenticated",
        operator.name,
    )
