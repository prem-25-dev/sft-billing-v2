import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.models import Invoice, InvoiceItem
from app.database.session import create_database_engine, shutdown_database
from app.excel.constants import SHEET_ACTIVITIES, SHEET_INVOICE_NUMBER_RESERVATIONS
from app.excel.workbook import create_new_workbook
from app.repositories.activity_repository import ActivityRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_number_repository import InvoiceNumberRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.services.legacy_excel_numbering import LegacyReservationLookup
from app.routes.invoice_items import router as invoice_items_router
from app.routes.invoices import router as invoices_router
from app.services import activity_service, invoice_item_service, invoice_service
from app.utils.errors import ConflictError, NotFoundError, ValidationFailedError


class InvoicePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "invoice-core.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.client_repository = ClientRepository(self.session_factory, self.engine)
        self.invoice_repository = InvoiceRepository(self.session_factory, self.engine)
        self.number_repository = InvoiceNumberRepository(
            self.session_factory, self.engine
        )
        self.payment_repository = PaymentRepository(self.session_factory, self.engine)
        self.legacy_lookup = LegacyReservationLookup(
            Path(self.temp_dir.name) / "no-legacy-workbook.xlsx"
        )
        self.client_repository.create(self._client())
        self.invoice_repository._ensure_schema()
        self.number_repository._ensure_schema()
        self.payment_repository._ensure_schema()
        self.workbook = create_new_workbook()
        self._patches = [
            patch("app.services.invoice_service.client_repository", self.client_repository),
            patch("app.services.invoice_service.invoice_repository", self.invoice_repository),
            patch("app.services.invoice_service.payment_repository", self.payment_repository),
            patch("app.services.payment_service.invoice_repository", self.invoice_repository),
            patch("app.services.payment_service.payment_repository", self.payment_repository),
            patch(
                "app.services.numbering_service.invoice_number_repository",
                self.number_repository,
            ),
            patch(
                "app.services.numbering_service.legacy_reservation_lookup",
                self.legacy_lookup,
            ),
            patch("app.services.invoice_item_service.invoice_repository", self.invoice_repository),
            patch("app.services.activity_service.add_activity_event", return_value={}),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self._patches):
            patcher.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    @staticmethod
    def _client(client_id: str = "client-1") -> dict:
        return {
            "id": client_id,
            "name": "Client",
            "contactName": None,
            "email": "client@example.com",
            "phone": "123",
            "billingAddress": "Address",
            "gstin": "29AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "notes": None,
        }

    @staticmethod
    def _item(
        item_id: str,
        *,
        description: str = "Service",
        unit_price: float = 100.25,
        product_id: str | None = None,
    ) -> dict:
        return {
            "id": item_id,
            "productId": product_id,
            "description": description,
            "hsnCode": "9983",
            "quantity": 2,
            "unitPrice": unit_price,
        }

    def _payload(
        self,
        *,
        invoice_id: str = "invoice-1",
        is_draft: bool = True,
        items: list[dict] | None = None,
    ) -> dict:
        return {
            "id": invoice_id,
            "clientId": "client-1",
            "issueDate": "2026-10-06",
            "dueDate": "2999-10-20",
            "gst": {"cgstRate": 0.09, "sgstRate": 0.09},
            "discount": 12.34,
            "roundOff": -0.01,
            "notes": "Initial notes",
            "terms": "Net 15",
            "supplierCode": "SUP-1",
            "poNumber": "PO-1",
            "poDate": "2026-10-01",
            "transporter": "Courier",
            "isDraft": is_draft,
            "items": items if items is not None else [
                self._item("item-1"),
                self._item("item-2", description="Another service", unit_price=50),
            ],
        }

    def test_create_get_by_id_number_and_list_preserve_core_fields(self):
        result = invoice_service.create_invoice(self._payload())

        self.assertEqual(result["id"], "invoice-1")
        self.assertEqual(result["number"], "001/2026-27")
        self.assertEqual(result["clientId"], "client-1")
        self.assertEqual(result["items"][0]["unitPrice"], 100.25)
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["gst"], {"cgstRate": 0.09, "sgstRate": 0.09})
        self.assertEqual(result["discount"], 12.34)
        self.assertEqual(result["roundOff"], -0.01)
        self.assertEqual(invoice_service.get_invoice("invoice-1")["number"], result["number"])
        self.assertEqual(
            self.invoice_repository.get_by_number("001/2026-27")["id"],
            "invoice-1",
        )
        self.assertEqual([row["id"] for row in invoice_service.list_invoices()], ["invoice-1"])

    def test_invoice_monetary_values_round_trip_as_integer_paise(self):
        invoice_service.create_invoice(
            {
                **self._payload(items=[self._item("item-money", unit_price=79_438.50)]),
                "discount": 1_234.56,
                "roundOff": -0.50,
            }
        )

        with self.engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT discount, roundOff FROM invoices WHERE id = 'invoice-1'"
                )
            ).one()
            stored_item_price = connection.execute(
                text("SELECT unitPrice FROM invoice_items WHERE id = 'item-money'")
            ).scalar()
        self.assertEqual(tuple(stored), (123_456, -50))
        self.assertEqual(stored_item_price, 7_943_850)

        result = invoice_service.get_invoice("invoice-1")
        self.assertEqual(result["discount"], 1_234.56)
        self.assertEqual(result["roundOff"], -0.5)
        self.assertEqual(result["items"][0]["unitPrice"], 79_438.5)

    def test_snapshot_fields_round_trip_through_repository_and_service(self):
        payload = self._payload(items=[self._item("item-snapshot")])
        payload["customerNameSnapshot"] = "Historical Customer"
        payload["customerAddressSnapshot"] = "Old Customer Address"
        payload["businessBankNameSnapshot"] = "Historical Bank"
        payload["authorizedSignatureReferenceSnapshot"] = "signature/ref.png"

        invoice_service.create_invoice(payload)
        persisted = self.invoice_repository.get_by_id("invoice-1")
        self.assertEqual(persisted["customerNameSnapshot"], "Historical Customer")
        self.assertEqual(persisted["customerAddressSnapshot"], "Old Customer Address")
        self.assertEqual(persisted["businessBankNameSnapshot"], "Historical Bank")
        self.assertEqual(
            persisted["authorizedSignatureReferenceSnapshot"], "signature/ref.png"
        )

        invoice_service.update_invoice(
            "invoice-1", {"notes": "Edited without losing snapshots"}
        )
        persisted_after_update = self.invoice_repository.get_by_id("invoice-1")
        self.assertEqual(
            persisted_after_update["customerNameSnapshot"], "Historical Customer"
        )
        self.assertEqual(
            persisted_after_update["authorizedSignatureReferenceSnapshot"],
            "signature/ref.png",
        )

    def test_invalid_items_fail_validation_before_creating_invoice_or_consuming_number(self):
        payload = self._payload(items=[self._item("item-invalid", description="  ")])

        with self.assertRaises(ValidationFailedError):
            invoice_service.create_invoice(payload)

        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1"))
        self.assertEqual(self.number_repository.highest_sequence("2026-27"), 0)

    def test_repository_create_rolls_back_invoice_and_items_on_database_failure(self):
        invoice_values = {
            "id": "atomic-invoice",
            "number": "002/2026-27",
            "clientId": "client-1",
            "issueDate": "2026-10-06",
            "dueDate": "2026-10-20",
            "cgstRate": 0.09,
            "sgstRate": 0.09,
            "discount": 0,
            "roundOff": 0,
            "isDraft": True,
        }
        items = [
            self._item("duplicate-item"),
            self._item("duplicate-item", description="Duplicate item identity"),
        ]

        with self.assertRaises(IntegrityError):
            self.invoice_repository.create(invoice_values, items)

        self.assertIsNone(self.invoice_repository.get_by_id("atomic-invoice"))
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text(
                        "SELECT COUNT(*) FROM invoice_items "
                        "WHERE invoiceId = 'atomic-invoice'"
                    )
                ).scalar(),
                0,
            )

    def test_item_replacement_and_invoice_update_roll_back_together(self):
        invoice_service.create_invoice(self._payload())
        original = self.invoice_repository.get_by_id("invoice-1")

        with self.assertRaises(IntegrityError):
            self.invoice_repository.update(
                "invoice-1",
                {"notes": "Must roll back"},
                [
                    self._item("duplicate-item"),
                    self._item("duplicate-item", description="Duplicate"),
                ],
            )

        current = self.invoice_repository.get_by_id("invoice-1")
        self.assertEqual(current["notes"], original["notes"])
        self.assertEqual(current["items"], original["items"])

    def test_missing_client_keeps_application_level_not_found_behavior(self):
        payload = self._payload()
        payload["clientId"] = "excel-only-client"

        with self.assertRaisesRegex(NotFoundError, "Client excel-only-client not found"):
            invoice_service.create_invoice(payload)

        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1"))

    def test_database_foreign_key_rejects_invoice_with_missing_client(self):
        values = {
            "id": "orphan-invoice",
            "number": "002/2026-27",
            "clientId": "missing-client",
            "issueDate": "2026-10-06",
            "dueDate": "2026-10-20",
            "cgstRate": 0.09,
            "sgstRate": 0.09,
            "discount": 0,
            "roundOff": 0,
            "isDraft": True,
        }
        with self.assertRaises(IntegrityError):
            self.invoice_repository.create(values, [self._item("orphan-item")])
        self.assertIsNone(self.invoice_repository.get_by_id("orphan-invoice"))

    def test_invoice_lifecycle_and_sqlite_payment_status_semantics(self):
        draft = invoice_service.create_invoice(self._payload())
        self.assertEqual(draft["status"], "draft")
        self.assertIsNone(draft["billedAt"])

        billed = invoice_service.update_invoice(
            "invoice-1",
            {"isDraft": False, "billedAt": "2026-10-07T10:00:00+00:00"},
        )
        self.assertFalse(billed["isDraft"])
        self.assertEqual(billed["billedAt"], "2026-10-07T10:00:00+00:00")
        self.assertEqual(billed["status"], "sent")

        from app.services import payment_service

        payment_service.record_payment(
            {
                "id": "payment-1",
                "invoiceId": "invoice-1",
                "clientId": "client-1",
                "amount": billed["totals"]["total"],
                "method": "cash",
                "receivedAt": "2026-10-07T10:00:00+00:00",
            }
        )
        paid = invoice_service.get_invoice("invoice-1")
        self.assertEqual(paid["totals"]["paidAmount"], billed["totals"]["total"])
        self.assertEqual(paid["status"], "paid")

        cancelled = invoice_service.update_invoice(
            "invoice-1", {"cancelledAt": "2026-10-07T10:02:00+00:00"}
        )
        self.assertEqual(cancelled["status"], "cancelled")

    def test_delete_draft_preserves_reservation_and_activity_without_reusing_number(self):
        created = invoice_service.create_invoice(self._payload())
        activity_repository = ActivityRepository(self.session_factory, self.engine)
        event = activity_repository.create(
            {
                "id": "activity-for-draft",
                "type": "invoice_created",
                "occurredAt": "2026-10-06T12:00:00+00:00",
                "summary": f"Invoice {created['number']} created",
                "clientId": "client-1",
                "invoiceId": created["id"],
            }
        )

        invoice_service.delete_invoice(created["id"])

        self.assertIsNone(self.invoice_repository.get_by_id(created["id"]))
        reservation = self.number_repository.get_by_number(created["number"])
        self.assertIsNotNone(reservation)
        self.assertIsNone(reservation["reservedFor"])
        preserved_event = activity_repository.get_by_id(event["id"])
        self.assertIsNotNone(preserved_event)
        self.assertIsNone(preserved_event["invoiceId"])

        next_number = invoice_service.reserve_invoice_number(
            created["id"],
            repository=self.number_repository,
            legacy_lookup=self.legacy_lookup,
        )
        self.assertNotEqual(next_number, created["number"])
        self.assertEqual(next_number.split("/")[0], "002")

    def test_delete_rejects_billed_invoice(self):
        created = invoice_service.create_invoice(
            self._payload(invoice_id="billed-invoice", is_draft=False)
        )

        with self.assertRaisesRegex(
            ConflictError, "Billed invoices cannot be permanently deleted"
        ):
            invoice_service.delete_invoice(created["id"])

        self.assertIsNotNone(self.invoice_repository.get_by_id(created["id"]))
        self.assertIsNotNone(self.number_repository.get_by_number(created["number"]))

    def test_delete_rejects_invoice_with_payment_history(self):
        created = invoice_service.create_invoice(self._payload(invoice_id="paid-draft"))
        self.payment_repository.create(
            {
                "id": "payment-for-draft",
                "invoiceId": created["id"],
                "clientId": "client-1",
                "amount": 1,
                "method": "cash",
                "receivedAt": "2026-10-06T12:00:00+00:00",
            },
            invoice_total_paise=100_000,
        )

        with self.assertRaisesRegex(ConflictError, "payment history"):
            invoice_service.delete_invoice(created["id"])

        self.assertIsNotNone(self.invoice_repository.get_by_id(created["id"]))
        self.assertEqual(
            self.payment_repository.list_for_invoice(created["id"])[0]["id"],
            "payment-for-draft",
        )

    def test_standalone_invoice_item_routes_use_invoice_repository(self):
        invoice_service.create_invoice(
            self._payload(items=[self._item("route-item")])
        )
        listed = invoice_item_service.list_items_for_invoice("invoice-1")
        self.assertEqual([item["id"] for item in listed], ["route-item"])

        updated = invoice_item_service.update_item(
            "route-item", {"description": "Updated service", "unitPrice": 123.45}
        )
        self.assertEqual(updated["description"], "Updated service")
        self.assertEqual(updated["unitPrice"], Decimal("123.45"))
        self.assertEqual(invoice_item_service.get_item("route-item"), updated)
        invoice_item_service.delete_item("route-item")
        self.assertEqual(invoice_item_service.list_items_for_invoice("invoice-1"), [])

    def test_api_contract_and_sqlite_number_reservation(self):
        import uuid
        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(invoices_router)
        app.include_router(invoice_items_router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        api_client = TestClient(app)

        # First, set up authentication
        from app.services.auth_service import create_user
        from app.database.session import get_db_session

        # Create a test user
        db_gen = get_db_session()
        db = next(db_gen)
        try:
            create_user(db, username=unique_username, password="TestPass123!", is_admin=True)
            db.commit()
        finally:
            next(db_gen, None)
            db.close()

        # Login to get a session token
        login_response = api_client.post(
            "/api/auth/login",
            json={"username": unique_username, "password": "TestPass123!", "remember": True}
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["token"]

        # Use authenticated client
        auth_headers = {"Authorization": f"Bearer {token}"}

        reservation_response = api_client.post(
            "/api/invoices/reserve-number", json={"invoiceId": "api-invoice"}, headers=auth_headers
        )
        self.assertEqual(reservation_response.status_code, 200)
        self.assertEqual(reservation_response.json()["number"], "001/2026-27")
        self.assertEqual(
            api_client.post(
                "/api/invoices/reserve-number", json={"invoiceId": "api-invoice"}, headers=auth_headers
            ).json()["number"],
            "001/2026-27",
        )
        payload = self._payload(invoice_id="api-invoice", items=[self._item("api-item")])

        created = api_client.post("/api/invoices", json=payload, headers=auth_headers)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["number"], "001/2026-27")
        self.assertEqual(created.json()["items"][0]["unitPrice"], 100.25)
        self.assertEqual(
            api_client.get("/api/invoices/api-invoice", headers=auth_headers).json()["id"], "api-invoice"
        )
        self.assertEqual(api_client.get("/api/invoices", headers=auth_headers).json()[0]["id"], "api-invoice")

        updated = api_client.put(
            "/api/invoices/api-invoice", json={"notes": "API update"}, headers=auth_headers
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["notes"], "API update")

        bad = api_client.post(
            "/api/invoices",
            json={
                **self._payload(invoice_id="bad-api-invoice"),
                "items": [self._item("bad-api-item", description="")],
            },
            headers=auth_headers,
        )
        self.assertEqual(bad.status_code, 422)
        self.assertIsNone(self.invoice_repository.get_by_id("bad-api-invoice"))

        deleted = api_client.delete("/api/invoices/api-invoice", headers=auth_headers)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json(), {"deleted": True, "id": "api-invoice"})
        self.assertIsNone(self.invoice_repository.get_by_id("api-invoice"))
        self.assertEqual(
            self.number_repository.get_by_number("001/2026-27")["reservedFor"],
            None,
        )
        replacement_number = api_client.post(
            "/api/invoices/reserve-number", json={"invoiceId": "api-invoice"}, headers=auth_headers
        ).json()["number"]
        self.assertEqual(replacement_number, "002/2026-27")

        billed_payload = self._payload(
            invoice_id="billed-api-invoice", is_draft=False,
            items=[self._item("billed-api-item")],
        )
        api_client.post(
            "/api/invoices/reserve-number", json={"invoiceId": "billed-api-invoice"}, headers=auth_headers
        )
        billed = api_client.post("/api/invoices", json=billed_payload, headers=auth_headers)
        self.assertEqual(billed.status_code, 201)
        blocked_delete = api_client.delete("/api/invoices/billed-api-invoice", headers=auth_headers)
        self.assertEqual(blocked_delete.status_code, 409)
        self.assertIn("Billed invoices cannot be permanently deleted", blocked_delete.json()["detail"])
        self.assertIsNotNone(self.invoice_repository.get_by_id("billed-api-invoice"))

    def test_migration_contains_only_migrated_domain_tables(self):
        tables = set(inspect(self.engine).get_table_names())
        self.assertEqual(
            tables,
            {
                "alembic_version",
                "clients",
                "invoices",
                "invoice_items",
                "invoice_number_reservations",
                "payments",
            },
        )
        self.assertNotIn("activities", tables)
        self.assertNotIn("products", tables)
        self.assertNotIn("business_profiles", tables)


if __name__ == "__main__":
    unittest.main()
