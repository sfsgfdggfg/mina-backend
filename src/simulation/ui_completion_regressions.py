from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.core.automation_policy_repository import InMemoryAgencyAutomationPolicyRepository
from src.core.web_session import hash_password
from src.simulation.pilot_web_shell_regressions import _environment, _hidden_value, _meta_value, _web_env


def evaluate_ui_completion_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    root = Path(__file__).resolve().parents[2]
    js_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    css_text = (root / "ui" / "web_shell" / "app.css").read_text(encoding="utf-8")
    plan_text = (root / "docs" / "ui-completion-plan.md").read_text(encoding="utf-8")

    check(
        "/automation-policy/agency" in js_text
        and "renderAutomationSettings" in js_text
        and "Sistem varsayılanı" in js_text,
        "settings exposes agency automation policy without creating a second authority",
    )
    check(
        "/automation-overrides" in js_text
        and "Üst kuralı kullan" in js_text
        and "Bu işte devre dışı" in js_text,
        "job detail exposes bounded per-job automation override semantics",
    )
    check(
        "/reminder-preview" in js_text
        and "/reminder-now" in js_text
        and "/reminder-approval-preview" in js_text
        and "supplier_reminder_policy" in js_text,
        "supplier follow-up UI uses preview/send or approval paths according to backend policy",
    )
    check(
        "/quote-approvals/" in js_text
        and "/final-output" in js_text
        and "/send" in js_text
        and "/revise" in js_text
        and "window.prompt" not in js_text,
        "quote decision and send workspace stays controlled and uses inline rejection/revision UI",
    )
    check(
        "/stage" not in js_text and "/owners" not in js_text
        and "Operasyonu Başlat" in plan_text,
        "UI completion does not invent stage-start or directed-owner authority while semantics are parked",
    )
    check(
        "markActiveNavigation" in js_text
        and "nav a.active" in css_text
        and ".jobs-card-list" in css_text
        and "@media (max-width: 720px)" in css_text,
        "shell navigation and MINA list have explicit active and narrow-screen presentation",
    )
    check(
        js_text.count(".innerHTML =") == 1
        and "insertAdjacentHTML" not in js_text
        and "localStorage" not in js_text
        and "sessionStorage" not in js_text,
        "UI completion preserves controlled text rendering and avoids browser token/state storage",
    )

    password = "UI-Completion-Test-2026!"
    password_hash = hash_password(password, salt=b"ui-completion-16")
    import src.api as api_module

    previous_repository = api_module.agency_automation_policy_repository
    test_repository = InMemoryAgencyAutomationPolicyRepository()
    api_module.agency_automation_policy_repository = test_repository
    try:
        with _environment(_web_env(password_hash)):
            with TestClient(
                api_module.app,
                base_url="https://127.0.0.1",
                client=("127.0.0.1", 50100),
            ) as client:
                login_page = client.get("/app/login")
                nonce = _hidden_value(login_page.text, "login_nonce")
                logged_in = client.post(
                    "/app/login",
                    data={"email": "ops@example.com", "password": password, "login_nonce": nonce},
                    follow_redirects=False,
                )
                settings_page = client.get("/app/settings")
                csrf = _meta_value(settings_page.text, "csrf-token")
                no_csrf = client.post(
                    "/automation-policy/agency",
                    json={"supplier_reminder_mode": "approval_required", "customer_deadline_update_mode": "automatic"},
                )
                saved = client.post(
                    "/automation-policy/agency",
                    headers={"X-CSRF-Token": csrf},
                    json={"supplier_reminder_mode": "approval_required", "customer_deadline_update_mode": "automatic"},
                )
                stored = test_repository.get()
                job_no_csrf = client.post(
                    "/mina-jobs/missing-job/automation-overrides",
                    json={"disable_supplier_reminders": True},
                )
                job_with_csrf = client.post(
                    "/mina-jobs/missing-job/automation-overrides",
                    headers={"X-CSRF-Token": csrf},
                    json={"disable_supplier_reminders": True},
                )
                quote_read = client.get("/quote-cases/missing-case")
                quote_no_csrf = client.post("/quote-approvals/missing-approval/approve", json={})
                quote_with_csrf = client.post(
                    "/quote-approvals/missing-approval/approve",
                    headers={"X-CSRF-Token": csrf}, json={},
                )
                check(
                    logged_in.status_code == 303
                    and settings_page.status_code == 200
                    and no_csrf.status_code == 403
                    and saved.status_code == 200
                    and stored is not None
                    and stored.supplier_reminder_mode == "approval_required"
                    and stored.customer_deadline_update_mode == "automatic"
                    and stored.updated_by == "Web Operator",
                    "authenticated Settings automation mutation is CSRF-guarded and records operator authority",
                )
                check(
                    job_no_csrf.status_code == 403
                    and job_with_csrf.status_code == 404
                    and quote_read.status_code == 404
                    and quote_no_csrf.status_code == 403
                    and quote_with_csrf.status_code == 404,
                    "job automation and quote decision APIs remain browser-session allowlisted and CSRF guarded",
                )
    finally:
        api_module.agency_automation_policy_repository = previous_repository

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_ui_completion_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nUI completion regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
