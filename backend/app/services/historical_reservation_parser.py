"""Parse historical reservation numbers without using redundant source columns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_INVOICE_NUMBER_PATTERN = re.compile(r"^(\d{3})/(\d{4})-(\d{2})$")


@dataclass(frozen=True)
class SourceFieldMismatch:
    field: Literal["financialYear", "sequence"]
    source_value: object
    derived_value: str | int


@dataclass(frozen=True)
class ParsedHistoricalReservation:
    number: str
    financial_year: str
    sequence: int
    source_mismatches: tuple[SourceFieldMismatch, ...]


def parse_historical_reservation(
    number: object,
    *,
    source_financial_year: object = None,
    source_sequence: object = None,
) -> ParsedHistoricalReservation:
    """Derive reservation values from its issued invoice number.

    Source-column mismatches are returned for reporting and never affect the
    derived financial year or sequence.
    """
    normalized_number = number.strip() if isinstance(number, str) else ""
    match = _INVOICE_NUMBER_PATTERN.fullmatch(normalized_number)
    if match is None:
        raise ValueError(f"Malformed historical invoice number: {number!r}.")

    sequence = int(match.group(1))
    start_year = int(match.group(2))
    end_year_suffix = int(match.group(3))
    if sequence == 0 or end_year_suffix != (start_year + 1) % 100:
        raise ValueError(f"Malformed historical invoice number: {number!r}.")

    financial_year = f"{match.group(2)}-{match.group(3)}"
    mismatches: list[SourceFieldMismatch] = []
    if source_financial_year not in (None, ""):
        if str(source_financial_year).strip() != financial_year:
            mismatches.append(
                SourceFieldMismatch(
                    field="financialYear",
                    source_value=source_financial_year,
                    derived_value=financial_year,
                )
            )
    if source_sequence not in (None, ""):
        if not _source_sequence_matches(source_sequence, sequence):
            mismatches.append(
                SourceFieldMismatch(
                    field="sequence",
                    source_value=source_sequence,
                    derived_value=sequence,
                )
            )

    return ParsedHistoricalReservation(
        number=normalized_number,
        financial_year=financial_year,
        sequence=sequence,
        source_mismatches=tuple(mismatches),
    )


def _source_sequence_matches(value: object, sequence: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == sequence
    if isinstance(value, float):
        return value.is_integer() and int(value) == sequence
    if isinstance(value, str):
        try:
            return int(value.strip()) == sequence
        except ValueError:
            return False
    return False
