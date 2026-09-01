from __future__ import annotations

import csv
import logging
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import PurePath
import re
from typing import Literal
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.core.mail import InboundAttachmentMetadata


# pypdf strict=False may emit structural recovery warnings. Extraction failures
# are represented by sanitized reason codes instead of uncontrolled stderr logs.
_PYPDF_LOGGER = logging.getLogger("pypdf")
_PYPDF_LOGGER.setLevel(logging.ERROR)


MAX_EXTRACTED_CHARS_PER_FILE = 100_000
MAX_CELL_CHARS = 2_000
MAX_PDF_PAGES = 50
MAX_XLSX_SHEETS = 10
MAX_XLSX_ROWS_PER_SHEET = 200
MAX_XLSX_COLUMNS = 50
MAX_CSV_ROWS = 1_000
MAX_TABLE_CELLS_PER_FILE = 5_000
MAX_XLSX_XML_PART_BYTES = 5 * 1024 * 1024
MAX_XLSX_RELEVANT_XML_BYTES = 20 * 1024 * 1024

AttachmentExtractionKind = Literal["text", "tables"]
AttachmentExtractionProfile = Literal["pdf", "xlsx", "csv"]


class AttachmentSafeExtractionError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SafeExtractedTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    rows: list[list[str]] = Field(repr=False)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.row_count != len(self.rows):
            raise ValueError("Extracted table row_count mismatch.")
        if any(len(row) != self.column_count for row in self.rows):
            raise ValueError("Extracted table column_count mismatch.")
        return self


class SafeAttachmentExtractionArtifact(BaseModel):
    """Bounded provider-neutral extracted content. Never contains raw bytes or provider IDs."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=512)
    content_profile: AttachmentExtractionProfile
    extraction_kind: AttachmentExtractionKind
    text: str | None = Field(default=None, repr=False)
    tables: list[SafeExtractedTable] = Field(default_factory=list, repr=False)
    character_count: int = Field(ge=0)
    table_count: int = Field(ge=0)
    cell_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_kind(self):
        if self.extraction_kind == "text":
            if self.text is None or self.tables:
                raise ValueError("Text extraction artifact shape is invalid.")
        elif self.text is not None or not self.tables:
            raise ValueError("Table extraction artifact shape is invalid.")
        if self.table_count != len(self.tables):
            raise ValueError("Extraction table_count mismatch.")
        if self.cell_count != sum(table.cell_count for table in self.tables):
            raise ValueError("Extraction cell_count mismatch.")
        return self


def _normalize_extracted_text(value: str, *, empty_code: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise AttachmentSafeExtractionError(empty_code)
    if "\x00" in normalized or any(
        ord(character) < 32 and character not in "\t\n"
        for character in normalized
    ):
        raise AttachmentSafeExtractionError("attachment_extracted_text_control_character_rejected")
    if len(normalized) > MAX_EXTRACTED_CHARS_PER_FILE:
        raise AttachmentSafeExtractionError("attachment_extracted_text_exceeds_limit")
    return normalized


def _normalize_cell(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\x00" in normalized or any(
        ord(character) < 32 and character not in "\t\n"
        for character in normalized
    ):
        raise AttachmentSafeExtractionError("attachment_extracted_cell_control_character_rejected")
    if len(normalized) > MAX_CELL_CHARS:
        raise AttachmentSafeExtractionError("attachment_extracted_cell_exceeds_limit")
    return normalized


def _text_artifact(metadata: InboundAttachmentMetadata, profile: AttachmentExtractionProfile, text: str):
    return SafeAttachmentExtractionArtifact(
        name=metadata.name,
        content_profile=profile,
        extraction_kind="text",
        text=text,
        character_count=len(text),
        table_count=0,
        cell_count=0,
    )


def _table_artifact(metadata: InboundAttachmentMetadata, profile: AttachmentExtractionProfile, tables: list[SafeExtractedTable]):
    character_count = sum(
        len(cell)
        for table in tables
        for row in table.rows
        for cell in row
    )
    if character_count > MAX_EXTRACTED_CHARS_PER_FILE:
        raise AttachmentSafeExtractionError("attachment_extracted_text_exceeds_limit")
    return SafeAttachmentExtractionArtifact(
        name=metadata.name,
        content_profile=profile,
        extraction_kind="tables",
        tables=tables,
        character_count=character_count,
        table_count=len(tables),
        cell_count=sum(table.cell_count for table in tables),
    )


def _extract_pdf(metadata: InboundAttachmentMetadata, content: bytes | bytearray):
    try:
        reader = PdfReader(BytesIO(bytes(content)), strict=False)
        if reader.is_encrypted:
            raise AttachmentSafeExtractionError("attachment_pdf_encrypted_not_allowed")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise AttachmentSafeExtractionError("attachment_pdf_page_count_exceeds_limit")
        pieces: list[str] = []
        total = 0
        for page in reader.pages:
            page_text = page.extract_text() or ""
            total += len(page_text)
            if total > MAX_EXTRACTED_CHARS_PER_FILE:
                raise AttachmentSafeExtractionError("attachment_extracted_text_exceeds_limit")
            if page_text.strip():
                pieces.append(page_text)
    except AttachmentSafeExtractionError:
        raise
    except (PdfReadError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise AttachmentSafeExtractionError("attachment_pdf_extraction_failed") from exc
    text = _normalize_extracted_text("\n\n".join(pieces), empty_code="attachment_pdf_no_extractable_text")
    return _text_artifact(metadata, "pdf", text)


def _column_index(cell_ref: str | None, fallback: int) -> int:
    if not cell_ref:
        return fallback
    match = re.match(r"^([A-Z]+)[1-9][0-9]*$", cell_ref.upper())
    if not match:
        raise AttachmentSafeExtractionError("attachment_xlsx_cell_reference_invalid")
    value = 0
    for character in match.group(1):
        value = value * 26 + (ord(character) - ord("A") + 1)
    return value


def _read_zip_part(archive: ZipFile, name: str) -> bytes:
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise AttachmentSafeExtractionError("attachment_xlsx_structure_invalid") from exc
    if info.file_size > MAX_XLSX_XML_PART_BYTES:
        raise AttachmentSafeExtractionError("attachment_xlsx_xml_part_exceeds_limit")
    return archive.read(info)


def _shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    raw = _read_zip_part(archive, "xl/sharedStrings.xml")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise AttachmentSafeExtractionError("attachment_xlsx_xml_invalid") from exc
    values = []
    for si in root.findall("{*}si"):
        text = "".join(node.text or "" for node in si.iter() if node.tag.endswith("}t"))
        values.append(_normalize_cell(text))
        if sum(len(item) for item in values) > MAX_EXTRACTED_CHARS_PER_FILE:
            raise AttachmentSafeExtractionError("attachment_extracted_text_exceeds_limit")
    return values


def _xlsx_cell_value(cell, shared: list[str]) -> str:
    if cell.find("{*}f") is not None:
        raise AttachmentSafeExtractionError("attachment_xlsx_formula_present")
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        inline = cell.find("{*}is")
        if inline is None:
            return ""
        return _normalize_cell("".join(node.text or "" for node in inline.iter() if node.tag.endswith("}t")))
    value_node = cell.find("{*}v")
    value = "" if value_node is None or value_node.text is None else value_node.text
    if cell_type == "s" and value:
        try:
            index = int(value)
            value = shared[index]
        except (ValueError, IndexError) as exc:
            raise AttachmentSafeExtractionError("attachment_xlsx_shared_string_invalid") from exc
    return _normalize_cell(value)


def _extract_xlsx(metadata: InboundAttachmentMetadata, content: bytes | bytearray):
    try:
        with ZipFile(BytesIO(bytes(content))) as archive:
            worksheet_names = sorted(
                name for name in archive.namelist()
                if name.startswith("xl/worksheets/") and name.endswith(".xml") and "/_rels/" not in name
            )
            if not worksheet_names:
                raise AttachmentSafeExtractionError("attachment_xlsx_worksheet_missing")
            if len(worksheet_names) > MAX_XLSX_SHEETS:
                raise AttachmentSafeExtractionError("attachment_xlsx_sheet_count_exceeds_limit")
            relevant_names = list(worksheet_names)
            if "xl/sharedStrings.xml" in archive.namelist():
                relevant_names.append("xl/sharedStrings.xml")
            declared = sum(archive.getinfo(name).file_size for name in relevant_names)
            if declared > MAX_XLSX_RELEVANT_XML_BYTES:
                raise AttachmentSafeExtractionError("attachment_xlsx_relevant_xml_exceeds_limit")
            shared = _shared_strings(archive)
            tables: list[SafeExtractedTable] = []
            total_cells = 0
            for sheet_index, worksheet_name in enumerate(worksheet_names, start=1):
                raw = _read_zip_part(archive, worksheet_name)
                try:
                    root = ET.fromstring(raw)
                except ET.ParseError as exc:
                    raise AttachmentSafeExtractionError("attachment_xlsx_xml_invalid") from exc
                sparse_rows: dict[int, dict[int, str]] = {}
                max_column = 0
                for row_position, row in enumerate(root.findall(".//{*}sheetData/{*}row"), start=1):
                    row_number_raw = row.attrib.get("r")
                    try:
                        row_number = int(row_number_raw) if row_number_raw else row_position
                    except ValueError as exc:
                        raise AttachmentSafeExtractionError("attachment_xlsx_row_reference_invalid") from exc
                    if row_number > MAX_XLSX_ROWS_PER_SHEET:
                        raise AttachmentSafeExtractionError("attachment_xlsx_row_count_exceeds_limit")
                    cells: dict[int, str] = {}
                    fallback_column = 1
                    for cell in row.findall("{*}c"):
                        column = _column_index(cell.attrib.get("r"), fallback_column)
                        fallback_column = column + 1
                        if column > MAX_XLSX_COLUMNS:
                            raise AttachmentSafeExtractionError("attachment_xlsx_column_count_exceeds_limit")
                        value = _xlsx_cell_value(cell, shared)
                        if value:
                            cells[column] = value
                            total_cells += 1
                            if total_cells > MAX_TABLE_CELLS_PER_FILE:
                                raise AttachmentSafeExtractionError("attachment_table_cell_count_exceeds_limit")
                            max_column = max(max_column, column)
                    if cells:
                        sparse_rows[row_number] = cells
                if sparse_rows and max_column:
                    max_row = max(sparse_rows)
                    rows = [
                        [sparse_rows.get(row_number, {}).get(column, "") for column in range(1, max_column + 1)]
                        for row_number in range(1, max_row + 1)
                    ]
                    tables.append(SafeExtractedTable(
                        name=f"sheet{sheet_index}",
                        rows=rows,
                        row_count=len(rows),
                        column_count=max_column,
                        cell_count=sum(1 for row in rows for cell in row if cell),
                    ))
            if not tables:
                raise AttachmentSafeExtractionError("attachment_xlsx_no_extractable_cells")
            return _table_artifact(metadata, "xlsx", tables)
    except AttachmentSafeExtractionError:
        raise
    except BadZipFile as exc:
        raise AttachmentSafeExtractionError("attachment_xlsx_extraction_failed") from exc


def _detect_csv_delimiter(text: str) -> str:
    candidates = [",", ";", "\t", "|"]
    sample_lines = [line for line in text.splitlines()[:20] if line.strip()]
    if not sample_lines:
        return ","
    counts = {candidate: sum(line.count(candidate) for line in sample_lines) for candidate in candidates}
    return max(candidates, key=lambda candidate: counts[candidate]) if max(counts.values()) else ","


def _extract_csv(metadata: InboundAttachmentMetadata, content: bytes | bytearray):
    try:
        text = bytes(content).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AttachmentSafeExtractionError("attachment_csv_encoding_not_allowed") from exc
    if len(text) > MAX_EXTRACTED_CHARS_PER_FILE:
        raise AttachmentSafeExtractionError("attachment_extracted_text_exceeds_limit")
    delimiter = _detect_csv_delimiter(text)
    reader = csv.reader(StringIO(text, newline=""), delimiter=delimiter)
    rows: list[list[str]] = []
    max_columns = 0
    nonempty_cells = 0
    try:
        for row_index, raw_row in enumerate(reader, start=1):
            if row_index > MAX_CSV_ROWS:
                raise AttachmentSafeExtractionError("attachment_csv_row_count_exceeds_limit")
            if len(raw_row) > MAX_XLSX_COLUMNS:
                raise AttachmentSafeExtractionError("attachment_csv_column_count_exceeds_limit")
            normalized_row = [_normalize_cell(cell) for cell in raw_row]
            nonempty_cells += sum(1 for cell in normalized_row if cell)
            if nonempty_cells > MAX_TABLE_CELLS_PER_FILE:
                raise AttachmentSafeExtractionError("attachment_table_cell_count_exceeds_limit")
            max_columns = max(max_columns, len(normalized_row))
            rows.append(normalized_row)
    except csv.Error as exc:
        raise AttachmentSafeExtractionError("attachment_csv_parse_failed") from exc
    if not rows or max_columns == 0 or nonempty_cells == 0:
        raise AttachmentSafeExtractionError("attachment_csv_no_extractable_cells")
    dense_rows = [row + [""] * (max_columns - len(row)) for row in rows]
    table = SafeExtractedTable(
        name="csv",
        rows=dense_rows,
        row_count=len(dense_rows),
        column_count=max_columns,
        cell_count=nonempty_cells,
    )
    return _table_artifact(metadata, "csv", [table])


def extract_verified_attachment(
    metadata: InboundAttachmentMetadata,
    content: bytes | bytearray,
    *,
    expected_sha256_hex: str,
    expected_profile: AttachmentExtractionProfile,
) -> SafeAttachmentExtractionArtifact:
    """Extract bounded content only after P1-55 verification; never interprets business meaning."""

    if sha256(content).hexdigest() != expected_sha256_hex:
        raise AttachmentSafeExtractionError("attachment_extraction_digest_mismatch")
    extension = PurePath(metadata.name).suffix.lower()
    profile_by_extension = {".pdf": "pdf", ".xlsx": "xlsx", ".csv": "csv"}
    if profile_by_extension.get(extension) != expected_profile:
        raise AttachmentSafeExtractionError("attachment_extraction_profile_mismatch")
    if expected_profile == "pdf":
        return _extract_pdf(metadata, content)
    if expected_profile == "xlsx":
        return _extract_xlsx(metadata, content)
    return _extract_csv(metadata, content)
