from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from src.core.attachment_content_verification import (
    AttachmentContentVerificationError,
    verify_attachment_content,
)
from src.core.mail import InboundAttachmentMetadata


def _metadata(name: str, content_type: str, data: bytes):
    return InboundAttachmentMetadata(
        name=name,
        content_type=content_type,
        size_bytes=len(data),
        kind="file",
        is_inline=False,
    )


def _xlsx(*, macro: bool = False) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("_rels/.rels", "<Relationships/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        if macro:
            archive.writestr("xl/vbaProject.bin", b"macro")
    return buffer.getvalue()


def evaluate_attachment_content_verification_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    pdf = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
    pdf_receipt = verify_attachment_content(
        _metadata("quote.pdf", "application/pdf", pdf),
        bytearray(pdf),
    )
    check(
        pdf_receipt.content_profile == "pdf"
        and pdf_receipt.sha256_hex == sha256(pdf).hexdigest()
        and "PDF-1.7" not in pdf_receipt.model_dump_json(),
        "PDF signature yields safe hash receipt",
    )

    invalid_pdf_rejected = False
    try:
        verify_attachment_content(
            _metadata("quote.pdf", "application/pdf", b"not-pdf"),
            bytearray(b"not-pdf"),
        )
    except AttachmentContentVerificationError as exc:
        invalid_pdf_rejected = exc.code == "attachment_pdf_signature_invalid"
    check(invalid_pdf_rejected, "invalid PDF signature rejected")

    xlsx = _xlsx()
    xlsx_receipt = verify_attachment_content(
        _metadata(
            "rates.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            xlsx,
        ),
        bytearray(xlsx),
    )
    check(xlsx_receipt.content_profile == "xlsx", "XLSX container structure verified")

    macro = _xlsx(macro=True)
    macro_rejected = False
    try:
        verify_attachment_content(
            _metadata(
                "rates.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                macro,
            ),
            bytearray(macro),
        )
    except AttachmentContentVerificationError as exc:
        macro_rejected = exc.code == "attachment_xlsx_macro_content_rejected"
    check(macro_rejected, "macro-bearing XLSX rejected")

    csv_data = "lane;price\nAdana-Hamburg;2300\n".encode("utf-8")
    csv_receipt = verify_attachment_content(
        _metadata("rates.csv", "text/csv", csv_data),
        bytearray(csv_data),
    )
    check(csv_receipt.content_profile == "csv", "UTF-8 CSV content profile verified")

    binary_csv = b"lane,price\x00evil"
    binary_csv_rejected = False
    try:
        verify_attachment_content(
            _metadata("rates.csv", "text/csv", binary_csv),
            bytearray(binary_csv),
        )
    except AttachmentContentVerificationError as exc:
        binary_csv_rejected = exc.code == "attachment_csv_binary_content_rejected"
    check(binary_csv_rejected, "binary CSV content rejected")

    smaller_raw_allowed = verify_attachment_content(
        _metadata("quote.pdf", "application/pdf", pdf).model_copy(
            update={"size_bytes": len(pdf) + 212}
        ),
        bytearray(pdf),
    )
    check(
        smaller_raw_allowed.size_bytes == len(pdf),
        "raw content may be smaller than Graph attachment size",
    )

    raw_exceeds_metadata = False
    wrong = _metadata("quote.pdf", "application/pdf", pdf).model_copy(
        update={"size_bytes": len(pdf) - 1}
    )
    try:
        verify_attachment_content(wrong, bytearray(pdf))
    except AttachmentContentVerificationError as exc:
        raw_exceeds_metadata = (
            exc.code == "attachment_content_size_exceeds_metadata"
        )
    check(raw_exceeds_metadata, "raw content cannot exceed Graph metadata size")

    return {
        "name": "Attachment content verification",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_attachment_content_verification_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAttachment content verification regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
