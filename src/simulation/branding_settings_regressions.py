from __future__ import annotations

import base64
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.core.agency_branding import (
    AgencyBrandingSettings,
    AgencyBrandingUpdate,
    branding_public_payload,
)
from src.core.agency_branding_repository import (
    InMemoryAgencyBrandingRepository,
    SQLiteAgencyBrandingRepository,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.web_session import hash_password
from src.simulation.pilot_web_shell_regressions import (
    _environment,
    _hidden_value,
    _meta_value,
    _web_env,
)

UTC = timezone.utc
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z0N8AAAAASUVORK5CYII="
)
PNG_URI = "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii")


def evaluate_branding_settings_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    update = AgencyBrandingUpdate(
        company_name="  Acme   Logistics  ", logo_data_uri=PNG_URI,
        primary_color="#ffffff", secondary_accent_color="#101828",
    )
    settings = AgencyBrandingSettings(
        **update.model_dump(), updated_at=datetime(2026, 9, 4, 18, 0, tzinfo=UTC),
        updated_by="Brand Admin",
    )
    payload = branding_public_payload(settings)
    check(
        settings.company_name == "Acme Logistics"
        and payload["primary_contrast_color"] == "#172033"
        and payload["secondary_contrast_color"] == "#FFFFFF"
        and payload["critical_status_colors_locked"] is True,
        "branding normalizes identity and derives contrast without overriding critical status colors",
    )

    invalid_logo_rejected = invalid_color_rejected = False
    try:
        AgencyBrandingUpdate(
            company_name="Acme", logo_data_uri="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
            primary_color="#3157D5", secondary_accent_color="#172033",
        )
    except ValidationError:
        invalid_logo_rejected = True
    try:
        AgencyBrandingUpdate(
            company_name="Acme", primary_color="blue", secondary_accent_color="#172033",
        )
    except ValidationError:
        invalid_color_rejected = True
    check(
        invalid_logo_rejected and invalid_color_rejected,
        "branding rejects SVG/unapproved logo types and non-hex colors",
    )

    mismatch_rejected = False
    try:
        AgencyBrandingUpdate(
            company_name="Acme",
            logo_data_uri="data:image/png;base64,/9j/2Q==",
            primary_color="#3157D5", secondary_accent_color="#172033",
        )
    except ValidationError:
        mismatch_rejected = True
    check(mismatch_rejected, "branding verifies logo magic bytes against declared MIME type")

    with tempfile.TemporaryDirectory() as tmp:
        store = SQLitePilotStore(Path(tmp) / "branding.sqlite3")
        repository = SQLiteAgencyBrandingRepository(store)
        stored = repository.save(settings)
        reloaded = SQLiteAgencyBrandingRepository(store).get()
        events = store.list_events(entity_type="agency_branding_settings")
    check(
        stored.company_name == "Acme Logistics"
        and reloaded is not None and reloaded.primary_color == "#FFFFFF"
        and len(events) == 1 and events[0]["event_type"] == "agency_branding_settings_saved",
        "branding persists as one current agency record with append-only audit evidence",
    )

    check(
        route_allowed("GET", "/settings/branding")
        and route_allowed("POST", "/settings/branding")
        and not route_allowed("DELETE", "/settings/branding"),
        "pilot allowlist exposes branding only through bounded read/update surfaces",
    )

    root = Path(__file__).resolve().parents[2]
    js_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    shell_text = (root / "src" / "web_shell.py").read_text(encoding="utf-8")
    check(
        'href="/app/settings">Ayarlar</a>' in shell_text
        and 'page="settings"' in shell_text
        and 'api("/settings/branding"' in js_text
        and 'image/svg+xml' not in js_text
        and 'critical_status_colors_locked' not in js_text,
        "pilot shell exposes Ayarlar→Branding and does not let browser redefine critical status colors",
    )

    password = "Branding-Pilot-Password-2026!"
    password_hash = hash_password(password, salt=b"brand-web-salt!!")
    import src.api as api_module

    original_repository = api_module.agency_branding_repository
    api_module.agency_branding_repository = InMemoryAgencyBrandingRepository()
    try:
        with _environment(_web_env(password_hash)):
            with TestClient(
                api_module.app, base_url="https://127.0.0.1", client=("127.0.0.1", 50000),
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
                default_response = client.get("/settings/branding")
                no_csrf = client.post("/settings/branding", json={
                    "company_name": "Pilot Agency", "logo_data_uri": None,
                    "primary_color": "#112233", "secondary_accent_color": "#445566",
                })
                saved = client.post(
                    "/settings/branding",
                    json={
                        "company_name": "Pilot Agency", "logo_data_uri": PNG_URI,
                        "primary_color": "#112233", "secondary_accent_color": "#445566",
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                reread = client.get("/settings/branding")
    finally:
        api_module.agency_branding_repository = original_repository

    default_json = default_response.json()
    saved_json = saved.json()
    reread_json = reread.json()
    check(
        logged_in.status_code == 303
        and settings_page.status_code == 200
        and "Ayarlar" in settings_page.text
        and default_response.status_code == 200
        and default_json["company_name"] == "MINAI"
        and no_csrf.status_code == 403
        and saved.status_code == 200
        and saved_json["company_name"] == "Pilot Agency"
        and saved_json["updated_by"] == "Web Operator"
        and reread_json["logo_data_uri"] == PNG_URI,
        "authenticated branding update requires CSRF and records the named operator",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_branding_settings_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nP2-13 branding settings regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
