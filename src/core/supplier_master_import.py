from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import PurePath
from typing import Mapping

from src.core.attachment_content_verification import verify_attachment_content
from src.core.attachment_safe_extraction import extract_verified_attachment
from src.core.mail import InboundAttachmentMetadata
from src.core.master_data import MasterContact, SupplierGeographyCapability, normalize_master_text
from src.core.master_data_service import create_supplier_master
from src.core.sqlite_repositories import atomic_repository_transaction


IMPORT_FIELDS = {
    "supplier_name", "contact_name", "email", "phone", "countries",
    "region_tags", "service_types", "equipment_types", "role", "notes",
}
_PROCESS_SECRET = secrets.token_bytes(32)


class SupplierImportError(ValueError):
    pass


def _extract(file_name: str, content: bytes):
    extension = PurePath(file_name).suffix.lower()
    if extension not in {".xlsx", ".csv"}:
        raise SupplierImportError("supplier_import_file_type_not_allowed")
    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if extension == ".xlsx" else "text/csv"
    )
    metadata = InboundAttachmentMetadata(
        name=file_name, content_type=content_type, size_bytes=len(content), kind="file"
    )
    receipt = verify_attachment_content(metadata, content)
    artifact = extract_verified_attachment(
        metadata, content, expected_sha256_hex=receipt.sha256_hex,
        expected_profile=receipt.content_profile,
    )
    return receipt, artifact


def _header_row(rows: list[list[str]]) -> tuple[int, list[str]]:
    for index, row in enumerate(rows):
        if any(cell.strip() for cell in row):
            headers = [cell.strip() or f"column_{column + 1}" for column, cell in enumerate(row)]
            if len({normalize_master_text(item) for item in headers}) != len(headers):
                raise SupplierImportError("supplier_import_duplicate_headers")
            return index, headers
    raise SupplierImportError("supplier_import_headers_missing")


def _suggest(headers: list[str]) -> dict[str, str]:
    aliases = {
        "supplier_name": {"supplier", "supplier name", "supplier_name", "tedarikci", "tedarikçi", "firma", "firma adi", "firma adı"},
        "contact_name": {"contact", "contact name", "contact_name", "yetkili", "kisi", "kişi"},
        "email": {"email", "e-mail", "eposta", "e posta"},
        "phone": {"phone", "telefon", "tel", "mobile"},
        "countries": {"countries", "country", "ulkeler", "ülkeler", "ulke", "ülke"},
        "region_tags": {"regions", "region", "region tags", "region_tags", "bolgeler", "bölgeler", "bolge", "bölge"},
        "service_types": {"service types", "service_type", "service_types", "services", "servis", "hizmetler"},
        "equipment_types": {"equipment", "equipment types", "equipment_types", "ekipman", "ekipmanlar"},
        "role": {"role", "rol"},
        "notes": {"notes", "note", "not", "notlar"},
    }
    normalized = {normalize_master_text(header): header for header in headers}
    return {
        field: normalized[alias]
        for field, values in aliases.items()
        for alias in values
        if alias in normalized
    }


def inspect_supplier_import(*, file_name: str, content: bytes) -> dict:
    receipt, artifact = _extract(file_name, content)
    tables = []
    for table in artifact.tables:
        header_index, headers = _header_row(table.rows)
        tables.append({
            "name": table.name, "headers": headers,
            "row_count": max(0, table.row_count - header_index - 1),
            "sample": table.rows[header_index + 1:header_index + 6],
            "suggested_mapping": _suggest(headers),
        })
    return {
        "file_sha256": receipt.sha256_hex, "file_name": file_name,
        "tables": tables, "limits": {"sample_rows": 5, "maximum_rows_per_table": 1000},
        "raw_file_stored": False,
    }


def _split(value: str) -> list[str]:
    return list(dict.fromkeys(
        item.strip() for item in re.split(r"[;,|\n]+", value or "") if item.strip()
    ))


def _state_digest(repository) -> str:
    payload = [
        item.model_dump(mode="json") for item in repository.list_suppliers()
    ]
    payload.sort(key=lambda item: item["supplier_id"])
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _token_key(environ: Mapping[str, str] | None = None) -> bytes:
    env = environ if environ is not None else os.environ
    configured = (env.get("MINAI_WEB_SESSION_SECRET") or "").strip()
    return configured.encode() if len(configured) >= 32 else _PROCESS_SECRET


def _token(*, file_sha: str, table_name: str, mapping: dict[str, str], state_sha: str) -> str:
    payload = json.dumps(
        {"file_sha256": file_sha, "table": table_name, "mapping": mapping, "master_state": state_sha},
        sort_keys=True, separators=(",", ":"),
    ).encode()
    return hmac.new(_token_key(), payload, hashlib.sha256).hexdigest()


def _validate_mapping(headers: list[str], mapping: dict[str, str]) -> None:
    if set(mapping) - IMPORT_FIELDS or not mapping.get("supplier_name"):
        raise SupplierImportError("supplier_import_mapping_invalid")
    values = [value for value in mapping.values() if value]
    if len(values) != len(set(values)) or any(value not in headers for value in values):
        raise SupplierImportError("supplier_import_mapping_invalid")


def preview_supplier_import(
    *, repository, file_name: str, content: bytes, table_name: str,
    mapping: dict[str, str],
) -> dict:
    receipt, artifact = _extract(file_name, content)
    table = next((item for item in artifact.tables if item.name == table_name), None)
    if table is None:
        raise SupplierImportError("supplier_import_table_not_found")
    header_index, headers = _header_row(table.rows)
    _validate_mapping(headers, mapping)
    indexes = {field: headers.index(header) for field, header in mapping.items() if header}
    existing_names = {normalize_master_text(item.supplier_name) for item in repository.list_suppliers()}
    existing_emails = {
        contact.email.casefold() for item in repository.list_suppliers()
        for contact in item.contacts if contact.active and contact.email
    }
    seen_names: set[str] = set()
    seen_emails: set[str] = set()
    rows = []
    valid_payloads = []
    for row_number, raw in enumerate(table.rows[header_index + 1:], start=header_index + 2):
        values = {field: (raw[index].strip() if index < len(raw) else "") for field, index in indexes.items()}
        if not any(values.values()):
            continue
        reasons: list[str] = []
        name = values.get("supplier_name", "")
        email = values.get("email", "").casefold()
        phone = values.get("phone", "")
        name_key = normalize_master_text(name) if name else ""
        if not name or len(name) > 240:
            reasons.append("supplier_name_invalid")
        if email and (email.count("@") != 1 or any(ch.isspace() for ch in email) or len(email) > 320):
            reasons.append("email_invalid")
        if values.get("contact_name") and not (email or phone):
            reasons.append("contact_requires_email_or_phone")
        role = values.get("role", "").casefold() or "backup"
        if role not in {"primary", "backup", "specialist"}:
            reasons.append("role_invalid")
        duplicate = name_key in existing_names or name_key in seen_names or bool(email and (email in existing_emails or email in seen_emails))
        classification = "invalid" if reasons else "duplicate" if duplicate else "valid"
        row_result = {"row_number": row_number, "classification": classification, "reasons": reasons}
        rows.append(row_result)
        if classification != "valid":
            continue
        countries = _split(values.get("countries", ""))
        contacts = []
        if email or phone:
            contacts.append(MasterContact(
                contact_name=values.get("contact_name") or None,
                email=email or None, phone=phone or None, roles=["other"], is_primary=True,
            ))
        payload = {
            "supplier_name": name, "role": role, "contacts": contacts,
            "geographies": [SupplierGeographyCapability(
                scope_type="country", scope_name=country, source="excel_import"
            ) for country in countries],
            "legacy_region_tags": _split(values.get("region_tags", "")),
            "service_types": _split(values.get("service_types", "")),
            "equipment_types": _split(values.get("equipment_types", "")),
            "notes": values.get("notes") or "Imported supplier profile.",
        }
        valid_payloads.append((row_number, payload))
        seen_names.add(name_key)
        if email:
            seen_emails.add(email)
    state_sha = _state_digest(repository)
    return {
        "file_sha256": receipt.sha256_hex, "table": table_name, "mapping": mapping,
        "master_data_state_sha256": state_sha,
        "preview_token": _token(file_sha=receipt.sha256_hex, table_name=table_name, mapping=mapping, state_sha=state_sha),
        "counts": {kind: sum(item["classification"] == kind for item in rows) for kind in ("valid", "duplicate", "invalid")},
        "rows": rows[:1000], "_valid_payloads": valid_payloads,
    }


def apply_supplier_import(
    *, repository, file_name: str, content: bytes, table_name: str,
    mapping: dict[str, str], preview_token: str, operator: str,
) -> dict:
    with atomic_repository_transaction(repository):
        preview = preview_supplier_import(
            repository=repository, file_name=file_name, content=content,
            table_name=table_name, mapping=mapping,
        )
        if not hmac.compare_digest(preview_token, preview["preview_token"]):
            raise SupplierImportError("supplier_import_preview_stale_or_invalid")
        created = []
        for row_number, payload in preview.pop("_valid_payloads"):
            profile = create_supplier_master(
                repository=repository,
                entry_id=f"excel-import:{preview['file_sha256']}:{table_name}:{row_number}",
                updated_by=operator, source="excel_import", **payload,
            )
            created.append(profile.supplier_id)
    return {
        "applied": len(created), "created_supplier_ids": created,
        "skipped_duplicates": preview["counts"]["duplicate"],
        "invalid": preview["counts"]["invalid"],
        "file_sha256": preview["file_sha256"], "source": "excel_import",
    }
