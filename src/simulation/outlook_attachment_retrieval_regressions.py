from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

from src.core.attachment_intake_policy import MAX_ATTACHMENT_FILE_BYTES
from src.core.mail import InboundAttachmentMetadata, InboundMailEnvelope
from src.integrations.outlook_graph import OutlookGraphReadClient


PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


class _Response:
    def __init__(self, status_code, *, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self.payload = payload
        self.content = content
        self.headers = headers or {}
        self.closed = False

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        if self.content:
            yield self.content

    def close(self):
        self.closed = True


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


def _raw_attachment(*, name="quote.pdf", size=len(PDF)):
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": "provider-secret-attachment-id",
        "name": name,
        "contentType": "application/pdf",
        "size": size,
        "isInline": False,
    }


def _mail(*, name="quote.pdf", size=len(PDF)):
    return InboundMailEnvelope(
        external_message_id="immutable-message-id",
        provider_name="microsoft_graph",
        mailbox_id="operations@example.invalid",
        sender_address="trusted@example.invalid",
        subject="Attachment test",
        body_text="Please review.",
        received_at=datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
        has_attachments=True,
        attachment_manifest=[
            InboundAttachmentMetadata(
                name=name,
                content_type="application/pdf",
                size_bytes=size,
                kind="file",
                is_inline=False,
            )
        ],
        source="email",
    )


def evaluate_outlook_attachment_retrieval_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    session = _Session([
        _Response(200, payload={"value": [_raw_attachment()]}),
        _Response(
            200,
            content=PDF,
            headers={
                "Content-Length": str(len(PDF)),
                "Content-Type": "application/pdf",
            },
        ),
    ])
    client = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=session,
    )
    result = client.retrieve_allowlisted_attachments(_mail())
    metadata_request, content_request = session.requests
    select = (metadata_request.get("params") or {}).get("$select", "")
    serialized = result.model_dump_json()
    check(
        result.status == "verified"
        and result.content_download_performed is True
        and len(result.verified_receipts) == 1
        and result.verified_receipts[0].sha256_hex == sha256(PDF).hexdigest(),
        "allowlisted Graph attachment is transiently verified",
    )
    check(
        "id" in select
        and "contentBytes" not in select
        and metadata_request["method"] == "GET"
        and content_request["method"] == "GET"
        and content_request["url"].endswith("/provider-secret-attachment-id/$value")
        and content_request.get("allow_redirects") is False
        and content_request.get("stream") is True,
        "retrieval uses bounded GET-only raw-content boundary",
    )
    check(
        "provider-secret-attachment-id" not in serialized
        and "PDF-1.7" not in serialized
        and "secret-token" not in serialized,
        "provider IDs tokens and content do not escape receipt",
    )

    drift_session = _Session([
        _Response(200, payload={"value": [_raw_attachment(name="changed.pdf")]}),
    ])
    drift = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=drift_session,
    ).retrieve_allowlisted_attachments(_mail())
    check(
        drift.status == "manual_review"
        and drift.reason_code == "graph_attachment_manifest_changed"
        and drift.content_download_performed is False
        and len(drift_session.requests) == 1,
        "manifest drift blocks before content GET",
    )

    mismatch_session = _Session([
        _Response(200, payload={"value": [_raw_attachment()]}),
        _Response(
            200,
            content=PDF + b"x",
            headers={"Content-Type": "application/pdf"},
        ),
    ])
    mismatch = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=mismatch_session,
    ).retrieve_allowlisted_attachments(_mail())
    check(
        mismatch.status == "manual_review"
        and mismatch.reason_code == "attachment_content_size_exceeds_metadata"
        and mismatch.content_download_performed is True,
        "downloaded size mismatch fails closed",
    )

    oversized_session = _Session([
        _Response(200, payload={"value": [_raw_attachment()]}),
        _Response(
            200,
            content=b"",
            headers={
                "Content-Length": str(MAX_ATTACHMENT_FILE_BYTES + 1),
                "Content-Type": "application/pdf",
            },
        ),
    ])
    oversized = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=oversized_session,
    ).retrieve_allowlisted_attachments(_mail())
    check(
        oversized.status == "manual_review"
        and oversized.reason_code == "graph_attachment_content_exceeds_limit"
        and oversized.content_download_performed is False,
        "announced oversized content rejected before stream read",
    )

    redirect_session = _Session([
        _Response(200, payload={"value": [_raw_attachment()]}),
        _Response(302, headers={"Content-Type": "application/pdf"}),
    ])
    redirect = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=redirect_session,
    ).retrieve_allowlisted_attachments(_mail())
    check(
        redirect.status == "manual_review"
        and redirect.reason_code == "microsoft_graph_redirect_refused",
        "attachment content redirect refused",
    )

    mime_session = _Session([
        _Response(200, payload={"value": [_raw_attachment()]}),
        _Response(
            200,
            content=PDF,
            headers={"Content-Type": "application/octet-stream"},
        ),
    ])
    mime_result = OutlookGraphReadClient(
        access_token="secret-token",
        mailbox_id="operations@example.invalid",
        session=mime_session,
    ).retrieve_allowlisted_attachments(_mail())
    check(
        mime_result.status == "manual_review"
        and mime_result.reason_code == "graph_attachment_response_mime_mismatch",
        "raw response MIME must match allowlisted metadata MIME",
    )

    return {
        "name": "Controlled Outlook attachment retrieval",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_outlook_attachment_retrieval_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nOutlook attachment retrieval regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
