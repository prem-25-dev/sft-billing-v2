"""Read-only lookup of invoice numbers consumed by the legacy workbook."""

from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import load_workbook

from app.excel.constants import SHEET_INVOICE_NUMBER_RESERVATIONS
from app.excel.workbook import WORKBOOK_PATH, workbook_lock
from app.services.historical_reservation_parser import parse_historical_reservation

logger = logging.getLogger(__name__)


class LegacyReservationLookup:
    """Inspect workbook reservations without creating, repairing, or saving it."""

    def __init__(self, workbook_path: Path = WORKBOOK_PATH) -> None:
        self._workbook_path = Path(workbook_path)

    def _reservations(self) -> list[tuple[str, str, int]]:
        if not self._workbook_path.exists():
            return []

        with workbook_lock():
            workbook = load_workbook(
                self._workbook_path, read_only=True, data_only=True
            )
            try:
                if SHEET_INVOICE_NUMBER_RESERVATIONS not in workbook.sheetnames:
                    return []

                sheet = workbook[SHEET_INVOICE_NUMBER_RESERVATIONS]
                rows = sheet.iter_rows(values_only=True)
                headers = next(rows, ())
                columns = {header: index for index, header in enumerate(headers)}
                required = {"number", "financialYear", "sequence"}
                if not required.issubset(columns):
                    raise ValueError(
                        "Legacy invoice reservation sheet is missing required headers."
                    )

                reservations: list[tuple[str, str, int]] = []
                for row in rows:
                    number_value = row[columns["number"]]
                    if number_value in (None, ""):
                        continue
                    number = str(number_value).strip()
                    financial_year_value = row[columns["financialYear"]]
                    sequence_value = row[columns["sequence"]]
                    parsed = parse_historical_reservation(
                        number,
                        source_financial_year=financial_year_value,
                        source_sequence=sequence_value,
                    )
                    for mismatch in parsed.source_mismatches:
                        logger.warning(
                            "Legacy invoice reservation mismatch number=%s field=%s "
                            "source_value=%r derived_value=%r; using number-derived value",
                            parsed.number,
                            mismatch.field,
                            mismatch.source_value,
                            mismatch.derived_value,
                        )
                    reservations.append(
                        (parsed.number, parsed.financial_year, parsed.sequence)
                    )
                return reservations
            finally:
                workbook.close()

    def is_number_reserved(self, number: str) -> bool:
        return any(reserved_number == number for reserved_number, _, _ in self._reservations())

    def highest_sequence(self, financial_year: str) -> int:
        return max(
            (
                sequence
                for _, reserved_year, sequence in self._reservations()
                if reserved_year == financial_year
            ),
            default=0,
        )

    def is_year_sequence_used(self, financial_year: str, sequence: int) -> bool:
        return any(
            reserved_year == financial_year and reserved_sequence == sequence
            for _, reserved_year, reserved_sequence in self._reservations()
        )


legacy_reservation_lookup = LegacyReservationLookup()
