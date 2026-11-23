from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.session import create_database_engine, shutdown_database
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import (
    PaymentRepository,
    to_paise,
)
from app.services import invoice_service, payment_service
from app.services.payment_proof_service import (
    AttachmentEnrichmentError,
    AttachmentReadbackError,
    AttachmentWriteError,
    PaymentProofAttachmentService,
)
from app.utils.errors import NotFoundError, ValidationFailedError


class PaymentPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_database_engine(
            f"sqlite:///{(Path(self.temp_dir.name) / 'payments.db').as_posix()}"
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.client_repository = ClientRepository(self.session_factory, self.engine)
        self.invoice_repository = InvoiceRepository(self.session_factory, self.engine)
        self.payment_repository = PaymentRepository(self.session_factory, self.engine)
        self.client_repository.create(
            {
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
        )
        self.invoice_repository._ensure_schema()
        self.payment_repository._ensure_schema()
        self.proof_service = PaymentProofAttachmentService(
            Path(self.temp_dir.name) / "proofs"
        )
        self.invoice_repository.create(
            self._invoice_values(), [self._item()]
        )
        self._patches = [
            patch.object(payment_service, "invoice_repository", self.invoice_repository),
            patch.object(payment_service, "payment_repository", self.payment_repository),
            patch.object(invoice_service, "invoice_repository", self.invoice_repository),
            patch.object(invoice_service, "payment_repository", self.payment_repository),
            patch.object(payment_service.activity_service, "add_activity_event"),
            patch.object(
                payment_service,
                "get_payment_proof_service",
                return_value=self.proof_service,
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
    def _invoice_values(
        invoice_id: str = "invoice-1",
        client_id: str = "client-1",
        *,
        amount: float = 1000,
        due_date: str = "2999-10-20",
    ) -> dict:
        return {
            "id": invoice_id,
            "number": f"INV-{invoice_id}",
            "clientId": client_id,
            "issueDate": "2026-10-01",
            "dueDate": due_date,
            "cgstRate": 0,
            "sgstRate": 0,
            "discount": 0,
            "roundOff": 0,
            "isDraft": False,
        }

    @staticmethod
    def _item(amount: float = 1000, item_id: str = "item-1") -> dict:
        return {
            "id": item_id,
            "description": "Service",
            "quantity": 1,
            "unitPrice": amount,
        }

    @staticmethod
    def _payment(
        payment_id: str,
        amount: float,
        *,
        invoice_id: str = "invoice-1",
        client_id: str = "client-1",
        received_at: str = "2026-10-07T10:00:00+00:00",
    ) -> dict:
        return {
            "id": payment_id,
            "invoiceId": invoice_id,
            "clientId": client_id,
            "amount": amount,
            "method": "upi",
            "receivedAt": received_at,
            "reference": None,
        }

    def _record(self, payment_id: str, amount: float, **kwargs):
        return payment_service.record_payment(
            self._payment(payment_id, amount, **kwargs)
        )

    def test_create_get_list_filter_and_delete_payment(self) -> None:
        created = self._record("payment-1", 125.50)
        self.assertEqual(created["amount"], 125.5)
        self.assertIsNone(created["paymentProof"])
        self.assertEqual(payment_service.get_payment("payment-1"), created)
        self.assertEqual(payment_service.list_payments(), [created])
        self.assertEqual(payment_service.list_payments_for_invoice("invoice-1"), [created])

        payment_service.delete_payment("payment-1")
        self.assertEqual(payment_service.list_payments(), [])
        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1")["paidAt"])

    def test_amount_is_integer_paise_and_rounds_half_up(self) -> None:
        self.assertEqual(to_paise(Decimal("79438.50")), 7_943_850)
        self.assertEqual(to_paise(Decimal("1.005")), 101)
        self.assertEqual(to_paise(0), 0)
        self._record("payment-money", 1.005)
        with self.engine.connect() as connection:
            stored = connection.execute(
                text("SELECT amount FROM payments WHERE id='payment-money'")
            ).scalar_one()
        self.assertEqual(stored, 101)
        self.assertEqual(payment_service.get_payment("payment-money")["amount"], 1.01)

    def test_nonexistent_invoice_and_mismatched_client_are_rejected(self) -> None:
        with self.assertRaises(NotFoundError):
            payment_service.record_payment(
                self._payment("no-invoice", 10, invoice_id="not-present")
            )
        with self.assertRaises(ValidationFailedError):
            self._record("wrong-client", 10, client_id="other-client")

        with self.assertRaises(IntegrityError):
            self.payment_repository.create(
                self._payment("bad-fk", 10, invoice_id="not-present"),
                invoice_total_paise=100_000,
            )
        self.assertIsNone(self.payment_repository.get_by_id("bad-fk"))

    def test_database_rejects_payment_with_client_different_from_invoice_client(self) -> None:
        self.client_repository.create(
            {
                "id": "client-2",
                "name": "Other Client",
                "contactName": None,
                "email": "other@example.com",
                "phone": "456",
                "billingAddress": "Other Address",
                "gstin": "27AAAAA0000A1Z7",
                "pan": "AAAAA0000B",
                "notes": None,
            }
        )
        with self.assertRaises(IntegrityError):
            self.payment_repository.create(
                self._payment("mismatch", 10, client_id="client-2"),
                invoice_total_paise=100_000,
            )
        self.assertIsNone(self.payment_repository.get_by_id("mismatch"))
        with self.assertRaises(IntegrityError):
            self.payment_repository.create(
                self._payment("missing-client", 10, client_id="not-a-client"),
                invoice_total_paise=100_000,
            )

    def test_multiple_payments_derive_paid_and_remaining_amounts(self) -> None:
        self.invoice_repository.update(
            "invoice-1",
            {},
            [self._item(79_438)],
        )
        self._record("payment-a", 30_000, received_at="2026-10-07T10:00:00+00:00")
        partial = invoice_service.get_invoice("invoice-1")
        self.assertEqual(partial["totals"]["paidAmount"], 30_000)
        self.assertEqual(partial["totals"]["balanceDue"], 49_438)
        self.assertEqual(partial["status"], "partially_paid")

        self._record("payment-b", 49_438, received_at="2026-10-08T10:00:00+00:00")
        paid = invoice_service.get_invoice("invoice-1")
        self.assertEqual(paid["totals"]["paidAmount"], 79_438)
        self.assertEqual(paid["totals"]["balanceDue"], 0)
        self.assertEqual(paid["status"], "paid")
        self.assertEqual(
            self.invoice_repository.get_by_id("invoice-1")["paidAt"],
            "2026-10-08T10:00:00+00:00",
        )

    def test_paid_at_tracks_full_payment_and_clears_after_delete(self) -> None:
        self._record("full", 1000, received_at="2026-10-07T11:00:00+00:00")
        self.assertEqual(
            self.invoice_repository.get_by_id("invoice-1")["paidAt"],
            "2026-10-07T11:00:00+00:00",
        )
        payment_service.delete_payment("full")
        invoice = invoice_service.get_invoice("invoice-1")
        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1")["paidAt"])
        self.assertEqual(invoice["status"], "sent")
        self.assertEqual(invoice["totals"]["paidAmount"], 0)

    def test_paid_at_clears_when_payment_amount_is_reduced(self) -> None:
        self._record("reduce-me", 1000)
        updated = self.payment_repository.update(
            "reduce-me",
            {"amount": 500},
            {"invoice-1": 100_000},
        )
        self.assertEqual(updated["amount"], 500)
        invoice = invoice_service.get_invoice("invoice-1")
        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1")["paidAt"])
        self.assertEqual(invoice["status"], "partially_paid")
        self.assertEqual(invoice["totals"]["balanceDue"], 500)

    def test_deleting_one_of_multiple_payments_reverts_paid_invoice_to_partial(self) -> None:
        self._record("part-a", 500, received_at="2026-10-07T10:00:00+00:00")
        self._record("part-b", 500, received_at="2026-10-08T10:00:00+00:00")
        self.assertEqual(invoice_service.get_invoice("invoice-1")["status"], "paid")

        payment_service.delete_payment("part-b")
        invoice = invoice_service.get_invoice("invoice-1")
        self.assertEqual(invoice["status"], "partially_paid")
        self.assertEqual(invoice["totals"]["paidAmount"], 500)
        self.assertEqual(invoice["totals"]["balanceDue"], 500)
        self.assertIsNone(self.invoice_repository.get_by_id("invoice-1")["paidAt"])

    def test_proof_metadata_round_trip_unique_non_null_and_multiple_nulls(self) -> None:
        first = self._record("proof-1", 100)
        second = self._record("proof-2", 100)
        self.assertIsNone(first["paymentProof"])
        self.assertIsNone(second["paymentProof"])

        proof = {
            "fileName": "receipt.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 12,
            "uploadedAt": "2026-10-07T10:00:00+00:00",
            "attachmentReference": "proof-1/token",
        }
        persisted = self.payment_repository.update_proof("proof-1", proof)
        self.assertEqual(persisted["paymentProof"], proof)
        with self.assertRaises(IntegrityError):
            self.payment_repository.update_proof(
                "proof-2",
                {**proof, "fileName": "duplicate.pdf"},
            )
        self.assertIsNone(
            self.payment_repository.get_by_id("proof-2")["paymentProof"]
        )

    def test_payment_creation_transaction_rolls_back_on_failure(self) -> None:
        with self.assertRaises(IntegrityError):
            self.payment_repository.create(
                self._payment(
                    "should-rollback",
                    100,
                    invoice_id="missing-invoice",
                    received_at="2026-10-09T10:00:00+00:00",
                ),
                invoice_total_paise=100_000,
            )
        self.assertIsNone(self.payment_repository.get_by_id("should-rollback"))

    def test_proof_upload_uses_filesystem_and_replacement_cleans_only_prior_file(self) -> None:
        first = payment_service.record_payment(
            {
                **self._payment("proof-file", 100),
                "_proof_upload": {
                    "fileName": "prior.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": 5,
                    "content": b"prior",
                },
            }
        )
        first_payment = first["payment"]
        prior_reference = first_payment["paymentProof"]["attachmentReference"]
        prior_path = self.proof_service._root / prior_reference
        self.assertTrue(prior_path.is_file())

        replacement = payment_service.record_payment(
            {
                **self._payment("proof-file", 100),
                "_proof_upload": {
                    "fileName": "next.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": 4,
                    "content": b"next",
                },
            }
        )
        replacement_payment = replacement["payment"]
        next_reference = replacement_payment["paymentProof"]["attachmentReference"]
        self.assertNotEqual(next_reference, prior_reference)
        self.assertFalse(prior_path.exists())
        self.assertTrue((self.proof_service._root / next_reference).is_file())

        self._record("unrelated-payment", 100)
        unrelated = payment_service.record_payment(
            {
                **self._payment("unrelated-payment", 100),
                "_proof_upload": {
                    "fileName": "unrelated.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": 9,
                    "content": b"unrelated",
                },
            }
        )["payment"]
        unrelated_path = (
            self.proof_service._root
            / unrelated["paymentProof"]["attachmentReference"]
        )
        payment_service.delete_payment("proof-file")
        self.assertFalse((self.proof_service._root / next_reference).exists())
        self.assertTrue(unrelated_path.is_file())

    def test_proof_failure_keeps_durable_payment_and_emits_activity_once(self) -> None:
        failing = Mock()
        failing.replace.side_effect = AttachmentWriteError(
            "safe write failure",
            category="write_failed",
            stage="write",
            retryable=True,
        )
        with patch.object(payment_service, "get_payment_proof_service", return_value=failing), patch.object(
            payment_service.activity_service, "add_activity_event"
        ) as activity:
            result = payment_service.record_payment(
                {
                    **self._payment("durable-proof-failure", 100),
                    "_proof_upload": {
                        "fileName": "receipt.pdf",
                        "mimeType": "application/pdf",
                        "sizeBytes": 1,
                        "content": b"x",
                    },
                }
            )
        self.assertEqual(result["payment"]["id"], "durable-proof-failure")
        self.assertEqual(result["proofError"]["stage"], "write")
        self.assertIsNotNone(
            self.payment_repository.get_by_id("durable-proof-failure")
        )
        activity.assert_called_once()

    def test_migration_adds_only_payments_table(self) -> None:
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
        self.assertNotIn("business_profiles", tables)
        self.assertNotIn("products", tables)


if __name__ == "__main__":
    unittest.main()
