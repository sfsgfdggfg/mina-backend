from __future__ import annotations

import json
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from src.core.master_data_repository import InMemoryMasterDataRepository, SQLiteMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.runtime_release import runtime_release_payload
from src.core.supplier_master_import import (
    SupplierImportError, apply_supplier_import, inspect_supplier_import,
    preview_supplier_import,
)
from src.core.web_session import (
    InMemoryWebSessionStore, WebSessionConfigurationError, WebUser,
    authenticate_web_user, change_web_user_password, hash_password,
)
from src.integrations.mailbox_credentials import resolve_imap_setup_defaults
from src.simulation.physical_temp import physical_temporary_directory


def _xlsx(*, formula: bool = False) -> bytes:
    cell = '<c r="A2"><f>1+1</f><v>2</v></c>' if formula else '<c r="A2" t="inlineStr"><is><t>Sheet Supplier</t></is></c>'
    sheet = f'''<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>supplier_name</t></is></c><c r="B1" t="inlineStr"><is><t>email</t></is></c></row>
<row r="2">{cell}<c r="B2" t="inlineStr"><is><t>sheet@example.invalid</t></is></c></row>
</sheetData></worksheet>'''
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return output.getvalue()


def evaluate_pilot_hardening_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    defaults = resolve_imap_setup_defaults(
        "ops@example.invalid", {"MINAI_IMAP_DEFAULT_PORT": "993"}
    )
    explicit = resolve_imap_setup_defaults("ops@example.invalid", {
        "MINAI_IMAP_DEFAULT_HOST": "imap.example.invalid",
        "MINAI_IMAP_DEFAULT_PORT": "994",
        "MINAI_IMAP_DEFAULT_USERNAME": "agency-user",
        "MINAI_IMAP_DEFAULT_CERTIFICATE_SHA256": "ab" * 32,
    })
    check(
        defaults["host"] == "mail.example.invalid" and defaults["username"] == "ops@example.invalid"
        and explicit["host"] == "imap.example.invalid" and explicit["port"] == 994
        and explicit["certificate_sha256"] == "ab" * 32,
        "IMAP onboarding resolves safe deployment defaults and conservative mailbox fallbacks",
    )

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1"}, clear=False):
        os.environ.pop("MINAI_PILOT_AIR_WORKSPACE_ENABLED", None)
        hidden = runtime_release_payload()["capabilities"]["air_workspace_enabled"] is False
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "1", "MINAI_PILOT_AIR_WORKSPACE_ENABLED": "1"}, clear=False):
        enabled = runtime_release_payload()["capabilities"]["air_workspace_enabled"] is True
    js = (Path(__file__).resolve().parents[2] / "ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        hidden and enabled and 'if(runtimeCapabilities.air_workspace_enabled)' in js
        and 'const maybe=(path)=>air?api(path):Promise.resolve({})' in js,
        "controlled pilot hides Air by default and the disabled UI does not call Air settings APIs",
    )

    repo = InMemoryMasterDataRepository()
    csv_content = (
        "supplier_name,email,countries,region_tags,service_types\n"
        "Alpha,alpha@example.invalid,TR;DE,DACH,FTL\n"
        "Alpha,other@example.invalid,TR,,FTL\n"
        "No Contact Name,invalid email,TR,,FTL\n"
    ).encode()
    inspected = inspect_supplier_import(file_name="suppliers.csv", content=csv_content)
    mapping = inspected["tables"][0]["suggested_mapping"]
    preview = preview_supplier_import(
        repository=repo, file_name="suppliers.csv", content=csv_content,
        table_name="csv", mapping=mapping,
    )
    token = preview["preview_token"]
    result = apply_supplier_import(
        repository=repo, file_name="suppliers.csv", content=csv_content,
        table_name="csv", mapping=mapping, preview_token=token, operator="Import Operator",
    )
    imported = repo.find_supplier_by_name("Alpha")
    check(
        result["applied"] == 1 and result["skipped_duplicates"] == 1 and result["invalid"] == 1
        and imported is not None and imported.source == "excel_import"
        and imported.updated_by == "Import Operator"
        and {geo.scope_name for geo in imported.geographies} == {"TR", "DE"}
        and imported.legacy_region_tags == ["DACH"],
        "CSV supplier import maps fields, skips duplicates/invalid rows, and preserves operator provenance",
    )
    xlsx_inspected = inspect_supplier_import(file_name="suppliers.xlsx", content=_xlsx())
    formula_blocked = False
    try:
        inspect_supplier_import(file_name="formula.xlsx", content=_xlsx(formula=True))
    except ValueError:
        formula_blocked = True
    check(
        xlsx_inspected["tables"][0]["headers"] == ["supplier_name", "email"] and formula_blocked,
        "XLSX import is bounded and rejects formula cells instead of executing or trusting them",
    )
    stale_repo = InMemoryMasterDataRepository()
    stale = preview_supplier_import(
        repository=stale_repo, file_name="suppliers.csv", content=csv_content,
        table_name="csv", mapping=mapping,
    )
    create_supplier_master(
        repository=stale_repo, entry_id="concurrent", supplier_name="Concurrent",
        updated_by="Other Operator", source="manual",
    )
    stale_blocked = False
    try:
        apply_supplier_import(
            repository=stale_repo, file_name="suppliers.csv", content=csv_content,
            table_name="csv", mapping=mapping, preview_token=stale["preview_token"],
            operator="Import Operator",
        )
    except SupplierImportError:
        stale_blocked = True
    check(stale_blocked, "supplier import apply fails closed when Master Data changed after preview")

    with physical_temporary_directory() as temporary:
        sqlite_path = Path(temporary) / "supplier-import.sqlite3"
        sqlite_repo = SQLiteMasterDataRepository(SQLitePilotStore(sqlite_path))
        sqlite_preview = preview_supplier_import(
            repository=sqlite_repo, file_name="suppliers.csv", content=csv_content,
            table_name="csv", mapping=mapping,
        )
        sqlite_result = apply_supplier_import(
            repository=sqlite_repo, file_name="suppliers.csv", content=csv_content,
            table_name="csv", mapping=mapping,
            preview_token=sqlite_preview["preview_token"], operator="SQLite Import Operator",
        )
        reopened_repo = SQLiteMasterDataRepository(SQLitePilotStore(sqlite_path))
        persisted = reopened_repo.find_supplier_by_name("Alpha")
        check(
            sqlite_result["applied"] == 1
            and persisted is not None
            and persisted.updated_by == "SQLite Import Operator"
            and persisted.source == "excel_import",
            "supplier import apply participates in the outer SQLite transaction and survives repository restart",
        )

    with physical_temporary_directory() as temporary:
        root = Path(temporary)
        override_path = root / "private" / "passwords.json"
        old_password = "old-password-2026"
        new_password = "new-password-2026"
        env = {
            "MINAI_PILOT_MODE": "1",
            "MINAI_WEB_USERS_JSON": json.dumps({
                "ops@example.com": {"name": "Web Operator", "password_hash": hash_password(old_password), "active": True}
            }),
            "MINAI_WEB_PASSWORD_OVERRIDES_PATH": str(override_path),
            "MINAI_WEB_SESSION_SECRET": "s" * 40,
            "MINAI_WEB_SHELL_ENABLED": "1",
        }
        change_web_user_password(
            email="ops@example.com", current_password=old_password,
            new_password=new_password, environ=env,
        )
        stored = override_path.read_text(encoding="utf-8")
        permissions_ok = os.name != "posix" or override_path.stat().st_mode & 0o077 == 0
        check(
            authenticate_web_user("ops@example.com", old_password, environ=env) is None
            and authenticate_web_user("ops@example.com", new_password, environ=env) is not None
            and old_password not in stored and new_password not in stored and permissions_ok,
            "password override persists only scrypt hash with owner-only permissions and replaces old authentication",
        )
        wrong = weak = long = False
        for candidate, password in (("wrong", "another-password"), ("weak", "short"), ("long", "x" * 129)):
            try:
                change_web_user_password(
                    email="ops@example.com",
                    current_password=("wrong" if candidate == "wrong" else new_password),
                    new_password=password, environ=env,
                )
            except ValueError:
                if candidate == "wrong": wrong = True
                elif candidate == "weak": weak = True
                else: long = True
        symlink = root / "password-link.json"
        symlink.symlink_to(override_path)
        symlink_rejected = False
        try:
            change_web_user_password(
                email="ops@example.com", current_password=new_password,
                new_password="third-password-2026",
                environ={**env, "MINAI_WEB_PASSWORD_OVERRIDES_PATH": str(symlink)},
            )
        except WebSessionConfigurationError:
            symlink_rejected = True
        check(wrong and weak and long and symlink_rejected, "password change rejects wrong current, weak/long values, and symlink storage")

        sessions = InMemoryWebSessionStore()
        user = WebUser("ops@example.com", "Web Operator", hash_password(new_password))
        first, first_cookie = sessions.create(user, environ=env)
        second, second_cookie = sessions.create(user, environ=env)
        sessions.invalidate_email(user.email)
        check(
            sessions.resolve(first_cookie, environ=env) is None
            and sessions.resolve(second_cookie, environ=env) is None
            and route_allowed("GET", "/settings/password")
            and route_allowed("POST", "/settings/password/change"),
            "password change route is narrowly allowlisted and all user sessions can be invalidated",
        )

    return {
        "passed": not failures,
        "failures": failures,
        "checks_passed": passes,
    }


if __name__ == "__main__":
    report = evaluate_pilot_hardening_regressions()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)
