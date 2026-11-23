from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
from pathlib import Path
from threading import Barrier

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.session import create_database_engine, shutdown_database
from app.excel.constants import (
    SHEET_INVOICE_NUMBER_RESERVATIONS,
)
from app.excel.rows import append_row
from app.excel.workbook import create_new_workbook
from app.repositories.invoice_number_repository import InvoiceNumberRepository
from app.services.legacy_excel_numbering import LegacyReservationLookup
from app.services.numbering_service import (
    financial_year,
    get_reserved_invoice_number,
    is_invoice_number_taken,
    reserve_invoice_number,
)


class InvoiceNumberingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "numbering.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.repository = InvoiceNumberRepository(self.session_factory, self.engine)
        self.repository._ensure_schema()
        self.legacy_path = Path(self.temp_dir.name) / "legacy.xlsx"
        self._write_legacy_reservations([])
        self.legacy_lookup = LegacyReservationLookup(self.legacy_path)

    def tearDown(self) -> None:
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    @staticmethod
    def _reservation(
        number: str,
        financial_year: str,
        sequence: int,
        reserved_for: str | None = None,
    ) -> dict:
        return {
            "number": number,
            "financialYear": financial_year,
            "sequence": sequence,
            "reservedFor": reserved_for,
            "reservedAt": "2026-10-07T00:00:00+00:00",
        }

    def _write_legacy_reservations(
        self, reservations: list[tuple[str, str, int]]
    ) -> None:
        workbook = create_new_workbook()
        sheet = workbook[SHEET_INVOICE_NUMBER_RESERVATIONS]
        for number, financial_year, sequence in reservations:
            append_row(
                sheet,
                SHEET_INVOICE_NUMBER_RESERVATIONS,
                {
                    "number": number,
                    "financialYear": financial_year,
                    "sequence": sequence,
                    "reservedFor": None,
                    "reservedAt": "2026-10-07T00:00:00+00:00",
                },
            )
        workbook.save(self.legacy_path)

    def _reserve(self, owner: str, at_date: date = date(2026, 10, 7)) -> str:
        return reserve_invoice_number(
            owner, at_date, self.repository, self.legacy_lookup
        )

    def test_financial_year_boundary_and_number_format(self) -> None:
        self.assertEqual(financial_year(date(2026, 3, 31)), "2025-26")
        self.assertEqual(financial_year(date(2026, 4, 1)), "2026-27")
        self.assertEqual(
            self._reserve("first"),
            "001/2026-27",
        )
        self.assertEqual(
            self._reserve("second"),
            "002/2026-27",
        )
        self.assertEqual(
            self._reserve("next-year", date(2027, 4, 1)),
            "001/2027-28",
        )

    def test_reservation_owner_is_idempotent_and_reservation_is_permanent(self) -> None:
        reserved = self._reserve("invoice-not-yet-created")
        self.assertEqual(
            self._reserve("invoice-not-yet-created", date(2027, 1, 1)),
            reserved,
        )
        self.assertEqual(
            get_reserved_invoice_number("invoice-not-yet-created", self.repository),
            reserved,
        )
        self.assertTrue(is_invoice_number_taken(reserved, self.repository))
        self.assertIsNone(self.repository.get_by_owner("unowned-invoice"))
        self.assertEqual(self.repository.get_by_number(reserved)["reservedFor"], "invoice-not-yet-created")

    def test_unique_constraints_and_multiple_null_owners(self) -> None:
        self.repository.create(self._reservation("001/2026-27", "2026-27", 1, "owner-1"))
        self.repository.create(self._reservation("002/2026-27", "2026-27", 2))
        self.repository.create(self._reservation("003/2026-27", "2026-27", 3))

        with self.assertRaises(IntegrityError):
            self.repository.create(
                self._reservation("001/2026-27", "2026-27", 4, "owner-4")
            )
        with self.assertRaises(IntegrityError):
            self.repository.create(
                self._reservation("different-number", "2026-27", 1, "owner-5")
            )
        with self.assertRaises(IntegrityError):
            self.repository.create(
                self._reservation("004/2026-27", "2026-27", 4, "owner-1")
            )

        self.assertEqual(self.repository.highest_sequence("2026-27"), 3)
        self.assertIsNone(self.repository.get_by_number("004/2026-27"))

    def test_failed_insert_rolls_back_and_does_not_consume_sequence(self) -> None:
        self.repository.create(self._reservation("001/2026-27", "2026-27", 1))
        with self.assertRaises(IntegrityError):
            self.repository.create(self._reservation("wrong-number", "2026-27", 1))
        self.assertEqual(
            self._reserve("next"),
            "002/2026-27",
        )

    def test_excel_only_history_advances_sqlite_sequence(self) -> None:
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("002/2026-27", "2026-27", 2),
                ("003/2026-27", "2026-27", 3),
            ]
        )
        self.assertEqual(self._reserve("next"), "004/2026-27")

    def test_sqlite_only_history_advances_sequence(self) -> None:
        self.repository.create(self._reservation("001/2026-27", "2026-27", 1))
        self.repository.create(self._reservation("002/2026-27", "2026-27", 2))
        self.assertEqual(self._reserve("next"), "003/2026-27")

    def test_mixed_noncontiguous_history_uses_highest_consumed_sequence(self) -> None:
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("003/2026-27", "2026-27", 3),
            ]
        )
        self.repository.create(self._reservation("002/2026-27", "2026-27", 2))
        self.assertEqual(self._reserve("next"), "004/2026-27")

    def test_gaps_across_sources_do_not_reuse_lower_number(self) -> None:
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("005/2026-27", "2026-27", 5),
            ]
        )
        self.repository.create(self._reservation("002/2026-27", "2026-27", 2))
        self.repository.create(self._reservation("003/2026-27", "2026-27", 3))
        self.assertEqual(self._reserve("next"), "006/2026-27")

    def test_different_financial_year_history_does_not_affect_allocation(self) -> None:
        self._write_legacy_reservations(
            [("099/2025-26", "2025-26", 99)]
        )
        self.repository.create(
            self._reservation("050/2025-26", "2025-26", 50)
        )
        self.assertEqual(self._reserve("new-year"), "001/2026-27")

    def test_legacy_lookup_answers_number_year_sequence_and_highest_queries(self) -> None:
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("003/2026-27", "2026-27", 3),
            ]
        )
        self.assertTrue(self.legacy_lookup.is_number_reserved("001/2026-27"))
        self.assertFalse(self.legacy_lookup.is_number_reserved("002/2026-27"))
        self.assertEqual(self.legacy_lookup.highest_sequence("2026-27"), 3)
        self.assertTrue(self.legacy_lookup.is_year_sequence_used("2026-27", 3))
        self.assertFalse(self.legacy_lookup.is_year_sequence_used("2026-27", 2))

    def test_legacy_lookup_is_read_only(self) -> None:
        self._write_legacy_reservations(
            [("001/2026-27", "2026-27", 1)]
        )
        original_hash = sha256(self.legacy_path.read_bytes()).hexdigest()
        self.assertEqual(self.legacy_lookup.highest_sequence("2026-27"), 1)
        self.assertTrue(self.legacy_lookup.is_number_reserved("001/2026-27"))
        self.assertEqual(
            sha256(self.legacy_path.read_bytes()).hexdigest(), original_hash
        )

    def test_conflicting_legacy_source_sequence_uses_invoice_number_without_workbook_writes(self) -> None:
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("006/2026-27", "2026-27", 6),
                ("011/2026-27", "2026-27", 2),
                ("015/2026-27", "2026-27", 3),
                ("023/2026-27", "2026-27", 4),
                ("029/2026-27", "2026-27", 5),
            ]
        )
        original_hash = sha256(self.legacy_path.read_bytes()).hexdigest()

        with self.assertLogs(
            "app.services.legacy_excel_numbering", level="WARNING"
        ) as logged:
            self.assertEqual(self.legacy_lookup.highest_sequence("2026-27"), 29)
            self.assertTrue(
                self.legacy_lookup.is_year_sequence_used("2026-27", 29)
            )
            self.assertEqual(
                self._reserve("after-conflicting-history"),
                "030/2026-27",
            )

        self.assertTrue(
            any(
                "number=011/2026-27 field=sequence" in message
                and "source_value=2" in message
                and "derived_value=11" in message
                for message in logged.output
            )
        )
        self.assertEqual(
            sha256(self.legacy_path.read_bytes()).hexdigest(), original_hash
        )

    def test_schema_constraints_and_reservation_has_no_invoice_foreign_key(self) -> None:
        inspector = inspect(self.engine)
        columns = {column["name"] for column in inspector.get_columns("invoice_number_reservations")}
        self.assertEqual(
            columns,
            {"number", "financialYear", "sequence", "reservedFor", "reservedAt"},
        )
        self.assertEqual(
            inspector.get_pk_constraint("invoice_number_reservations")["constrained_columns"],
            ["number"],
        )
        self.assertEqual(inspector.get_foreign_keys("invoice_number_reservations"), [])
        unique_sets = {
            tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(
                "invoice_number_reservations"
            )
        }
        self.assertEqual(
            unique_sets,
            {("financialYear", "sequence"), ("reservedFor",)},
        )
        self.assertEqual(
            {
                tuple(index["column_names"])
                for index in inspector.get_indexes("invoice_number_reservations")
            },
            {("financialYear",)},
        )

    def test_concurrent_reservations_never_return_duplicate_numbers(self) -> None:
        count = 12
        barrier = Barrier(count)
        self._write_legacy_reservations(
            [
                ("001/2026-27", "2026-27", 1),
                ("003/2026-27", "2026-27", 3),
            ]
        )
        self.repository.create(
            self._reservation("002/2026-27", "2026-27", 2)
        )

        def reserve(index: int) -> str:
            barrier.wait()
            return self._reserve(f"concurrent-owner-{index}")

        with ThreadPoolExecutor(max_workers=count) as pool:
            numbers = list(pool.map(reserve, range(count)))

        self.assertEqual(len(numbers), count)
        self.assertEqual(len(set(numbers)), count)
        self.assertEqual(
            set(numbers),
            {f"{sequence:03d}/2026-27" for sequence in range(4, count + 4)},
        )


if __name__ == "__main__":
    unittest.main()
