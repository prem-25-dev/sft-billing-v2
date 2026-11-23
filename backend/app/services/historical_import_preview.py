"""Read-only validation and mapping preview for legacy workbook records.

This module deliberately has no database or workbook-writing dependencies.
Its output is a proposal only; it does not persist or reserve any data.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from openpyxl import load_workbook

from app.services.calculation_service import compute_invoice_totals
from app.services.historical_reservation_parser import (
    ParsedHistoricalReservation,
    parse_historical_reservation,
)
from app.utils.validators import is_valid_email, is_valid_gstin, is_valid_iso_date

Severity = Literal["error", "warning"]

_CLIENT_FIELDS = (
    "id",
    "name",
    "contactName",
    "email",
    "phone",
    "billingAddress",
    "gstin",
    "pan",
    "notes",
)
_INVOICE_FIELDS = (
    "id",
    "number",
    "clientId",
    "issueDate",
    "dueDate",
    "cgstRate",
    "sgstRate",
    "discount",
    "roundOff",
    "notes",
    "terms",
    "supplierCode",
    "poNumber",
    "poDate",
    "transporter",
    "isDraft",
    "sentAt",
    "viewedAt",
    "paidAt",
    "cancelledAt",
    "billedAt",
)
_INVOICE_SNAPSHOT_FIELDS = (
    "customerNameSnapshot",
    "customerAddressSnapshot",
    "customerPhoneSnapshot",
    "customerEmailSnapshot",
    "customerGstinSnapshot",
    "customerPanSnapshot",
    "businessNameSnapshot",
    "businessLogoUrlSnapshot",
    "businessAddressSnapshot",
    "businessPhoneSnapshot",
    "businessEmailSnapshot",
    "businessGstinSnapshot",
    "businessPanSnapshot",
    "businessBankAccountHolderSnapshot",
    "businessBankNameSnapshot",
    "businessBankBranchSnapshot",
    "businessBankAccountNumberSnapshot",
    "businessBankIfscSnapshot",
    "businessDeclarationSnapshot",
    "authorizedSignatureReferenceSnapshot",
)
_ITEM_FIELDS = (
    "id",
    "invoiceId",
    "productId",
    "description",
    "hsnCode",
    "quantity",
    "unitPrice",
)
_RESERVATION_FIELDS = (
    "number",
    "financialYear",
    "sequence",
    "reservedFor",
    "reservedAt",
)
_SHEETS: dict[str, tuple[str, tuple[str, ...]]] = {
    "clients": ("Clients", _CLIENT_FIELDS),
    "invoices": ("Invoices", _INVOICE_FIELDS),
    "invoiceItems": ("InvoiceItems", _ITEM_FIELDS),
    "reservations": ("InvoiceNumberReservations", _RESERVATION_FIELDS),
}
_TOTAL_COLUMN_MAP = {
    "subtotal": "subtotal",
    "taxablevalue": "taxableValue",
    "cgstamount": "cgstAmount",
    "sgstamount": "sgstAmount",
    "total": "total",
    "grandtotal": "total",
}


@dataclass(frozen=True)
class PreviewFinding:
    severity: Severity
    entity: str
    source_row: int | None
    field: str | None
    message: str
    source_value: Any = None


@dataclass(frozen=True)
class HistoricalImportPreview:
    source_path: str
    source_sha256: str
    records: dict[str, tuple[dict[str, Any], ...]]
    counts: dict[str, int]
    errors: tuple[PreviewFinding, ...]
    warnings: tuple[PreviewFinding, ...]
    missing_values: dict[str, int]
    reservation_mismatches: tuple[dict[str, Any], ...]
    reservation_usage: dict[str, str]
    calculated_totals: dict[str, dict[str, Any]]
    total_discrepancies: tuple[dict[str, Any], ...]
    excluded_source_counts: dict[str, int]
    writes_performed: int = 0
    commit_supported: bool = False

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly report without altering the preview."""
        return {
            "sourcePath": self.source_path,
            "sourceSha256": self.source_sha256,
            "records": self.records,
            "counts": self.counts,
            "errors": [asdict(finding) for finding in self.errors],
            "warnings": [asdict(finding) for finding in self.warnings],
            "missingValues": self.missing_values,
            "reservationMismatches": self.reservation_mismatches,
            "reservationUsage": self.reservation_usage,
            "calculatedTotals": self.calculated_totals,
            "totalDiscrepancies": self.total_discrepancies,
            "excludedSourceCounts": self.excluded_source_counts,
            "writesPerformed": self.writes_performed,
            "commitSupported": self.commit_supported,
            "isValid": self.is_valid,
        }


def preview_historical_import(
    workbook_path: str | Path,
) -> HistoricalImportPreview:
    """Read a workbook and return validated target-shaped candidates only."""
    path = Path(workbook_path).expanduser().resolve()
    initial_hash = _file_sha256(path)
    findings: list[PreviewFinding] = []
    missing_values: dict[str, int] = {}

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        total_headers: dict[str, str] = {}
        for entity, (sheet_name, fields) in _SHEETS.items():
            if sheet_name not in workbook.sheetnames:
                findings.append(
                    PreviewFinding(
                        "error", entity, None, None,
                        f"Required worksheet {sheet_name!r} is missing.",
                    )
                )
                sheets[entity] = []
                continue

            worksheet = workbook[sheet_name]
            row_iter = worksheet.iter_rows(values_only=True)
            header_row = next(row_iter, ())
            headers = {
                str(value).strip(): index
                for index, value in enumerate(header_row)
                if value is not None and str(value).strip()
            }
            header_lookup = {name.casefold(): index for name, index in headers.items()}
            for required_header in _required_headers(entity):
                if required_header.casefold() not in header_lookup:
                    findings.append(
                        PreviewFinding(
                            "error", entity, 1, required_header,
                            f"Required source column {required_header!r} is missing.",
                        )
                    )

            if entity == "invoices":
                total_headers = {
                    _TOTAL_COLUMN_MAP[name.casefold()]: name
                    for name in headers
                    if name.casefold() in _TOTAL_COLUMN_MAP
                }

            mapped_rows: list[tuple[int, dict[str, Any]]] = []
            for source_row, values in enumerate(row_iter, start=2):
                if not any(value is not None and value != "" for value in values):
                    continue
                record: dict[str, Any] = {}
                for field in fields:
                    index = header_lookup.get(field.casefold())
                    value = values[index] if index is not None and index < len(values) else None
                    record[field] = _target_value(value)
                    if value is None or value == "" or (
                        isinstance(value, str) and not value.strip()
                    ):
                        missing_key = f"{entity}.{field}"
                        missing_values[missing_key] = missing_values.get(missing_key, 0) + 1
                if entity == "invoices":
                    record["_sourceTotals"] = {
                        target_field: _target_value(
                            values[header_lookup[header.casefold()]]
                        )
                        for target_field, header in total_headers.items()
                        if header.casefold() in header_lookup
                        and header_lookup[header.casefold()] < len(values)
                    }
                if entity == "clients":
                    client_since_index = header_lookup.get("clientsince")
                    record["_clientSincePresent"] = (
                        client_since_index is not None
                        and client_since_index < len(values)
                        and values[client_since_index] not in (None, "")
                    )
                record["_sourceRow"] = source_row
                mapped_rows.append((source_row, record))
            sheets[entity] = mapped_rows

        _validate_clients(sheets["clients"], findings)
        _validate_invoices(sheets["invoices"], findings)
        _validate_items(sheets["invoiceItems"], findings)
        parsed_reservations, mismatches = _validate_reservations(
            sheets["reservations"], findings
        )
        parsed_by_row = {
            source_row: parsed
            for source_row, parsed, _ in parsed_reservations
        }
        records: dict[str, tuple[dict[str, Any], ...]] = {}
        for entity, rows in sheets.items():
            mapped_records: list[dict[str, Any]] = []
            for source_row, record in rows:
                candidate = {
                    key: value
                    for key, value in record.items()
                    if not key.startswith("_")
                }
                if entity == "reservations" and source_row in parsed_by_row:
                    parsed = parsed_by_row[source_row]
                    candidate["number"] = parsed.number
                    candidate["financialYear"] = parsed.financial_year
                    candidate["sequence"] = parsed.sequence
                elif entity == "reservations":
                    candidate["financialYear"] = None
                    candidate["sequence"] = None
                if entity == "invoices":
                    candidate.update({field: None for field in _INVOICE_SNAPSHOT_FIELDS})
                mapped_records.append(candidate)
            records[entity] = tuple(mapped_records)
        _validate_duplicate_keys("clients", sheets["clients"], ("id",), findings)
        _validate_duplicate_keys("invoices", sheets["invoices"], ("id", "number"), findings)
        _validate_duplicate_keys("invoiceItems", sheets["invoiceItems"], ("id",), findings)
        _validate_duplicate_keys("reservations", sheets["reservations"], ("number",), findings)
        _validate_reservation_uniqueness(parsed_reservations, findings)
        _validate_references(sheets, parsed_reservations, findings)
        calculated_totals, discrepancies = _calculate_totals(
            sheets["invoices"], sheets["invoiceItems"], total_headers, findings
        )

        client_since_count = sum(
            1
            for _, record in sheets["clients"]
            if record.get("_clientSincePresent")
        )
        if client_since_count:
            findings.append(
                PreviewFinding(
                    "warning",
                    "clients",
                    None,
                    "clientSince",
                    f"{client_since_count} populated source value(s) are intentionally unmapped.",
                )
            )

        excluded_source_counts = {
            "payments": _count_data_rows(workbook, "Payments"),
            "activities": _count_data_rows(workbook, "Activities"),
        }
        for entity, count in excluded_source_counts.items():
            if count:
                findings.append(
                    PreviewFinding(
                        "warning",
                        entity,
                        None,
                        None,
                        f"{count} source record(s) are excluded; this preview does not import {entity}.",
                    )
                )

        if not total_headers:
            findings.append(
                PreviewFinding(
                    "warning",
                    "invoices",
                    None,
                    None,
                    "The workbook has no stored subtotal, tax, or total columns; calculated totals are shown without source-total comparison.",
                )
            )
    finally:
        workbook.close()

    final_hash = _file_sha256(path)
    if final_hash != initial_hash:
        findings.append(
            PreviewFinding(
                "error",
                "workbook",
                None,
                None,
                "Source workbook changed while the preview was being read.",
            )
        )

    errors = tuple(finding for finding in findings if finding.severity == "error")
    warnings = tuple(finding for finding in findings if finding.severity == "warning")
    counts = {entity: len(entity_records) for entity, entity_records in records.items()}
    invoice_numbers = {record.get("number") for record in records["invoices"]}
    reservation_usage = {
        record["number"]: (
            "linked_to_invoice"
            if record["number"] in invoice_numbers
            else "unused_reservation"
        )
        for record in records["reservations"]
    }
    return HistoricalImportPreview(
        source_path=str(path),
        source_sha256=final_hash,
        records=records,
        counts=counts,
        errors=errors,
        warnings=warnings,
        missing_values=missing_values,
        reservation_mismatches=tuple(mismatches),
        reservation_usage=reservation_usage,
        calculated_totals=calculated_totals,
        total_discrepancies=tuple(discrepancies),
        excluded_source_counts=excluded_source_counts,
    )


def _required_headers(entity: str) -> tuple[str, ...]:
    if entity == "clients":
        return ("id", "name", "billingAddress", "gstin")
    if entity == "invoices":
        return (
            "id", "number", "clientId", "issueDate", "dueDate",
            "cgstRate", "sgstRate", "discount", "roundOff", "isDraft",
        )
    if entity == "invoiceItems":
        return ("id", "invoiceId", "description", "quantity", "unitPrice")
    return ("number", "financialYear", "sequence", "reservedAt")


def _target_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finding(
    findings: list[PreviewFinding],
    severity: Severity,
    entity: str,
    source_row: int | None,
    field: str | None,
    message: str,
    source_value: Any = None,
) -> None:
    findings.append(
        PreviewFinding(severity, entity, source_row, field, message, source_value)
    )


def _valid_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _validate_clients(
    rows: list[tuple[int, dict[str, Any]]], findings: list[PreviewFinding]
) -> None:
    for source_row, row in rows:
        for field in ("id", "name", "billingAddress", "gstin"):
            if not _valid_text(row.get(field)):
                _finding(findings, "error", "clients", source_row, field, f"{field} is required.", row.get(field))
        if _valid_text(row.get("gstin")) and not is_valid_gstin(row["gstin"]):
            _finding(findings, "error", "clients", source_row, "gstin", "GSTIN format is invalid.", row["gstin"])
        email = row.get("email")
        if email is not None and not isinstance(email, str):
            _finding(findings, "error", "clients", source_row, "email", "Email must be text or blank.", email)
        elif email and not is_valid_email(email.strip()):
            _finding(findings, "error", "clients", source_row, "email", "Email format is invalid.", email)
        for field in ("contactName", "phone", "pan", "notes"):
            if row.get(field) is not None and not isinstance(row[field], str):
                _finding(findings, "error", "clients", source_row, field, f"{field} must be text or blank.", row[field])


def _validate_invoices(
    rows: list[tuple[int, dict[str, Any]]], findings: list[PreviewFinding]
) -> None:
    for source_row, row in rows:
        for field in ("id", "number", "clientId", "issueDate", "dueDate"):
            if not _valid_text(row.get(field)):
                _finding(findings, "error", "invoices", source_row, field, f"{field} is required.", row.get(field))
        for field in ("issueDate", "dueDate"):
            value = row.get(field)
            if _valid_text(value) and not is_valid_iso_date(value):
                _finding(findings, "error", "invoices", source_row, field, "Date must be a valid ISO date.", value)
        for field in ("cgstRate", "sgstRate"):
            value = _number(row.get(field))
            if value is None or not 0 <= value <= 1:
                _finding(findings, "error", "invoices", source_row, field, "GST rate must be a finite number between 0 and 1.", row.get(field))
        for field in ("discount", "roundOff"):
            value = _number(row.get(field))
            if value is None or (field == "discount" and value < 0):
                _finding(findings, "error", "invoices", source_row, field, "Must be a finite monetary number; discount cannot be negative.", row.get(field))
        if not isinstance(row.get("isDraft"), bool):
            _finding(findings, "error", "invoices", source_row, "isDraft", "isDraft must be an Excel boolean.", row.get("isDraft"))


def _validate_items(
    rows: list[tuple[int, dict[str, Any]]], findings: list[PreviewFinding]
) -> None:
    for source_row, row in rows:
        for field in ("id", "invoiceId", "description"):
            if not _valid_text(row.get(field)):
                _finding(findings, "error", "invoiceItems", source_row, field, f"{field} is required.", row.get(field))
        quantity = _number(row.get("quantity"))
        if quantity is None or quantity <= 0:
            _finding(findings, "error", "invoiceItems", source_row, "quantity", "Quantity must be a finite number greater than zero.", row.get("quantity"))
        unit_price = _number(row.get("unitPrice"))
        if unit_price is None or unit_price < 0:
            _finding(findings, "error", "invoiceItems", source_row, "unitPrice", "Unit price must be a finite non-negative number.", row.get("unitPrice"))
        for field in ("productId", "hsnCode"):
            if row.get(field) is not None and not isinstance(row[field], str):
                _finding(findings, "error", "invoiceItems", source_row, field, f"{field} must be text or blank.", row[field])


def _validate_reservations(
    rows: list[tuple[int, dict[str, Any]]],
    findings: list[PreviewFinding],
) -> tuple[list[tuple[int, ParsedHistoricalReservation, dict[str, Any]]], list[dict[str, Any]]]:
    parsed_rows: list[tuple[int, ParsedHistoricalReservation, dict[str, Any]]] = []
    mismatches: list[dict[str, Any]] = []
    for source_row, row in rows:
        if not _valid_text(row.get("reservedAt")):
            _finding(findings, "error", "reservations", source_row, "reservedAt", "reservedAt is required.", row.get("reservedAt"))
        elif not is_valid_iso_date(row["reservedAt"]):
            _finding(findings, "error", "reservations", source_row, "reservedAt", "reservedAt must be an ISO timestamp.", row["reservedAt"])
        try:
            parsed = parse_historical_reservation(
                row.get("number"),
                source_financial_year=row.get("financialYear"),
                source_sequence=row.get("sequence"),
            )
        except ValueError as exc:
            _finding(findings, "error", "reservations", source_row, "number", str(exc), row.get("number"))
            continue
        parsed_rows.append((source_row, parsed, row))
        for field in ("financialYear", "sequence"):
            if row.get(field) is None:
                _finding(
                    findings, "warning", "reservations", source_row, field,
                    "Source value is blank; the invoice-number-derived value will be used.",
                )
        for mismatch in parsed.source_mismatches:
            report = {
                "sourceRow": source_row,
                "number": parsed.number,
                "field": mismatch.field,
                "sourceValue": mismatch.source_value,
                "derivedValue": mismatch.derived_value,
            }
            mismatches.append(report)
            _finding(
                findings, "warning", "reservations", source_row, mismatch.field,
                "Source field disagrees with the invoice-number-derived value; the derived value is authoritative.",
                mismatch.source_value,
            )
        reserved_for = row.get("reservedFor")
        if reserved_for is not None and not isinstance(reserved_for, str):
            _finding(findings, "error", "reservations", source_row, "reservedFor", "reservedFor must be text or blank.", reserved_for)
    return parsed_rows, mismatches


def _validate_duplicate_keys(
    entity: str,
    rows: list[tuple[int, dict[str, Any]]],
    fields: tuple[str, ...],
    findings: list[PreviewFinding],
) -> None:
    for field in fields:
        seen: dict[str, int] = {}
        for source_row, record in rows:
            value = record.get(field)
            if value is None or value == "":
                continue
            key = str(value)
            if key in seen:
                _finding(
                    findings, "error", entity, source_row, field,
                    f"Duplicate {field}; first seen on source row {seen[key]}.", value,
                )
            else:
                seen[key] = source_row


def _validate_reservation_uniqueness(
    rows: list[tuple[int, ParsedHistoricalReservation, dict[str, Any]]],
    findings: list[PreviewFinding],
) -> None:
    seen_sequences: dict[tuple[str, int], int] = {}
    seen_owners: dict[str, int] = {}
    for source_row, parsed, record in rows:
        sequence_key = (parsed.financial_year, parsed.sequence)
        if sequence_key in seen_sequences:
            _finding(
                findings, "error", "reservations", source_row, "sequence",
                f"Duplicate derived financial-year/sequence; first seen on source row {seen_sequences[sequence_key]}.",
                sequence_key,
            )
        else:
            seen_sequences[sequence_key] = source_row
        owner = record.get("reservedFor")
        if owner:
            if owner in seen_owners:
                _finding(
                    findings, "error", "reservations", source_row, "reservedFor",
                    f"Duplicate reservation owner; first seen on source row {seen_owners[owner]}.",
                    owner,
                )
            else:
                seen_owners[owner] = source_row


def _validate_references(
    sheets: dict[str, list[tuple[int, dict[str, Any]]]],
    reservations: list[tuple[int, ParsedHistoricalReservation, dict[str, Any]]],
    findings: list[PreviewFinding],
) -> None:
    clients = {row.get("id") for _, row in sheets["clients"] if row.get("id")}
    invoices = {row.get("id"): row for _, row in sheets["invoices"] if row.get("id")}
    invoice_numbers = {row.get("number") for _, row in sheets["invoices"]}
    reserved_numbers = {parsed.number for _, parsed, _ in reservations}
    item_invoice_ids = {
        row.get("invoiceId") for _, row in sheets["invoiceItems"] if row.get("invoiceId")
    }

    for source_row, invoice in sheets["invoices"]:
        client_id = invoice.get("clientId")
        if client_id and client_id not in clients:
            _finding(findings, "error", "invoices", source_row, "clientId", "Invoice references a missing Client.", client_id)
        number = invoice.get("number")
        if number and number not in reserved_numbers:
            _finding(findings, "error", "invoices", source_row, "number", "Invoice number has no matching historical reservation.", number)
        invoice_id = invoice.get("id")
        if invoice_id and invoice_id not in item_invoice_ids:
            _finding(findings, "error", "invoices", source_row, "items", "Invoice must contain at least one line item.")

    for source_row, item in sheets["invoiceItems"]:
        invoice_id = item.get("invoiceId")
        if invoice_id and invoice_id not in invoices:
            _finding(findings, "error", "invoiceItems", source_row, "invoiceId", "Invoice item references a missing Invoice.", invoice_id)

    for source_row, parsed, reservation in reservations:
        owner = reservation.get("reservedFor")
        if not owner:
            continue
        if owner not in invoices:
            _finding(
                findings, "warning", "reservations", source_row, "reservedFor",
                "Reservation owner does not resolve to an imported invoice; preserve the source value as unresolved metadata.",
                owner,
            )
        elif invoices[owner].get("number") != parsed.number:
            _finding(
                findings, "error", "reservations", source_row, "reservedFor",
                "Reservation owner resolves to an Invoice with a different invoice number.",
                owner,
            )

    missing_reservations = invoice_numbers - reserved_numbers
    for number in sorted(missing_reservations):
        _finding(findings, "error", "invoices", None, "number", "Invoice number is not protected by a historical reservation.", number)


def _calculate_totals(
    invoice_rows: list[tuple[int, dict[str, Any]]],
    item_rows: list[tuple[int, dict[str, Any]]],
    source_total_headers: dict[str, str],
    findings: list[PreviewFinding],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    items_by_invoice: dict[str, list[dict[str, Any]]] = {}
    for _, item in item_rows:
        invoice_id = item.get("invoiceId")
        if invoice_id:
            items_by_invoice.setdefault(invoice_id, []).append(item)

    calculated: dict[str, dict[str, Any]] = {}
    discrepancies: list[dict[str, Any]] = []
    for source_row, invoice in invoice_rows:
        invoice_id = invoice.get("id")
        if not invoice_id:
            continue
        invoice_items = items_by_invoice.get(invoice_id, [])
        values = [
            _number(invoice.get("cgstRate")),
            _number(invoice.get("sgstRate")),
            _number(invoice.get("discount")),
            _number(invoice.get("roundOff")),
        ]
        if any(value is None for value in values) or any(
            _number(item.get("quantity")) is None
            or _number(item.get("unitPrice")) is None
            for item in invoice_items
        ):
            continue
        try:
            totals = compute_invoice_totals(
                items=invoice_items,
                cgst_rate=values[0] or 0,
                sgst_rate=values[1] or 0,
                discount=values[2] or 0,
                round_off=values[3] or 0,
            )
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            _finding(
                findings, "error", "invoices", source_row, "totals",
                f"Could not calculate totals using the application calculation service: {exc}",
            )
            continue
        calculated[invoice_id] = totals
        for field, source_header in source_total_headers.items():
            if source_header.casefold() not in {
                "subtotal", "taxablevalue", "cgstamount", "sgstamount", "total", "grandtotal"
            }:
                continue
            source_value = invoice.get("_sourceTotals", {}).get(field)
            if source_value is None:
                continue
            source_number = _number(source_value)
            expected = totals[field]
            if source_number is None:
                discrepancies.append({
                    "invoiceId": invoice_id,
                    "sourceRow": source_row,
                    "field": source_header,
                    "sourceValue": source_value,
                    "calculatedValue": expected,
                    "reason": "Stored source total is not a finite number.",
                })
            elif _money_decimal(source_number) != _money_decimal(expected):
                discrepancies.append({
                    "invoiceId": invoice_id,
                    "sourceRow": source_row,
                    "field": source_header,
                    "sourceValue": source_value,
                    "calculatedValue": expected,
                    "reason": "Stored source total differs from the application calculation.",
                })
        for discrepancy in [d for d in discrepancies if d["invoiceId"] == invoice_id]:
            _finding(
                findings, "warning", "invoices", source_row, discrepancy["field"],
                discrepancy["reason"], discrepancy["sourceValue"],
            )
    return calculated, discrepancies


def _money_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _count_data_rows(workbook: Any, sheet_name: str) -> int:
    if sheet_name not in workbook.sheetnames:
        return 0
    rows = workbook[sheet_name].iter_rows(min_row=2, values_only=True)
    return sum(1 for row in rows if any(value is not None and value != "" for value in row))
