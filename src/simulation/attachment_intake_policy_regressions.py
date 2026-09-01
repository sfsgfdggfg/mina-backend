from __future__ import annotations

from src.core.attachment_intake_policy import (
    MAX_ATTACHMENT_AUTO_FILES,
    MAX_ATTACHMENT_FILE_BYTES,
    MAX_ATTACHMENT_TOTAL_BYTES,
    assess_attachment_intake,
)
from src.core.mail import InboundAttachmentMetadata, InboundMailEnvelope


def _mail(*items, truncated=False):
    return InboundMailEnvelope(
        provider_name="microsoft_graph",
        mailbox_id="pilot@example.invalid",
        sender_address="ops@example.invalid",
        body_text="Attachment policy regression.",
        has_attachments=True,
        attachment_manifest=list(items),
        attachment_manifest_truncated=truncated,
        source="email",
    )


def _item(name, mime, size=1024, *, kind="file", inline=False):
    return InboundAttachmentMetadata(
        name=name,
        content_type=mime,
        size_bytes=size,
        kind=kind,
        is_inline=inline,
    )


def evaluate_attachment_intake_policy_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    allowlisted = assess_attachment_intake(_mail(
        _item("quote.pdf", "application/pdf"),
        _item(
            "rates.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        _item("lanes.csv", "text/csv"),
    ))
    check(
        allowlisted.status == "metadata_allowlisted"
        and allowlisted.reason_code == "attachment_metadata_allowlisted",
        "PDF XLSX CSV metadata allowlisted",
    )

    cases = [
        (_mail(), "attachment_manifest_missing", "missing manifest manual review"),
        (_mail(_item("a.pdf", "application/pdf"), truncated=True), "attachment_manifest_truncated", "truncated manifest manual review"),
        (_mail(*[_item(f"{i}.pdf", "application/pdf") for i in range(MAX_ATTACHMENT_AUTO_FILES + 1)]), "attachment_count_exceeds_limit", "attachment count bounded"),
        (_mail(_item("big.pdf", "application/pdf", MAX_ATTACHMENT_FILE_BYTES + 1)), "attachment_file_size_exceeds_limit", "per file size bounded"),
        (_mail(_item("a.pdf", "application/pdf", MAX_ATTACHMENT_TOTAL_BYTES // 2 + 1), _item("b.pdf", "application/pdf", MAX_ATTACHMENT_TOTAL_BYTES // 2 + 1)), "attachment_total_size_exceeds_limit", "total attachment size bounded"),
        (_mail(_item("inline.pdf", "application/pdf", inline=True)), "attachment_inline_not_allowed", "inline attachment manual review"),
        (_mail(_item("quote.pdf", "application/pdf", kind="item")), "attachment_kind_not_allowed", "item attachment manual review"),
        (_mail(_item("quote.pdf", "application/pdf", kind="reference")), "attachment_kind_not_allowed", "reference attachment manual review"),
        (_mail(_item("quote.pdf", "application/pdf", kind="unknown")), "attachment_kind_not_allowed", "unknown attachment kind manual review"),
        (_mail(_item("quote.xlsm", "application/vnd.ms-excel.sheet.macroenabled.12")), "attachment_extension_not_allowed", "macro workbook manual review"),
        (_mail(_item("quote.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")), "attachment_extension_not_allowed", "DOCX manual review"),
        (_mail(_item("quote.pdf", None)), "attachment_mime_missing", "missing MIME manual review"),
        (_mail(_item("quote.pdf", "text/plain")), "attachment_mime_mismatch", "MIME mismatch manual review"),
    ]
    for mail, reason, label in cases:
        result = assess_attachment_intake(mail)
        check(
            result.status == "manual_review" and result.reason_code == reason,
            label,
        )

    no_attachment_rejected = False
    try:
        assess_attachment_intake(InboundMailEnvelope(
            body_text="No attachment.",
            has_attachments=False,
        ))
    except ValueError:
        no_attachment_rejected = True
    check(no_attachment_rejected, "policy requires attachment state")

    return {
        "name": "Attachment intake metadata policy",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_attachment_intake_policy_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    if result["passed"]:
        print("\nAttachment intake policy regressions: PASS")
        return 0
    print("\nAttachment intake policy regressions: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
