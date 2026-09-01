from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfWriter

from src.core.mail import InboundAttachmentMetadata, InboundMailEnvelope
from src.integrations.outlook_graph import OutlookGraphReadClient
from src.simulation.attachment_safe_extraction_regressions import _pdf_with_text


class _Response:
    def __init__(self, status_code, *, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self.payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        if self.content:
            yield self.content

    def close(self):
        pass


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)


def _raw_attachment(size):
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": "provider-extraction-secret-id",
        "name": "quote.pdf",
        "contentType": "application/pdf",
        "size": size,
        "isInline": False,
    }


def _mail(size):
    return InboundMailEnvelope(
        external_message_id="immutable-extraction-message",
        provider_name="microsoft_graph",
        mailbox_id="operations@example.invalid",
        sender_address="trusted@example.invalid",
        subject="Attachment extraction test",
        body_text="Please review.",
        received_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        has_attachments=True,
        attachment_manifest=[
            InboundAttachmentMetadata(
                name="quote.pdf",
                content_type="application/pdf",
                size_bytes=size,
                kind="file",
                is_inline=False,
            )
        ],
        source="email",
    )


def _encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _client_for(content):
    session = _Session([
        _Response(200, payload={"value": [_raw_attachment(len(content))]}),
        _Response(
            200,
            content=content,
            headers={
                "Content-Length": str(len(content)),
                "Content-Type": "application/pdf",
            },
        ),
    ])
    return OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=session,
    ), session


def evaluate_outlook_attachment_extraction_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    pdf = _pdf_with_text("Supplier rate 2300 EUR")
    client, session = _client_for(pdf)
    result = client.retrieve_and_extract_allowlisted_attachments(_mail(len(pdf)))
    serialized = result.model_dump_json()
    check(
        result.status == "verified"
        and result.extraction_attempted is True
        and len(result.extracted_artifacts) == 1
        and result.extracted_artifacts[0].text == "Supplier rate 2300 EUR"
        and result.extracted_artifacts[0].character_count == len("Supplier rate 2300 EUR"),
        "verified Graph PDF is extracted transiently",
    )
    check(
        "Supplier rate 2300 EUR" not in serialized
        and "extracted_artifacts" not in serialized
        and "provider-extraction-secret-id" not in serialized
        and all(request["method"] == "GET" for request in session.requests),
        "extracted content and provider ID are excluded from serialized retrieval receipt",
    )

    verify_only_client, _ = _client_for(pdf)
    verify_only = verify_only_client.retrieve_allowlisted_attachments(_mail(len(pdf)))
    check(
        verify_only.status == "verified"
        and verify_only.extraction_attempted is False
        and not verify_only.extracted_artifacts,
        "P1-55 verification-only retrieval remains unchanged",
    )

    encrypted = _encrypted_pdf()
    encrypted_client, _ = _client_for(encrypted)
    encrypted_result = encrypted_client.retrieve_and_extract_allowlisted_attachments(
        _mail(len(encrypted))
    )
    check(
        encrypted_result.status == "manual_review"
        and encrypted_result.reason_code == "attachment_pdf_encrypted_not_allowed"
        and encrypted_result.extraction_attempted is True
        and encrypted_result.content_download_performed is True
        and not encrypted_result.extracted_artifacts,
        "extraction failure returns sanitized manual review result",
    )

    return {
        "name": "Controlled Outlook attachment extraction",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_outlook_attachment_extraction_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nOutlook attachment extraction regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
