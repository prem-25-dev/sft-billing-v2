#!/usr/bin/env python
"""
Tests for atomic cumulative payment validation.
"""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.orm import sessionmaker

from app.database.session import create_database_engine, shutdown_database
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.services import payment_service
from app.services.payment_proof_service import PaymentProofAttachmentService
from app.utils.errors import ValidationFailedError


class PaymentValidationTests(unittest.TestCase):
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
            self._invoice_values(), [self._item(1000)]
        )
        self._patches = [
            patch.object(payment_service, "invoice_repository", self.invoice_repository),
            patch.object(payment_service, "payment_repository", self.payment_repository),
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

    def test_valid_partial_payment_succeeds(self) -> None:
        """A valid partial payment should succeed."""
        result = self._record("payment-1", 300)
        self.assertEqual(result["amount"], 300)
        self.assertIsNone(result.get("paymentProof"))

    def test_payment_exactly_equal_to_remaining_balance_succeeds(self) -> None:
        """A payment exactly equal to the remaining balance should succeed."""
        self._record("payment-1", 300)
        result = self._record("payment-2", 700)
        self.assertEqual(result["amount"], 700)

    def test_payment_larger_than_remaining_balance_rejected(self) -> None:
        """A payment larger than the remaining balance should be rejected."""
        self._record("payment-1", 300)

        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-2", 800)

        self.assertIn("amount", cm.exception.errors)
        self.assertIn("exceeds remaining balance", cm.exception.errors["amount"])

    def test_multiple_payments_cannot_collectively_exceed_invoice_total(self) -> None:
        """Multiple individually valid payments cannot collectively exceed the invoice total."""
        self._record("payment-1", 400)
        self._record("payment-2", 400)

        # Third payment would exceed total (1000)
        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-3", 300)

        self.assertIn("amount", cm.exception.errors)

    def test_rejected_payment_leaves_no_extra_record(self) -> None:
        """A rejected payment should leave no extra payment record."""
        self._record("payment-1", 400)

        with self.assertRaises(ValidationFailedError):
            self._record("payment-2", 800)

        payments = self.payment_repository.list_for_invoice("invoice-1")
        self.assertEqual(len(payments), 1)
        self.assertEqual(payments[0]["id"], "payment-1")

    def test_editing_payment_does_not_double_count_original(self) -> None:
        """Editing a payment should not double-count the original payment."""
        self._record("payment-1", 400)

        # Update payment to 600 (should be valid: 600 <= 1000 remaining)
        updated = self.payment_repository.update(
            "payment-1",
            {"amount": 600},
            {"invoice-1": 100_000},
        )
        self.assertEqual(updated["amount"], 600)

        # Now try to add another payment of 500 (should fail: 600 + 500 > 1000)
        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-2", 500)

        self.assertIn("amount", cm.exception.errors)

    def test_replacement_payment_validated_correctly(self) -> None:
        """Replacing a payment should validate against remaining balance excluding the replaced payment."""
        # Create initial payment of 800
        self._record("payment-1", 800)

        # Replace with 1200 (should be valid: replacing 800 with 1200, remaining was 200, new total = 1200 <= 1000? No, should fail)
        # Wait, invoice total is 1000, so replacing 800 with 1200 would exceed
        with self.assertRaises(ValidationFailedError) as cm:
            payment_service.record_payment(self._payment("payment-1", 1200))

        self.assertIn("amount", cm.exception.errors)

        # Replace with 900 (should be valid: 900 <= 1000)
        result = payment_service.record_payment(self._payment("payment-1", 900))
        self.assertEqual(result["amount"], 900)

    def test_zero_amount_rejected(self) -> None:
        """Zero amount should be rejected."""
        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-1", 0)
        self.assertIn("amount", cm.exception.errors)

    def test_negative_amount_rejected(self) -> None:
        """Negative amount should be rejected."""
        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-1", -100)
        self.assertIn("amount", cm.exception.errors)

    def test_payment_amount_precision(self) -> None:
        """Payment amounts should be rounded to 2 decimal places."""
        result = self._record("payment-1", 100.005)  # Should round to 100.01
        self.assertEqual(result["amount"], 100.01)

    def test_concurrent_payment_simulation(self) -> None:
        """Simulate concurrent payments - second should fail if first succeeds."""
        # This simulates the race condition by checking that validation happens
        # within the transaction. In a real concurrent scenario, the database
        # would need row-level locking, but our validation checks the current
        # state at transaction start.
        self._record("payment-1", 500)

        # Now try to add 600 more (would exceed 1000)
        with self.assertRaises(ValidationFailedError):
            self._record("payment-2", 600)

    def test_payment_with_different_invoice_id_rejected(self) -> None:
        """Payment for different invoice should be rejected."""
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
        self.invoice_repository.create(
            self._invoice_values(invoice_id="invoice-2", client_id="client-2"),
            [self._item(500, item_id="item-2")],
        )

        with self.assertRaises(ValidationFailedError) as cm:
            self._record("payment-wrong-invoice", 100, invoice_id="invoice-2", client_id="client-1")

        self.assertIn("clientId", cm.exception.errors)

    def test_invoice_total_with_gst(self) -> None:
        """Test validation works with GST amounts."""
        # Create invoice with 18% GST (9% CGST + 9% SGST)
        self.invoice_repository.create(
            {
                "id": "invoice-gst",
                "number": "INV-GST",
                "clientId": "client-1",
                "issueDate": "2026-10-01",
                "dueDate": "2026-10-31",
                "cgstRate": 0.09,
                "sgstRate": 0.09,
                "discount": 0,
                "roundOff": 0,
                "isDraft": False,
            },
            [{"id": "item-gst", "description": "Service with GST", "quantity": 1, "unitPrice": 1000}],
        )

        # Invoice total should be 1000 + 90 + 90 = 1180
        result = self._record("payment-gst", 1180, invoice_id="invoice-gst")
        self.assertEqual(result["amount"], 1180)

        # Try to overpay
        with self.assertRaises(ValidationFailedError):
            self._record("payment-gst-2", 1, invoice_id="invoice-gst")


if __name__ == "__main__":
    unittest.main()