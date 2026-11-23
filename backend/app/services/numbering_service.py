"""Invoice-number business rules and legacy workbook reservation helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

from openpyxl.workbook import Workbook
from sqlalchemy.exc import IntegrityError

from app.excel.constants import SHEET_INVOICE_NUMBER_RESERVATIONS
from app.excel.rows import append_row, read_rows
from app.repositories.invoice_number_repository import (
    InvoiceNumberRepository,
    invoice_number_repository,
)
from app.services.legacy_excel_numbering import (
    LegacyReservationLookup,
    legacy_reservation_lookup,
)

_MAX_RESERVATION_ATTEMPTS = 1000


def financial_year(value: date) -> str:
    if value.month >= 4:
        return f"{value.year}-{str(value.year + 1)[-2:]}"
    return f"{value.year - 1}-{str(value.year)[-2:]}"


def get_reserved_invoice_number(
    reserved_for: str, repository: InvoiceNumberRepository | None = None
) -> str | None:
    reservation = (repository or invoice_number_repository).get_by_owner(reserved_for)
    return reservation["number"] if reservation is not None else None


def reserve_invoice_number(
    reserved_for: str | None = None,
    at_date: date | None = None,
    repository: InvoiceNumberRepository | None = None,
    legacy_lookup: LegacyReservationLookup | None = None,
    session: Session | None = None,
) -> str:
    """Allocate a permanent number, retrying sequence collisions safely."""
    active_repository = repository or invoice_number_repository
    active_legacy_lookup = legacy_lookup or legacy_reservation_lookup

    if reserved_for is not None:
        existing = active_repository.get_by_owner(reserved_for)
        if existing is not None:
            return existing["number"]

    fy = financial_year(at_date or datetime.now(timezone.utc).date())
    legacy_highest = active_legacy_lookup.highest_sequence(fy)
    for _ in range(_MAX_RESERVATION_ATTEMPTS):
        sequence = max(active_repository.highest_sequence(fy, session=session), legacy_highest) + 1
        if sequence > 999:
            raise ValueError(f"Invoice number limit reached for financial year {fy}.")

        number = f"{sequence:03d}/{fy}"
        try:
            active_repository.create(
                {
                    "number": number,
                    "financialYear": fy,
                    "sequence": sequence,
                    "reservedFor": reserved_for,
                    "reservedAt": datetime.now(timezone.utc).isoformat(),
                },
                session=session,
            )
            return number
        except IntegrityError:
            if reserved_for is not None:
                existing = active_repository.get_by_owner(reserved_for)
                if existing is not None:
                    return existing["number"]
            if active_repository.get_by_year_sequence(fy, sequence) is None:
                raise
            legacy_highest = max(
                legacy_highest, active_legacy_lookup.highest_sequence(fy)
            )

    raise RuntimeError("Unable to reserve a unique invoice number after repeated collisions.")


def next_invoice_number(
    reserved_for: str | None = None,
    at_date: date | None = None,
    repository: InvoiceNumberRepository | None = None,
    legacy_lookup: LegacyReservationLookup | None = None,
) -> str:
    return reserve_invoice_number(reserved_for, at_date, repository, legacy_lookup)


def is_invoice_number_taken(
    number: str, repository: InvoiceNumberRepository | None = None
) -> bool:
    return (repository or invoice_number_repository).is_reserved(number)


def reserve_invoice_number_in_workbook(
    wb: Workbook, reserved_for: str | None = None, at_date: date | None = None
) -> str:
    """Legacy Excel implementation retained for reference and rollback."""
    fy = financial_year(at_date or datetime.now(timezone.utc).date())
    reservations = read_rows(
        wb[SHEET_INVOICE_NUMBER_RESERVATIONS], SHEET_INVOICE_NUMBER_RESERVATIONS
    )
    highest = max(
        (
            int(row["sequence"])
            for row in reservations
            if row.get("financialYear") == fy
        ),
        default=0,
    )
    sequence = highest + 1
    if sequence > 999:
        raise ValueError(f"Invoice number limit reached for financial year {fy}.")
    number = f"{sequence:03d}/{fy}"
    append_row(
        wb[SHEET_INVOICE_NUMBER_RESERVATIONS],
        SHEET_INVOICE_NUMBER_RESERVATIONS,
        {
            "number": number,
            "financialYear": fy,
            "sequence": sequence,
            "reservedFor": reserved_for,
            "reservedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    return number


def next_invoice_number_in_workbook(wb: Workbook) -> str:
    return reserve_invoice_number_in_workbook(wb)


def is_invoice_number_taken_in_workbook(wb: Workbook, number: str) -> bool:
    return any(
        row.get("number") == number
        for row in read_rows(
            wb[SHEET_INVOICE_NUMBER_RESERVATIONS],
            SHEET_INVOICE_NUMBER_RESERVATIONS,
        )
    )
