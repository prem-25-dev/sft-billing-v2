from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.session import create_database_engine, shutdown_database
from app.models.schemas import ActivityEventType
from app.repositories.activity_repository import ActivityRepository
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_number_repository import InvoiceNumberRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.routes.activities import router
from app.services import activity_service, invoice_service, payment_service
from app.services import numbering_service
from app.services.legacy_excel_numbering import LegacyReservationLookup
from app.services.legacy_excel_numbering import LegacyReservationLookup


class ActivityPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            f"sqlite:///{(Path(self.temp_dir.name) / 'activities.db').as_posix()}"
        )
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
        self.activity_repository = ActivityRepository(self.session_factory, self.engine)
        self.legacy_lookup = LegacyReservationLookup(
            Path(self.temp_dir.name) / "no-legacy-workbook.xlsx"
        )
        self.client_repository.create(self._client())
        self.invoice_repository._ensure_schema()
        self.number_repository._ensure_schema()
        self.payment_repository._ensure_schema()
        self.activity_repository._ensure_schema()
        self.invoice_repository.create(self._invoice(), [self._item()])
        self.payment_repository.create(self._payment(), 100_000)
        self._patches = [
            patch.object(activity_service, "activity_repository", self.activity_repository),
            patch.object(
                numbering_service,
                "invoice_number_repository",
                self.number_repository,
            ),
            patch.object(
                numbering_service,
                "legacy_reservation_lookup",
                self.legacy_lookup,
            ),
            patch.object(invoice_service, "client_repository", self.client_repository),
            patch.object(invoice_service, "invoice_repository", self.invoice_repository),
            patch.object(invoice_service, "payment_repository", self.payment_repository),
            patch.object(
                payment_service, "invoice_repository", self.invoice_repository
            ),
            patch.object(
                payment_service, "payment_repository", self.payment_repository
            ),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    @staticmethod
    def _client() -> dict:
        return {
            "id": "client-1",
            "name": "Test Client",
            "contactName": None,
            "email": "client@example.com",
            "phone": "123",
            "billingAddress": "Address",
            "gstin": "29AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "notes": None,
        }

    @staticmethod
    def _invoice() -> dict:
        return {
            "id": "invoice-1",
            "number": "INV-1",
            "clientId": "client-1",
            "issueDate": "2026-10-01",
            "dueDate": "2999-10-20",
            "cgstRate": 0,
            "sgstRate": 0,
            "discount": 0,
            "roundOff": 0,
            "isDraft": False,
        }

    @staticmethod
    def _item() -> dict:
        return {
            "id": "item-1",
            "description": "Service",
            "quantity": 1,
            "unitPrice": 1000,
        }

    @staticmethod
    def _payment() -> dict:
        return {
            "id": "payment-1",
            "invoiceId": "invoice-1",
            "clientId": "client-1",
            "amount": 100,
            "method": "cash",
            "receivedAt": "2026-10-07T10:00:00+00:00",
        }

    def _activity(self, activity_id: str, **values) -> dict:
        payload = {
            "type": "invoice_created",
            "occurredAt": "2026-10-07T10:00:00+00:00",
            "summary": activity_id,
            **values,
        }
        with patch.object(activity_service, "new_id", return_value=activity_id):
            return activity_service.add_activity_event(payload)

    def test_create_get_and_all_event_types_are_preserved(self) -> None:
        self.assertEqual(
            {event_type.value for event_type in ActivityEventType},
            {
                "invoice_created",
                "invoice_sent",
                "invoice_viewed",
                "invoice_became_overdue",
                "invoice_reminder_sent",
                "invoice_marked_paid",
                "payment_received",
                "client_added",
                "note_added",
            },
        )
        created = self._activity(
            "created",
            type=ActivityEventType.payment_received.value,
            summary="Payment received",
            clientId="client-1",
            invoiceId="invoice-1",
            paymentId="payment-1",
            amount=79_438.50,
        )
        self.assertEqual(activity_service.get_activity("created"), created)
        self.assertEqual(created["type"], "payment_received")
        self.assertEqual(created["amount"], 79_438.5)

    def test_amount_is_integer_paise_with_established_rounding(self) -> None:
        self._activity("amount", amount=Decimal("1.005"))
        with self.engine.connect() as connection:
            stored = connection.execute(
                text("SELECT amount FROM activities WHERE id='amount'")
            ).scalar_one()
        self.assertEqual(stored, 101)
        self.assertEqual(activity_service.get_activity("amount")["amount"], 1.01)

        self._activity("zero", amount=0)
        self.assertEqual(activity_service.get_activity("zero")["amount"], 0.0)
        self._activity("null-amount", amount=None)
        self.assertIsNone(activity_service.get_activity("null-amount")["amount"])

    def test_timestamp_ordering_filters_and_recent_activity(self) -> None:
        self._activity(
            "old", occurredAt="2026-10-05T10:00:00+00:00", clientId="client-1"
        )
        self._activity(
            "middle",
            occurredAt="2026-10-06T10:00:00+00:00",
            invoiceId="invoice-1",
        )
        self._activity(
            "new",
            occurredAt="2026-10-07T10:00:00+00:00",
            paymentId="payment-1",
        )

        self.assertEqual(
            [row["id"] for row in activity_service.list_activity()],
            ["new", "middle", "old"],
        )
        self.assertEqual(
            [row["id"] for row in activity_service.list_recent_activity(2)],
            ["new", "middle"],
        )
        self.assertEqual(
            [row["id"] for row in activity_service.list_activity_for_client("client-1")],
            ["old"],
        )
        self.assertEqual(
            [row["id"] for row in activity_service.list_activity_for_invoice("invoice-1")],
            ["middle"],
        )
        self.assertEqual(
            [row["id"] for row in activity_service.list_activity_for_payment("payment-1")],
            ["new"],
        )
        self.assertEqual(
            activity_service.get_activity("new")["occurredAt"],
            "2026-10-07T10:00:00+00:00",
        )
        parsed = datetime.fromisoformat(
            activity_service.get_activity("new")["occurredAt"]
        )
        self.assertEqual(parsed.utcoffset().total_seconds(), 0)
        with self.assertRaises(ValueError):
            activity_service.list_recent_activity(-1)

    def test_nullable_references_and_invalid_foreign_keys(self) -> None:
        self.assertEqual(self._activity("unlinked")["clientId"], None)
        self.assertEqual(
            self._activity("valid-all", clientId="client-1", invoiceId="invoice-1", paymentId="payment-1")["paymentId"],
            "payment-1",
        )
        with self.assertRaises(IntegrityError):
            self._activity("invalid-client", clientId="missing-client")
        self.assertIsNone(self.activity_repository.get_by_id("invalid-client"))
        with self.assertRaises(IntegrityError):
            self._activity("invalid-invoice", invoiceId="missing-invoice")
        with self.assertRaises(IntegrityError):
            self._activity("invalid-payment", paymentId="missing-payment")

    def test_activity_transaction_rolls_back_on_failure(self) -> None:
        with self.assertRaises(IntegrityError):
            self.activity_repository.create(
                {
                    "id": "rollback",
                    "type": "payment_received",
                    "occurredAt": "2026-10-07T10:00:00+00:00",
                    "summary": "Invalid link",
                    "clientId": "missing-client",
                }
            )
        self.assertIsNone(self.activity_repository.get_by_id("rollback"))

    def test_invoice_and_payment_producers_write_activities_to_sqlite(self) -> None:
        created_invoice = invoice_service.create_invoice(
            {
                "id": "new-invoice",
                "clientId": "client-1",
                "issueDate": "2026-10-07",
                "dueDate": "2999-10-20",
                "gst": {"cgstRate": 0, "sgstRate": 0},
                "isDraft": True,
                "items": [{"description": "New work", "quantity": 1, "unitPrice": 100}],
            }
        )
        invoice_activity = next(
            event
            for event in activity_service.list_activity()
            if event["invoiceId"] == created_invoice["id"]
        )
        self.assertEqual(invoice_activity["type"], "invoice_created")

        result = payment_service.record_payment(
            {
                "id": "new-payment",
                "invoiceId": "invoice-1",
                "clientId": "client-1",
                "amount": 10,
                "method": "cash",
                "receivedAt": "2026-10-07T12:00:00+00:00",
            }
        )
        payment_activity = next(
            event
            for event in activity_service.list_activity()
            if event["paymentId"] == result["id"]
        )
        self.assertEqual(payment_activity["type"], "payment_received")

    def test_http_activity_contract_and_deleting_entities_preserves_events(self) -> None:
        import uuid
        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        client = TestClient(app)

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
        login_response = client.post(
            "/api/auth/login",
            json={"username": unique_username, "password": "TestPass123!", "remember": True}
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["token"]

        # Use authenticated client
        auth_headers = {"Authorization": f"Bearer {token}"}

        response = client.post(
            "/api/activities",
            json={
                "type": "invoice_sent",
                "occurredAt": "2026-10-07T10:00:00+00:00",
                "summary": "Sent",
                "invoiceId": "invoice-1",
                "amount": 12.34,
            },
            headers=auth_headers,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(client.get("/api/activities", headers=auth_headers).json()[0], response.json())
        linked_event = self.activity_repository.create(
            {
                "id": "linked",
                "type": "payment_received",
                "occurredAt": "2026-10-07T10:01:00+00:00",
                "summary": "All references",
                "clientId": "client-1",
                "invoiceId": "invoice-1",
                "paymentId": "payment-1",
            }
        )

        self.payment_repository.delete("payment-1", invoice_total_paise=100_000)
        self.invoice_repository.update("invoice-1", {"isDraft": True})
        self.invoice_repository.delete("invoice-1")
        self.client_repository.delete("client-1")
        event = activity_service.get_activity(linked_event["id"])
        self.assertIsNone(event["invoiceId"])
        self.assertIsNone(event["clientId"])
        self.assertIsNone(event["paymentId"])

    def test_activity_failure_does_not_rollback_completed_invoice_operation(self) -> None:
        new_invoice_payload = {
            "id": "committed-before-activity-failure",
            "clientId": "client-1",
            "issueDate": "2026-10-07",
            "dueDate": "2999-10-20",
            "gst": {"cgstRate": 0, "sgstRate": 0},
            "isDraft": True,
            "items": [{"description": "Work", "quantity": 1, "unitPrice": 10}],
        }
        with patch.object(
            self.activity_repository,
            "create",
            side_effect=RuntimeError("activity write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "activity write failed"):
                invoice_service.create_invoice(new_invoice_payload)

        self.assertIsNotNone(
            self.invoice_repository.get_by_id("committed-before-activity-failure")
        )

    def test_activity_migration_creates_only_activity_table_including_indexes(self) -> None:
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
                "activities",
            },
        )
        self.assertNotIn("business_profiles", tables)
        self.assertNotIn("products", tables)
        self.assertEqual(
            {
                tuple(index["column_names"])
                for index in inspect(self.engine).get_indexes("activities")
            },
            {
                ("occurredAt",),
                ("clientId",),
                ("invoiceId",),
                ("paymentId",),
            },
        )


if __name__ == "__main__":
    unittest.main()
