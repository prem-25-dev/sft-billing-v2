"""Explicit, atomic persistence for a previously validated import preview."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.repositories.historical_import_repository import (
    HistoricalImportRepository,
)
from app.services.historical_import_preview import (
    HistoricalImportPreview,
    preview_historical_import,
)
from app.services.historical_reservation_parser import parse_historical_reservation


class HistoricalImportError(Exception):
    """Base error for a historical import that did not commit."""


class HistoricalImportValidationError(HistoricalImportError):
    """Raised when the preview is invalid, stale, or internally inconsistent."""


class HistoricalImportConflictError(HistoricalImportError):
    """Raised when any target key already exists; no records are overwritten."""

    def __init__(self, conflicts: tuple[dict[str, str], ...]) -> None:
        self.conflicts = conflicts
        details = ", ".join(
            f"{conflict['entity']}:{conflict['key']}" for conflict in conflicts
        )
        super().__init__(f"Historical import conflicts with existing records: {details}.")


@dataclass(frozen=True)
class HistoricalImportResult:
    source_sha256: str
    counts: dict[str, int]


def import_historical_preview(
    preview: HistoricalImportPreview,
    session_factory: sessionmaker[Session],
) -> HistoricalImportResult:
    """Atomically persist a validated preview using the supplied SQLite database.

    The caller must explicitly supply a session factory for an already-migrated
    SQLite database. This service never initializes schema or imports excluded
    domains. It has no route, startup hook, or production-database default.
    """
    if preview.errors:
        raise HistoricalImportValidationError(
            "Preview contains blocking errors; no records were written."
        )
    if not preview.is_valid or preview.commit_supported or preview.writes_performed:
        raise HistoricalImportValidationError(
            "The supplied object is not an uncommitted valid preview."
        )

    _verify_preview_is_current(preview)
    _validate_candidate_relationships(preview.records)

    with session_factory.begin() as session:
        if session.get_bind().dialect.name != "sqlite":
            raise HistoricalImportValidationError(
                "Historical import requires an explicitly supplied SQLite database."
            )

        repository = HistoricalImportRepository(session)
        repository.assert_import_schema_ready()
        conflicts = repository.find_existing_conflicts(preview.records)
        if conflicts:
            raise HistoricalImportConflictError(conflicts)

        repository.add_clients(preview.records["clients"])
        repository.add_invoices(preview.records["invoices"])
        repository.add_invoice_items(preview.records["invoiceItems"])
        repository.add_reservations(preview.records["reservations"])
        repository.assert_foreign_key_integrity()

    return HistoricalImportResult(
        source_sha256=preview.source_sha256,
        counts=dict(preview.counts),
    )


def _verify_preview_is_current(preview: HistoricalImportPreview) -> None:
    try:
        current = preview_historical_import(Path(preview.source_path))
    except (OSError, ValueError) as exc:
        raise HistoricalImportValidationError(
            "The source workbook could not be revalidated; no records were written."
        ) from exc

    if (
        not current.is_valid
        or current.source_sha256 != preview.source_sha256
        or current.records != preview.records
        or current.counts != preview.counts
        or current.errors != preview.errors
        or current.warnings != preview.warnings
    ):
        raise HistoricalImportValidationError(
            "The preview is stale or has changed since validation; no records were written."
        )


def _validate_candidate_relationships(
    records: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    client_ids = {record.get("id") for record in records["clients"]}
    invoice_ids = {record.get("id") for record in records["invoices"]}
    invoice_numbers = {record.get("number") for record in records["invoices"]}
    reservation_numbers: set[str] = set()

    for invoice in records["invoices"]:
        if invoice.get("clientId") not in client_ids:
            raise HistoricalImportValidationError(
                f"Invoice {invoice.get('id')!r} references a Client not in the preview."
            )
    for item in records["invoiceItems"]:
        if item.get("invoiceId") not in invoice_ids:
            raise HistoricalImportValidationError(
                f"Invoice item {item.get('id')!r} references an Invoice not in the preview."
            )
    for reservation in records["reservations"]:
        number = reservation.get("number")
        if not isinstance(number, str):
            raise HistoricalImportValidationError(
                "A reservation has no valid invoice number."
            )
        try:
            parsed = parse_historical_reservation(number)
        except ValueError as exc:
            raise HistoricalImportValidationError(
                f"Invalid historical reservation number {number!r}."
            ) from exc
        if (
            reservation.get("financialYear") != parsed.financial_year
            or reservation.get("sequence") != parsed.sequence
        ):
            raise HistoricalImportValidationError(
                f"Reservation {number!r} does not match its invoice-number-derived values."
            )
        if number in reservation_numbers:
            raise HistoricalImportValidationError(
                f"Duplicate reservation number {number!r}."
            )
        reservation_numbers.add(number)

    if not invoice_numbers.issubset(reservation_numbers):
        raise HistoricalImportValidationError(
            "Every imported invoice number must have a matching reservation."
        )
