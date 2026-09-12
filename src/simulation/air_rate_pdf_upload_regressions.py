from __future__ import annotations

import asyncio
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_rate_document_store import (
    AirRateDocumentStore,
    resolve_air_rate_storage_directory,
)
from src.core.air_rate_source_service import (
    AirRateSourceUploadError,
    build_air_rate_source_view,
    register_commercial_air_rate_pdf,
)
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.pilot_access import route_allowed


PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def evaluate_air_rate_pdf_upload_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    with TemporaryDirectory() as temporary:
        root = Path(temporary) / "air-rate-sources"
        store = AirRateDocumentStore(root)
        repo = InMemoryAirShadowRepository()
        source, created = register_commercial_air_rate_pdf(
            repository=repo,
            document_store=store,
            entry_id="upload-thy-general-202609",
            airline_name="THY",
            document_name="thy-general-september.pdf",
            content_type="application/pdf",
            content=PDF,
            cargo_scope="general_cargo",
            origin_airport="ada",
            recorded_by="Pilot Operator",
            notes="Synthetic upload regression.",
        )
        path = store.path_for_sha256(source.sha256_hex)
        check(created and source.size_bytes == len(PDF) and source.origin_airport == "ADA",
              "verified commercial-air PDF creates metadata-only source identity")
        check(path.name == f"{source.sha256_hex}.pdf" and path.read_bytes() == PDF,
              "protected document storage is content-addressed and preserves exact PDF bytes")
        check(stat.S_IMODE(root.stat().st_mode) == 0o700 and stat.S_IMODE(path.stat().st_mode) == 0o600,
              "air-rate storage hardens directory and PDF permissions")
        check("thy-general-september.pdf" not in str(path),
              "commercially sensitive original document name is not used as storage path")
        check(PDF.decode("latin1") not in source.model_dump_json(),
              "raw commercial-air PDF bytes never enter durable source metadata")
        retry, retry_created = register_commercial_air_rate_pdf(
            repository=repo,
            document_store=store,
            entry_id="upload-thy-general-202609",
            airline_name="THY",
            document_name="thy-general-september.pdf",
            content_type="application/pdf; charset=binary",
            content=PDF,
            cargo_scope="general_cargo",
            origin_airport="ADA",
            recorded_by="Pilot Operator",
            notes="Synthetic upload regression.",
        )
        check(not retry_created and retry.source_id == source.source_id,
              "identical air-rate PDF upload retry is idempotent")
        view = build_air_rate_source_view(repository=repo, document_store=store)
        check(view["shadow_only"] is True and view["commercial_air_pricing_enabled"] is False
              and view["express_pricing_enabled"] is False
              and view["rate_sources"][0]["document_stored"] is True
              and view["rate_sources"][0]["runtime_authoritative"] is False,
              "read-only air-rate listing exposes stored evidence without pricing authority")

        invalid_signature = False
        try:
            register_commercial_air_rate_pdf(
                repository=repo, document_store=store, entry_id="bad-pdf",
                airline_name="THY", document_name="bad.pdf", content_type="application/pdf",
                content=b"not a pdf", recorded_by="Pilot Operator",
            )
        except AirRateSourceUploadError as exc:
            invalid_signature = exc.code == "attachment_pdf_signature_invalid"
        check(invalid_signature, "air-rate upload reuses bounded PDF signature verification")

        wrong_type = False
        try:
            register_commercial_air_rate_pdf(
                repository=repo, document_store=store, entry_id="wrong-type",
                airline_name="THY", document_name="rates.pdf", content_type="application/octet-stream",
                content=PDF, recorded_by="Pilot Operator",
            )
        except AirRateSourceUploadError as exc:
            wrong_type = exc.code == "air_rate_pdf_content_type_required"
        check(wrong_type, "air-rate upload rejects non-PDF content type")

        path_name_rejected = False
        try:
            register_commercial_air_rate_pdf(
                repository=repo, document_store=store, entry_id="path-name",
                airline_name="THY", document_name="../secret.pdf", content_type="application/pdf",
                content=PDF, recorded_by="Pilot Operator",
            )
        except ValueError:
            path_name_rejected = True
        check(path_name_rejected, "air-rate source rejects path-like uploaded document names")

    with TemporaryDirectory() as temporary:
        db_path = Path(temporary) / "pilot.sqlite3"
        resolved = resolve_air_rate_storage_directory({
            "MINAI_PILOT_MODE": "1",
            "MINAI_PILOT_DB_PATH": str(db_path),
        })
        check(resolved == db_path.parent / "air-rate-sources",
              "pilot document storage defaults beside external pilot database and outside repository")

    from src import api
    with TemporaryDirectory() as temporary:
        api_repo = InMemoryAirShadowRepository()
        api_store = AirRateDocumentStore(Path(temporary) / "api-air")
        original_repo, original_store = api.air_shadow_repository, api.air_rate_document_store
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": PDF, "more_body": False}

        request = Request({
            "type": "http", "method": "POST", "path": "/air-rate-sources/upload",
            "headers": [
                (b"content-type", b"application/pdf"),
                (b"content-length", str(len(PDF)).encode("ascii")),
            ],
        }, receive)
        request.state.pilot_operator = "API Operator"
        try:
            api.air_shadow_repository, api.air_rate_document_store = api_repo, api_store
            response = asyncio.run(api.upload_air_rate_source(
                request,
                entry_id="api-air-upload",
                airline_name="THY",
                document_name="api-rate.pdf",
                cargo_scope="general_cargo",
                origin_airport="ADA",
                valid_from=None,
                valid_to=None,
                notes=None,
            ))
            listing = api.list_air_rate_sources()
        finally:
            api.air_shadow_repository, api.air_rate_document_store = original_repo, original_store
        check(response["created"] is True and response["shadow_only"] is True
              and response["rate_source"]["document_stored"] is True
              and len(listing["rate_sources"]) == 1,
              "controlled API uploads and lists commercial-air PDF evidence")

    check(route_allowed("GET", "/air-rate-sources")
          and route_allowed("POST", "/air-rate-sources/upload"),
          "pilot access explicitly allows bounded air-rate upload and read-only listing")

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check("Havayolu Listeleri" in js and "/air-rate-sources/upload?" in js
          and 'file.accept="application/pdf,.pdf"' in js
          and "Bu ekran fiyat üretmez" in js
          and "10*1024*1024" in js,
          "browser settings exposes PDF-only commercial-air shadow upload with visible authority boundary")

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_pdf_upload_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir rate PDF upload regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
