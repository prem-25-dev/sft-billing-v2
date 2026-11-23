import unittest
import tempfile
from unittest.mock import patch
from datetime import date
from pathlib import Path
from sqlalchemy.orm import sessionmaker

from app.database.session import create_database_engine, shutdown_database
from app.excel.constants import SHEET_INVOICES
from app.excel.rows import append_row
from app.excel.workbook import create_new_workbook, ensure_sheets_present
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_number_repository import InvoiceNumberRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.legacy_excel_numbering import LegacyReservationLookup
from app.services import invoice_service
from app.services.numbering_service import next_invoice_number, financial_year


class InvoiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "lifecycle.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.client_repository = ClientRepository(self.session_factory, self.engine)
        self.invoice_repository = InvoiceRepository(self.session_factory, self.engine)
        self.payment_repository = PaymentRepository(self.session_factory, self.engine)
        self.number_repository = InvoiceNumberRepository(
            self.session_factory, self.engine
        )
        self.legacy_lookup = LegacyReservationLookup(
            Path(self.temp_dir.name) / "no-legacy-workbook.xlsx"
        )
        self.client_repository.create(
            {
                "id": "client-1",
                "name": "Client",
                "contactName": None,
                "email": "client@example.com",
                "phone": "123",
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "notes": None,
            }
        )
        self.invoice_repository._ensure_schema()
        self.number_repository._ensure_schema()
        self.payment_repository._ensure_schema()
        self.repository_patches = [
            patch("app.services.invoice_service.client_repository", self.client_repository),
            patch("app.services.invoice_service.invoice_repository", self.invoice_repository),
            patch("app.services.invoice_service.payment_repository", self.payment_repository),
            patch(
                "app.services.numbering_service.invoice_number_repository",
                self.number_repository,
            ),
            patch(
                "app.services.numbering_service.legacy_reservation_lookup",
                self.legacy_lookup,
            ),
        ]
        for patcher in self.repository_patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.repository_patches):
            patcher.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def _client(self):
        return {"id": "client-1"}

    def _invoice_row(self, *, is_draft: bool, sent_at=None, billed_at=None):
        return {
            "id": "invoice-1",
            "number": "INV-1035",
            "clientId": "client-1",
            "issueDate": "2025-05-01T00:00:00+00:00",
            "dueDate": "2025-05-16T00:00:00+00:00",
            "cgstRate": 0.09,
            "sgstRate": 0.09,
            "discount": 0,
            "roundOff": 0,
            "isDraft": is_draft,
            "billedAt": billed_at,
            "sentAt": sent_at,
            "viewedAt": None,
            "paidAt": None,
            "cancelledAt": None,
        }

    def _item(self):
        return {
            "id": "line-1",
            "invoiceId": "invoice-1",
            "description": "Consulting",
            "quantity": 1,
            "unitPrice": 1000,
        }

    def _seed_invoice(self, *, is_draft: bool, sent_at=None, billed_at=None):
        return self.invoice_repository.create(
            {
                "id": "invoice-1",
                "number": "INV-1035",
                "clientId": "client-1",
                "issueDate": "2025-05-01T00:00:00+00:00",
                "dueDate": "2025-05-16T00:00:00+00:00",
                "cgstRate": 0.09,
                "sgstRate": 0.09,
                "discount": 0,
                "roundOff": 0,
                "isDraft": is_draft,
                "billedAt": billed_at,
                "sentAt": sent_at,
                "viewedAt": None,
                "paidAt": None,
                "cancelledAt": None,
            },
            [self._item()],
        )

    def test_number_allocator_scans_drafts_and_billed_invoices(self):
        wb = create_new_workbook()
        ws = wb[SHEET_INVOICES]
        append_row(ws, SHEET_INVOICES, {"id": "billed", "number": "INV-1035", "isDraft": False})
        append_row(ws, SHEET_INVOICES, {"id": "draft", "number": "INV-1039", "isDraft": True})

        expected_fy = financial_year(date(2026, 10, 3))
        self.assertEqual(
            next_invoice_number(at_date=date(2026, 10, 3), repository=self.number_repository),
            f"001/{expected_fy}",
        )

    def test_billed_creation_sets_billed_at_without_marking_invoice_sent(self):
        wb = create_new_workbook()
        activity = {"type": "invoice_created"}

        payload = {
            "id": "invoice-1",
            "clientId": "client-1",
            "issueDate": "2025-05-01T00:00:00+00:00",
            "dueDate": "2025-05-16T00:00:00+00:00",
            "gst": {"cgstRate": 0.09, "sgstRate": 0.09},
            "discount": 0,
            "roundOff": 0,
            "isDraft": False,
            "items": [{"description": "Consulting", "quantity": 1, "unitPrice": 1000}],
        }

        with patch.object(
            invoice_service.activity_service, "add_activity_event", return_value=activity
        ):
            result = invoice_service.create_invoice(payload)

        self.assertFalse(result["isDraft"])
        self.assertTrue(result["billedAt"])
        self.assertIsNone(result["sentAt"])

    def test_billing_existing_draft_sets_billed_at_and_preserves_sent_at(self):
        wb = create_new_workbook()
        self._seed_invoice(
            is_draft=True, sent_at="2025-05-02T10:00:00+00:00"
        )
        billed_at = "2025-05-03T10:00:00+00:00"

        with patch.object(
            invoice_service.activity_service, "add_activity_event"
        ) as activity:
            result = invoice_service.update_invoice("invoice-1", {"isDraft": False, "billedAt": billed_at})

        self.assertFalse(result["isDraft"])
        self.assertEqual(result["billedAt"], billed_at)
        self.assertEqual(result["sentAt"], "2025-05-02T10:00:00+00:00")
        activity.assert_not_called()

    def test_legacy_invoice_sheet_gets_billed_at_header_without_reordering(self):
        wb = create_new_workbook()
        ws = wb[SHEET_INVOICES]
        original_headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column)]
        ws.delete_cols(ws.max_column)

        changed = ensure_sheets_present(wb)

        headers = [ws.cell(row=1, column=i).value for i in range(1, ws.max_column + 1)]
        self.assertTrue(changed)
        self.assertEqual(headers[:-1], original_headers)
        self.assertEqual(headers[-1], "billedAt")


if __name__ == "__main__":
    unittest.main()
