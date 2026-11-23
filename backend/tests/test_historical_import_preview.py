import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from openpyxl import Workbook, load_workbook

from app.database.models import Client, Invoice, InvoiceItem, InvoiceNumberReservation
from app.database.session import (
    create_database_engine,
    initialize_database,
    shutdown_database,
)
from app.repositories.historical_import_repository import HistoricalImportRepository
from app.repositories.invoice_number_repository import InvoiceNumberRepository
from app.services.historical_import_preview import preview_historical_import
from app.services.historical_import_service import (
    HistoricalImportConflictError,
    HistoricalImportValidationError,
    import_historical_preview,
)
from app.services.legacy_excel_numbering import LegacyReservationLookup
from app.services.numbering_service import reserve_invoice_number


class HistoricalImportPreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workbook_path = Path(self.temp_dir.name) / "historical.xlsx"
        self._make_workbook(self.workbook_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _make_workbook(path: Path, *, include_total: bool = False) -> None:
        workbook = Workbook()
        clients = workbook.active
        clients.title = "Clients"
        clients.append(
            ["id", "name", "contactName", "email", "phone", "billingAddress",
             "gstin", "clientSince", "notes", "pan"]
        )
        for index in range(1, 6):
            clients.append(
                [f"client-{index}", f"Client {index}", None, None, None,
                 f"Address {index}", f"33AAACM5230H1Z{index}",
                 "2026-10-04T12:00:00", None, None]
            )

        invoices = workbook.create_sheet("Invoices")
        invoice_headers = [
            "id", "number", "clientId", "issueDate", "dueDate", "cgstRate",
            "sgstRate", "discount", "roundOff", "notes", "terms",
            "supplierCode", "poNumber", "poDate", "transporter", "isDraft",
            "sentAt", "viewedAt", "paidAt", "cancelledAt", "billedAt",
        ]
        if include_total:
            invoice_headers.append("total")
        invoices.append(invoice_headers)
        numbers = (
            "001/2026-27",
            "011/2026-27",
            "015/2026-27",
            "023/2026-27",
            "029/2026-27",
        )
        for index, number in enumerate(numbers, start=1):
            invoice_row = [
                f"invoice-{index}", number, f"client-{index}",
                "2026-04-01", "2026-04-30", 0.09, 0.09, 0, 0,
                None, None, None, None, None, None, False,
                None, None, None, None, "2026-04-01T00:00:00+00:00",
            ]
            if include_total:
                invoice_row.append(999 if index == 1 else 0)
            invoices.append(invoice_row)

        items = workbook.create_sheet("InvoiceItems")
        items.append(
            ["id", "invoiceId", "productId", "description", "hsnCode",
             "quantity", "unitPrice"]
        )
        item_id = 0
        for invoice_index, item_count in enumerate((3, 1, 2, 1, 1), start=1):
            for _ in range(item_count):
                item_id += 1
                items.append(
                    [f"item-{item_id}", f"invoice-{invoice_index}", None,
                     f"Item {item_id}", "9989", 2, 10.5]
                )

        reservations = workbook.create_sheet("InvoiceNumberReservations")
        reservations.append(
            ["number", "financialYear", "sequence", "reservedFor", "reservedAt"]
        )
        reservation_rows = [
            ("001/2026-27", "2026-27", 1, None),
            ("006/2026-27", "2026-27", 6, "unresolved-draft-id"),
            ("011/2026-27", "2026-27", 2, None),
            ("015/2026-27", "2026-27", 3, None),
            ("023/2026-27", "2026-27", 4, None),
            ("029/2026-27", "2026-27", 5, None),
        ]
        for number, financial_year, sequence, owner in reservation_rows:
            reservations.append(
                [number, financial_year, sequence, owner, "2026-10-04T12:00:00"]
            )

        workbook.create_sheet("Payments").append(
            ["id", "invoiceId", "clientId", "amount"]
        )
        workbook.create_sheet("Activities").append(
            ["id", "type", "occurredAt", "summary"]
        )
        workbook.create_sheet("BusinessProfile").append(["name", "email"])
        workbook.save(path)

    def test_maps_entity_counts_contacts_null_snapshots_and_products_as_optional(self):
        preview = preview_historical_import(self.workbook_path)

        self.assertTrue(preview.is_valid, preview.errors)
        self.assertEqual(
            preview.counts,
            {"clients": 5, "invoices": 5, "invoiceItems": 8, "reservations": 6},
        )
        self.assertEqual(preview.excluded_source_counts, {"payments": 0, "activities": 0})
        client = preview.records["clients"][0]
        self.assertIsNone(client["email"])
        self.assertIsNone(client["phone"])
        self.assertIsNone(client["pan"])
        self.assertNotIn("clientSince", client)

        invoice = preview.records["invoices"][0]
        self.assertTrue(all(invoice[field] is None for field in (
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
        )))
        self.assertIsNone(preview.records["invoiceItems"][0]["productId"])
        self.assertEqual(preview.writes_performed, 0)
        self.assertFalse(preview.commit_supported)

    def test_derives_reservations_from_number_and_reports_source_mismatches(self):
        preview = preview_historical_import(self.workbook_path)

        reservations = {
            row["number"]: (row["financialYear"], row["sequence"])
            for row in preview.records["reservations"]
        }
        self.assertEqual(reservations, {
            "001/2026-27": ("2026-27", 1),
            "006/2026-27": ("2026-27", 6),
            "011/2026-27": ("2026-27", 11),
            "015/2026-27": ("2026-27", 15),
            "023/2026-27": ("2026-27", 23),
            "029/2026-27": ("2026-27", 29),
        })
        self.assertEqual(
            {mismatch["number"] for mismatch in preview.reservation_mismatches},
            {"011/2026-27", "015/2026-27", "023/2026-27", "029/2026-27"},
        )
        self.assertEqual(
            preview.reservation_usage["006/2026-27"],
            "unused_reservation",
        )
        unused = next(
            row for row in preview.records["reservations"]
            if row["number"] == "006/2026-27"
        )
        self.assertEqual(unused["reservedFor"], "unresolved-draft-id")
        self.assertTrue(any(
            finding.field == "reservedFor" and finding.severity == "warning"
            for finding in preview.warnings
        ))

    def test_calculates_totals_and_reports_source_total_discrepancies(self):
        self._make_workbook(self.workbook_path, include_total=True)
        preview = preview_historical_import(self.workbook_path)

        totals = preview.calculated_totals["invoice-1"]
        self.assertEqual(totals["subtotal"], 63)
        self.assertEqual(totals["cgstAmount"], 5.67)
        self.assertEqual(totals["sgstAmount"], 5.67)
        self.assertEqual(totals["total"], 74.34)
        self.assertEqual(len(preview.total_discrepancies), 5)
        self.assertEqual(preview.total_discrepancies[0]["calculatedValue"], 74.34)

    def test_duplicate_keys_missing_references_and_bad_reservation_are_errors(self):
        workbook = load_workbook(self.workbook_path)
        workbook["Clients"]["A3"] = "client-1"
        workbook["Invoices"]["C2"] = "missing-client"
        workbook["InvoiceItems"]["B2"] = "missing-invoice"
        workbook["InvoiceNumberReservations"]["A4"] = "not-an-invoice-number"
        workbook.save(self.workbook_path)

        preview = preview_historical_import(self.workbook_path)
        self.assertFalse(preview.is_valid)
        error_fields = {(finding.entity, finding.field) for finding in preview.errors}
        self.assertIn(("clients", "id"), error_fields)
        self.assertIn(("invoices", "clientId"), error_fields)
        self.assertIn(("invoiceItems", "invoiceId"), error_fields)
        self.assertIn(("reservations", "number"), error_fields)
        self.assertIn(("invoices", "number"), error_fields)

    def test_blank_required_fields_and_invalid_values_are_reported(self):
        workbook = load_workbook(self.workbook_path)
        workbook["Clients"]["B2"] = None
        workbook["Invoices"]["F2"] = 1.5
        workbook["InvoiceItems"]["F2"] = 0
        workbook.save(self.workbook_path)

        preview = preview_historical_import(self.workbook_path)
        self.assertFalse(preview.is_valid)
        error_fields = {(finding.entity, finding.field) for finding in preview.errors}
        self.assertIn(("clients", "name"), error_fields)
        self.assertIn(("invoices", "cgstRate"), error_fields)
        self.assertIn(("invoiceItems", "quantity"), error_fields)
        self.assertGreater(preview.missing_values["clients.name"], 0)

    def test_duplicate_invoice_item_and_reservation_unique_keys_are_reported(self):
        workbook = load_workbook(self.workbook_path)
        workbook["Invoices"]["B3"] = "001/2026-27"
        workbook["InvoiceItems"]["A3"] = "item-1"
        workbook["InvoiceNumberReservations"]["D4"] = "unresolved-draft-id"
        workbook["InvoiceNumberReservations"]["C4"] = 1
        workbook["InvoiceNumberReservations"]["A4"] = "001/2026-27"
        workbook.save(self.workbook_path)

        preview = preview_historical_import(self.workbook_path)
        error_fields = {(finding.entity, finding.field) for finding in preview.errors}
        self.assertIn(("invoices", "number"), error_fields)
        self.assertIn(("invoiceItems", "id"), error_fields)
        self.assertIn(("reservations", "number"), error_fields)
        self.assertIn(("reservations", "sequence"), error_fields)
        self.assertIn(("reservations", "reservedFor"), error_fields)

    def test_preview_is_repeatable_and_does_not_write_workbook_or_database(self):
        before = hashlib.sha256(self.workbook_path.read_bytes()).hexdigest()
        production_db = Path(__file__).resolve().parents[1] / "data" / "sft_billing.db"
        database_existed_before = production_db.exists()

        first = preview_historical_import(self.workbook_path)
        second = preview_historical_import(self.workbook_path)

        after = hashlib.sha256(self.workbook_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(first.records, second.records)
        self.assertEqual(first.counts, second.counts)
        self.assertEqual(first.errors, second.errors)
        self.assertEqual(first.warnings, second.warnings)
        self.assertEqual(first.source_sha256, before)
        self.assertEqual(first.writes_performed, 0)
        self.assertEqual(production_db.exists(), database_existed_before)

    def test_preview_reports_source_hash_and_no_unavailable_snapshot_or_total_values(self):
        preview = preview_historical_import(self.workbook_path)

        self.assertEqual(preview.source_sha256, hashlib.sha256(self.workbook_path.read_bytes()).hexdigest())
        self.assertTrue(any(
            finding.field == "clientSince" for finding in preview.warnings
        ))
        self.assertTrue(any("no stored subtotal" in finding.message for finding in preview.warnings))
        self.assertFalse(preview.total_discrepancies)
        self.assertEqual(len(preview.calculated_totals), 5)


class HistoricalImportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.workbook_path = root / "historical.xlsx"
        HistoricalImportPreviewTests._make_workbook(self.workbook_path)
        self.engine = create_database_engine(
            f"sqlite:///{(root / 'historical.db').as_posix()}"
        )
        initialize_database(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def tearDown(self):
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def _entity_counts(self):
        with self.session_factory() as session:
            return {
                "clients": session.scalar(select(func.count()).select_from(Client)),
                "invoices": session.scalar(select(func.count()).select_from(Invoice)),
                "invoiceItems": session.scalar(
                    select(func.count()).select_from(InvoiceItem)
                ),
                "reservations": session.scalar(
                    select(func.count()).select_from(InvoiceNumberReservation)
                ),
            }

    def test_imports_all_entities_and_allocator_advances_past_every_reservation(self):
        preview = preview_historical_import(self.workbook_path)
        result = import_historical_preview(preview, self.session_factory)

        self.assertEqual(result.counts, {
            "clients": 5,
            "invoices": 5,
            "invoiceItems": 8,
            "reservations": 6,
        })
        self.assertEqual(self._entity_counts(), result.counts)
        with self.session_factory() as session:
            client = session.get(Client, "client-1")
            invoice = session.get(Invoice, "invoice-1")
            item = session.get(InvoiceItem, "item-1")
            reservations = set(
                session.scalars(select(InvoiceNumberReservation.number))
            )
            self.assertIsNone(client.email)
            self.assertIsNone(client.phone)
            self.assertIsNone(client.pan)
            self.assertEqual(invoice.cgst_rate, 0.09)
            self.assertEqual(invoice.sgst_rate, 0.09)
            self.assertIsNone(invoice.customer_name_snapshot)
            self.assertIsNone(invoice.business_name_snapshot)
            self.assertEqual(item.unit_price, 1050)
            self.assertIsNone(item.product_id)
            self.assertIn("006/2026-27", reservations)
            self.assertEqual(
                session.connection()
                .exec_driver_sql("PRAGMA foreign_key_check")
                .all(),
                [],
            )

        number_repository = InvoiceNumberRepository(
            self.session_factory, self.engine
        )
        allocated = reserve_invoice_number(
            "new-after-history",
            date(2026, 10, 14),
            number_repository,
            LegacyReservationLookup(Path(self.temp_dir.name) / "no-legacy.xlsx"),
        )
        self.assertEqual(allocated, "030/2026-27")

    def test_blocking_preview_error_prevents_all_writes(self):
        workbook = load_workbook(self.workbook_path)
        workbook["Clients"]["B2"] = None
        workbook.save(self.workbook_path)
        preview = preview_historical_import(self.workbook_path)

        with self.assertRaises(HistoricalImportValidationError):
            import_historical_preview(preview, self.session_factory)

        self.assertEqual(
            self._entity_counts(),
            {"clients": 0, "invoices": 0, "invoiceItems": 0, "reservations": 0},
        )

    def test_existing_keys_are_conflicts_and_rerun_never_skips_or_overwrites(self):
        preview = preview_historical_import(self.workbook_path)
        import_historical_preview(preview, self.session_factory)

        with self.assertRaises(HistoricalImportConflictError) as raised:
            import_historical_preview(preview, self.session_factory)

        conflict_entities = {conflict["entity"] for conflict in raised.exception.conflicts}
        self.assertEqual(
            conflict_entities,
            {"clients", "invoices", "invoiceItems", "reservations"},
        )
        self.assertTrue(any(
            conflict["key"] == "number=001/2026-27"
            for conflict in raised.exception.conflicts
        ))
        self.assertTrue(any(
            conflict["key"] == "2026-27/6"
            for conflict in raised.exception.conflicts
        ))
        self.assertEqual(
            self._entity_counts(),
            {"clients": 5, "invoices": 5, "invoiceItems": 8, "reservations": 6},
        )

    def test_source_changes_or_candidate_tampering_rejects_stale_preview(self):
        preview = preview_historical_import(self.workbook_path)
        workbook = load_workbook(self.workbook_path)
        workbook["Clients"]["B2"] = "Changed after preview"
        workbook.save(self.workbook_path)

        with self.assertRaises(HistoricalImportValidationError):
            import_historical_preview(preview, self.session_factory)

        self.assertEqual(self._entity_counts()["clients"], 0)

    def test_relationship_validation_failure_prevents_all_writes(self):
        preview = preview_historical_import(self.workbook_path)
        records = {
            entity: tuple(dict(record) for record in rows)
            for entity, rows in preview.records.items()
        }
        records["invoices"][0]["clientId"] = "missing-client"
        inconsistent_preview = replace(preview, records=records)

        with patch(
            "app.services.historical_import_service._verify_preview_is_current"
        ):
            with self.assertRaisesRegex(
                HistoricalImportValidationError, "references a Client"
            ):
                import_historical_preview(inconsistent_preview, self.session_factory)

        self.assertEqual(
            self._entity_counts(),
            {"clients": 0, "invoices": 0, "invoiceItems": 0, "reservations": 0},
        )

    def test_import_rejects_schema_without_nullable_client_migration(self):
        old_engine = create_database_engine(
            f"sqlite:///{(Path(self.temp_dir.name) / 'old-schema.db').as_posix()}"
        )
        old_factory = sessionmaker(
            bind=old_engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        try:
            from app.database.session import initialize_numbering_database

            initialize_numbering_database(old_engine)
            preview = preview_historical_import(self.workbook_path)
            with self.assertRaisesRegex(RuntimeError, "nullable client-field migration"):
                import_historical_preview(preview, old_factory)
            with old_engine.connect() as connection:
                self.assertEqual(
                    connection.exec_driver_sql(
                        "SELECT version_num FROM alembic_version"
                    ).scalar(),
                    "0003_invoice_number_reservations",
                )
        finally:
            shutdown_database(old_engine)

    def test_database_foreign_key_violation_rolls_back_prior_client_inserts(self):
        preview = preview_historical_import(self.workbook_path)

        def add_invoice_with_invalid_client(repository, records):
            self.assertTrue(records)
            repository._session.add(
                Invoice(
                    id="invalid-invoice",
                    number="900/2026-27",
                    client_id="missing-client",
                    issue_date="2026-04-01",
                    due_date="2026-04-30",
                    cgst_rate=0,
                    sgst_rate=0,
                    discount=0,
                    round_off=0,
                    is_draft=True,
                )
            )
            repository._session.flush()

        with patch.object(
            HistoricalImportRepository,
            "add_invoices",
            add_invoice_with_invalid_client,
        ):
            with self.assertRaises(IntegrityError):
                import_historical_preview(preview, self.session_factory)

        self.assertEqual(
            self._entity_counts(),
            {"clients": 0, "invoices": 0, "invoiceItems": 0, "reservations": 0},
        )

    def test_late_failure_rolls_back_clients_and_invoices(self):
        preview = preview_historical_import(self.workbook_path)

        def fail_after_prior_inserts(repository, records):
            self.assertTrue(repository._session.is_active)
            self.assertTrue(records)
            raise RuntimeError("simulated item persistence failure")

        with patch.object(
            HistoricalImportRepository,
            "add_invoice_items",
            fail_after_prior_inserts,
        ):
            with self.assertRaisesRegex(RuntimeError, "simulated item"):
                import_historical_preview(preview, self.session_factory)

        self.assertEqual(
            self._entity_counts(),
            {"clients": 0, "invoices": 0, "invoiceItems": 0, "reservations": 0},
        )


if __name__ == "__main__":
    unittest.main()
