"""Generic sheet <-> list[dict] helpers used by every service.

A "row" here is always a plain dict keyed by the sheet's header names —
services never touch openpyxl cell objects directly.  Payment proof is the
one storage-specific exception: its five workbook columns are exposed as the
nested ``paymentProof`` metadata object used by the payment contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
import math
from typing import Any

from openpyxl.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from app.excel.constants import (
    HEADERS_BY_SHEET,
    PAYMENT_PROOF_HEADER_TO_FIELD,
    PAYMENT_PROOF_HEADERS,
    SHEET_PAYMENTS,
)

PAYMENT_PROOF_UNAVAILABLE_KEY = "proofUnavailable"


def _cell_to_value(value: Any) -> Any:
    """Normalize openpyxl date values to plain serializable values."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _header_positions(ws: Worksheet, sheet_name: str) -> dict[str, int]:
    """Return the actual worksheet column for each known header.

    Existing workbooks can have headers appended during migration, so using
    the canonical header list as positional indexes would misread a workbook
    whose columns were preserved in a different order.  The header row is the
    source of truth for the physical column positions.
    """
    expected_headers = set(HEADERS_BY_SHEET[sheet_name])
    positions: dict[str, int] = {}
    for column_index in range(1, ws.max_column + 1):
        header = ws.cell(row=1, column=column_index).value
        if isinstance(header, str) and header in expected_headers and header not in positions:
            positions[header] = column_index
    return positions


def _is_blank(value: Any) -> bool:
    return value is None or value == ""


def _valid_size(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    numeric_value = float(value)
    return math.isfinite(numeric_value) and numeric_value >= 0 and numeric_value.is_integer()


def _parse_payment_proof(
    storage_values: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, bool]:
    """Deserialize the five proof cells.

    The second return value identifies malformed/partial metadata.  Such a
    row remains a valid payment row, but its proof is explicitly unavailable;
    no missing field is guessed or reconstructed from the remaining cells.
    """
    if all(_is_blank(storage_values.get(header)) for header in PAYMENT_PROOF_HEADERS):
        return None, False

    file_name = storage_values.get("proof_fileName")
    mime_type = storage_values.get("proof_mimeType")
    size_bytes = storage_values.get("proof_sizeBytes")
    uploaded_at = storage_values.get("proof_uploadedAt")
    attachment_reference = storage_values.get("proof_attachmentReference")

    if (
        not isinstance(file_name, str)
        or not file_name
        or not isinstance(mime_type, str)
        or not mime_type
        or not _valid_size(size_bytes)
        or not isinstance(uploaded_at, str)
        or not uploaded_at
        or not isinstance(attachment_reference, str)
        or not attachment_reference
    ):
        return None, True

    return {
        "fileName": file_name,
        "mimeType": mime_type,
        "sizeBytes": int(size_bytes),
        "uploadedAt": uploaded_at,
        "attachmentReference": attachment_reference,
    }, False


def _proof_storage_values(proof: Any) -> dict[str, Any]:
    """Validate and serialize a nested paymentProof value.

    ``None`` is the intentional no-proof state and writes five blank cells.
    A partially populated object is rejected instead of being serialized as a
    misleading proof record.
    """
    if proof is None:
        return {header: None for header in PAYMENT_PROOF_HEADERS}
    if not isinstance(proof, Mapping):
        raise ValueError("paymentProof must be a mapping or None")

    storage_values = {
        header: proof.get(field_name)
        for header, field_name in PAYMENT_PROOF_HEADER_TO_FIELD.items()
    }
    parsed, unavailable = _parse_payment_proof(storage_values)
    if unavailable or parsed is None:
        raise ValueError("paymentProof metadata must contain all five valid fields")

    return {
        "proof_fileName": parsed["fileName"],
        "proof_mimeType": parsed["mimeType"],
        "proof_sizeBytes": parsed["sizeBytes"],
        "proof_uploadedAt": parsed["uploadedAt"],
        "proof_attachmentReference": parsed["attachmentReference"],
    }


def _row_values(row: Mapping[str, Any], sheet_name: str) -> dict[str, Any]:
    values = {header: row.get(header) for header in HEADERS_BY_SHEET[sheet_name]}
    if sheet_name == SHEET_PAYMENTS:
        values.update(_proof_storage_values(row.get("paymentProof")))
    return values


def _read_storage_row(
    ws: Worksheet,
    sheet_name: str,
    excel_row: tuple[Any, ...],
) -> dict[str, Any]:
    positions = _header_positions(ws, sheet_name)
    row: dict[str, Any] = {}
    for header in HEADERS_BY_SHEET[sheet_name]:
        column_index = positions.get(header)
        value = excel_row[column_index - 1] if column_index is not None and column_index <= len(excel_row) else None
        row[header] = _cell_to_value(value)
    return row


def _to_domain_row(
    row: dict[str, Any],
    sheet_name: str,
) -> dict[str, Any]:
    if sheet_name != SHEET_PAYMENTS:
        return row

    storage_values = {header: row.pop(header, None) for header in PAYMENT_PROOF_HEADERS}
    payment_proof, unavailable = _parse_payment_proof(storage_values)
    row["paymentProof"] = payment_proof
    if unavailable:
        row[PAYMENT_PROOF_UNAVAILABLE_KEY] = True
    return row


def read_rows(ws: Worksheet, sheet_name: str) -> list[dict[str, Any]]:
    """Read every non-blank data row using the worksheet's actual headers."""
    rows: list[dict[str, Any]] = []
    for excel_row in ws.iter_rows(min_row=2, values_only=True):
        if excel_row is None or all(_is_blank(value) for value in excel_row):
            continue
        rows.append(_to_domain_row(_read_storage_row(ws, sheet_name, excel_row), sheet_name))
    return rows


def append_row(ws: Worksheet, sheet_name: str, row: dict[str, Any]) -> None:
    """Append a domain row without assuming a physical column order."""
    positions = _header_positions(ws, sheet_name)
    values = _row_values(row, sheet_name)
    excel_row_num = ws.max_row + 1
    for header, column_index in positions.items():
        ws.cell(row=excel_row_num, column=column_index, value=values[header])


def find_row_index(ws: Worksheet, sheet_name: str, id_column: str, id_value: str) -> int | None:
    """Return the 1-based worksheet row for an id, or ``None`` when absent."""
    id_column_index = _header_positions(ws, sheet_name).get(id_column)
    if id_column_index is None:
        return None
    for excel_row_num, excel_row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if excel_row is None:
            continue
        value = excel_row[id_column_index - 1] if id_column_index <= len(excel_row) else None
        if value == id_value:
            return excel_row_num
    return None


def write_row(ws: Worksheet, sheet_name: str, excel_row_num: int, row: dict[str, Any]) -> None:
    """Write a domain row to an existing worksheet row."""
    positions = _header_positions(ws, sheet_name)
    values = _row_values(row, sheet_name)
    for header, column_index in positions.items():
        ws.cell(row=excel_row_num, column=column_index, value=values[header])


def update_payment_proof(
    ws: Worksheet,
    payment_id: str,
    payment_proof: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Atomically enrich one existing payment row with proof metadata.

    The helper changes only the five proof cells on the matching payment row;
    it never appends a row.  Cell values are restored if a write fails before
    the caller saves the workbook, preventing a partial in-memory enrichment.
    """
    proof_values = _proof_storage_values(payment_proof)
    positions = _header_positions(ws, SHEET_PAYMENTS)
    missing_headers = [header for header in PAYMENT_PROOF_HEADERS if header not in positions]
    if missing_headers:
        raise ValueError(
            "Payment proof headers are missing; load the workbook through the migration path first."
        )

    excel_row_num = find_row_index(ws, SHEET_PAYMENTS, "id", payment_id)
    if excel_row_num is None:
        raise KeyError(f"Payment {payment_id} not found")

    previous_values = {
        header: ws.cell(row=excel_row_num, column=positions[header]).value
        for header in PAYMENT_PROOF_HEADERS
    }
    try:
        for header in PAYMENT_PROOF_HEADERS:
            ws.cell(row=excel_row_num, column=positions[header], value=proof_values[header])
    except Exception:
        for header, value in previous_values.items():
            ws.cell(row=excel_row_num, column=positions[header], value=value)
        raise

    for row in read_rows(ws, SHEET_PAYMENTS):
        if row.get("id") == payment_id:
            return row
    raise KeyError(f"Payment {payment_id} not found")


def delete_row(ws: Worksheet, excel_row_num: int) -> None:
    ws.delete_rows(excel_row_num, 1)


def get_sheet(wb: Workbook, sheet_name: str) -> Worksheet:
    return wb[sheet_name]
