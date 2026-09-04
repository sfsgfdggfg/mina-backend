from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.core.web_session import (
    InMemoryLoginThrottle,
    InMemoryWebSessionStore,
    WebSessionConfigurationError,
    WebUser,
    hash_password,
    password_hash_supported,
    validate_web_session_configuration,
    verify_password,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


@contextmanager
def _environment(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _web_env(password_hash: str) -> dict[str, str]:
    return {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps({"CLI Operator": "c" * 40}),
        "MINAI_WEB_SHELL_ENABLED": "1",
        "MINAI_WEB_SESSION_SECRET": "session-secret-" + "s" * 40,
        "MINAI_WEB_SESSION_TTL_MINUTES": "480",
        "MINAI_WEB_SESSION_IDLE_MINUTES": "60",
        "MINAI_WEB_USERS_JSON": json.dumps({
            "ops@example.com": {
                "name": "Web Operator", "password_hash": password_hash, "active": True,
            }
        }),
    }


def _hidden_value(html_text: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]+)"', html_text)
    if not match:
        raise AssertionError(f"Missing hidden value: {name}")
    return match.group(1)


def _meta_value(html_text: str, name: str) -> str:
    match = re.search(rf'<meta name="{re.escape(name)}" content="([^"]+)"', html_text)
    if not match:
        raise AssertionError(f"Missing meta value: {name}")
    return match.group(1)


def evaluate_pilot_web_shell_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    root = Path(__file__).resolve().parents[2]
    js_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    prohibited_browser_patterns = (
        "localStorage", "sessionStorage", "insertAdjacentHTML", "eval(", "new Function",
    )
    check(
        not any(pattern in js_text for pattern in prohibited_browser_patterns)
        and js_text.count(".innerHTML =") == 1
        and 'X-CSRF-Token' in js_text
        and "/reminder-approval" in js_text
        and "/customer-deadline-update/approval" in js_text,
        "browser assets avoid token storage and dynamic HTML while wiring controlled approval APIs",
    )

    password = "Pilot-Web-Password-2026!"
    password_hash = hash_password(password, salt=b"pilot-web-salt!!")
    check(
        password not in password_hash
        and password_hash_supported(password_hash)
        and verify_password(password, password_hash)
        and not verify_password("wrong-password", password_hash)
        and not password_hash_supported(password_hash.replace("$16384$", "$1048576$")),
        "web passwords use bounded one-way scrypt verification and never plaintext storage",
    )
    throttle = InMemoryLoginThrottle(max_failures=3, window_minutes=10)
    throttle.record_failure("127.0.0.1", now=NOW)
    throttle.record_failure("127.0.0.1", now=NOW + timedelta(seconds=1))
    still_allowed = throttle.allowed("127.0.0.1", now=NOW + timedelta(seconds=2))
    throttle.record_failure("127.0.0.1", now=NOW + timedelta(seconds=3))
    blocked = not throttle.allowed("127.0.0.1", now=NOW + timedelta(seconds=4))
    recovered = throttle.allowed("127.0.0.1", now=NOW + timedelta(minutes=11))
    check(
        still_allowed and blocked and recovered,
        "login failure throttle blocks repeated attempts and recovers after its bounded window",
    )

    bad_env = _web_env(password_hash)
    bad_env["MINAI_WEB_USERS_JSON"] = json.dumps({
        "ops@example.com": {"name": "Ops", "password_hash": "plaintext-password"}
    })
    config_rejected = False
    with _environment(bad_env):
        try:
            validate_web_session_configuration()
        except WebSessionConfigurationError:
            config_rejected = True
    check(config_rejected, "web-shell configuration rejects plaintext password material")

    store = InMemoryWebSessionStore()
    user = WebUser("ops@example.com", "Web Operator", password_hash)
    direct_env = _web_env(password_hash)
    session, cookie = store.create(user, now=NOW, environ=direct_env)
    resolved = store.resolve(cookie, now=NOW + timedelta(minutes=30), environ=direct_env)
    expired = store.resolve(cookie, now=NOW + timedelta(minutes=91), environ=direct_env)
    check(
        resolved is not None and expired is None and password not in cookie,
        "server-side sessions carry opaque signed cookies and enforce idle expiry",
    )

    import src.api as api_module

    disabled_env = {
        "MINAI_PILOT_MODE": "1",
        "MINAI_PILOT_BIND_HOST": "127.0.0.1",
        "MINAI_PILOT_ALLOWED_NETWORKS": "127.0.0.1/32",
        "MINAI_PILOT_OPERATORS_JSON": json.dumps({"CLI Operator": "c" * 40}),
        "MINAI_WEB_SHELL_ENABLED": "0",
    }
    with _environment(disabled_env):
        with TestClient(
            api_module.app, base_url="https://127.0.0.1", client=("127.0.0.1", 50000),
        ) as client:
            disabled = client.get("/app/login")
    check(disabled.status_code == 404, "pilot web shell is fail-closed unless explicitly enabled")

    with _environment(_web_env(password_hash)):
        with TestClient(
            api_module.app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
        ) as insecure_client:
            insecure = insecure_client.get("/app/login")
        check(
            insecure.status_code == 426
            and insecure.json().get("detail") == "pilot_web_https_required",
            "pilot web shell requires HTTPS even on loopback",
        )

    with _environment(_web_env(password_hash)):
        with TestClient(
            api_module.app, base_url="https://127.0.0.1", client=("127.0.0.1", 50000),
        ) as client:
            login_page = client.get("/app/login")
            nonce = _hidden_value(login_page.text, "login_nonce")
            check(
                login_page.status_code == 200
                and "Content-Security-Policy" in login_page.headers
                and login_page.cookies.get("minai_login_nonce") == nonce,
                "login page uses transport guard security headers and anti-login-CSRF nonce",
            )
            wrong = client.post(
                "/app/login",
                data={"email": "ops@example.com", "password": "wrong-password", "login_nonce": nonce},
                follow_redirects=False,
            )
            next_nonce = _hidden_value(wrong.text, "login_nonce")
            check(
                wrong.status_code == 401
                and "E-posta veya şifre hatalı." in wrong.text
                and "minai_session" not in wrong.cookies,
                "login failures are generic and do not create authenticated sessions",
            )

            logged_in = client.post(
                "/app/login",
                data={"email": "ops@example.com", "password": password, "login_nonce": next_nonce},
                follow_redirects=False,
            )
            set_cookie = logged_in.headers.get("set-cookie", "")
            check(
                logged_in.status_code == 303
                and logged_in.headers.get("location") == "/app/dashboard"
                and "minai_session=" in set_cookie
                and "HttpOnly" in set_cookie
                and "Secure" in set_cookie
                and "SameSite=strict" in set_cookie,
                "successful login issues a secure HttpOnly SameSite server-session cookie",
            )

            jobs_page = client.get("/app/jobs")
            csrf = _meta_value(jobs_page.text, "csrf-token")
            api_jobs = client.get("/mina-jobs")
            check(
                jobs_page.status_code == 200
                and "Web Operator" in jobs_page.text
                and password not in jobs_page.text
                and api_jobs.status_code == 200,
                "authenticated browser session can render the shell and read controlled APIs",
            )

            no_csrf = client.post("/mina-jobs/manual", json={})
            with_csrf = client.post(
                "/mina-jobs/manual", json={}, headers={"X-CSRF-Token": csrf}
            )
            check(
                no_csrf.status_code == 403
                and no_csrf.json().get("detail") == "csrf_validation_failed"
                and with_csrf.status_code == 422,
                "browser-session mutations require CSRF before request-model processing",
            )

            invalid_bearer = client.get(
                "/mina-jobs", headers={"Authorization": "Bearer invalid-browser-bypass"}
            )
            valid_bearer_post = client.post(
                "/mina-jobs/manual", json={}, headers={"Authorization": "Bearer " + "c" * 40}
            )
            check(
                invalid_bearer.status_code == 401 and valid_bearer_post.status_code == 422,
                "explicit bearer authorization takes precedence and remains CSRF-independent",
            )

            bad_logout = client.post(
                "/app/logout", data={"csrf_token": "wrong-token"}, follow_redirects=False
            )
            good_logout = client.post(
                "/app/logout", data={"csrf_token": csrf}, follow_redirects=False
            )
            after_logout = client.get("/app/jobs", follow_redirects=False)
            check(
                bad_logout.status_code == 403
                and good_logout.status_code == 303
                and after_logout.status_code == 303
                and after_logout.headers.get("location") == "/app/login",
                "logout requires CSRF invalidates server session and removes shell access",
            )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_pilot_web_shell_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nP2-09 pilot web shell regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
