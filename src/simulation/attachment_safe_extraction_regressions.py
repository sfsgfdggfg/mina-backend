from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from pypdf import PdfWriter

from src.core.attachment_safe_extraction import (
    AttachmentSafeExtractionError,
    extract_verified_attachment,
)
from src.core.mail import InboundAttachmentMetadata


def _pdf_with_text(text="MINAI attachment extraction") -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(output)
    output += f"xref\n0 {len(objects) + 1}\n".encode()
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += f"{offset:010d} 00000 n \n".encode()
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(output)


def _encrypted_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _xlsx(*, formula=False) -> bytes:
    sheet_value = (
        '<row r="1"><c r="A1" t="inlineStr"><is><t>Lane</t></is></c>'
        '<c r="B1" t="inlineStr"><is><t>Price</t></is></c></row>'
        '<row r="2"><c r="A2" t="inlineStr"><is><t>Adana-Hamburg</t></is></c>'
        + ('<c r="B2"><f>1+1</f><v>2</v></c>' if formula else '<c r="B2"><v>2300</v></c>')
        + '</row>'
    )
    entries = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
        "xl/workbook.xml": '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Rates" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>',
        "xl/worksheets/sheet1.xml": '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + sheet_value + '</sheetData></worksheet>',
    }
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue()


def _meta(name, content_type, size):
    return InboundAttachmentMetadata(
        name=name,
        content_type=content_type,
        size_bytes=size,
        kind="file",
        is_inline=False,
    )


def _extract(name, mime, content, profile):
    return extract_verified_attachment(
        _meta(name, mime, len(content)),
        content,
        expected_sha256_hex=sha256(content).hexdigest(),
        expected_profile=profile,
    )


def evaluate_attachment_safe_extraction_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    pdf = _pdf_with_text()
    pdf_result = _extract("quote.pdf", "application/pdf", pdf, "pdf")
    check(
        pdf_result.extraction_kind == "text"
        and pdf_result.text == "MINAI attachment extraction"
        and pdf_result.character_count == len("MINAI attachment extraction")
        and pdf_result.table_count == 0,
        "PDF text is bounded into provider-neutral artifact",
    )

    try:
        encrypted = _encrypted_pdf()
        _extract("secret.pdf", "application/pdf", encrypted, "pdf")
    except AttachmentSafeExtractionError as exc:
        encrypted_code = exc.code
    else:
        encrypted_code = None
    check(
        encrypted_code == "attachment_pdf_encrypted_not_allowed",
        "encrypted PDF fails closed",
    )

    xlsx = _xlsx()
    xlsx_result = _extract(
        "rates.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        xlsx,
        "xlsx",
    )
    check(
        xlsx_result.extraction_kind == "tables"
        and xlsx_result.table_count == 1
        and xlsx_result.tables[0].rows == [["Lane", "Price"], ["Adana-Hamburg", "2300"]]
        and xlsx_result.cell_count == 4,
        "XLSX cells are extracted without formula evaluation",
    )

    try:
        formula = _xlsx(formula=True)
        _extract(
            "formula.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            formula,
            "xlsx",
        )
    except AttachmentSafeExtractionError as exc:
        formula_code = exc.code
    else:
        formula_code = None
    check(
        formula_code == "attachment_xlsx_formula_present",
        "XLSX formula content fails closed",
    )

    csv_bytes = "Lane;Price\nAdana-Hamburg;2300\n".encode()
    csv_result = _extract("rates.csv", "text/csv", csv_bytes, "csv")
    check(
        csv_result.extraction_kind == "tables"
        and csv_result.tables[0].rows == [["Lane", "Price"], ["Adana-Hamburg", "2300"]]
        and csv_result.cell_count == 4,
        "CSV delimiter and table cells are extracted deterministically",
    )

    try:
        extract_verified_attachment(
            _meta("quote.pdf", "application/pdf", len(pdf)),
            pdf,
            expected_sha256_hex="0" * 64,
            expected_profile="pdf",
        )
    except AttachmentSafeExtractionError as exc:
        digest_code = exc.code
    else:
        digest_code = None
    check(
        digest_code == "attachment_extraction_digest_mismatch",
        "extraction refuses content that does not match verification digest",
    )

    long_csv = ("x" * 2001 + "\n").encode()
    try:
        _extract("long.csv", "text/csv", long_csv, "csv")
    except AttachmentSafeExtractionError as exc:
        long_code = exc.code
    else:
        long_code = None
    check(
        long_code == "attachment_extracted_cell_exceeds_limit",
        "oversized extracted cell fails closed without truncation",
    )

    return {
        "name": "Safe attachment extraction",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_attachment_safe_extraction_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nSafe attachment extraction regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
