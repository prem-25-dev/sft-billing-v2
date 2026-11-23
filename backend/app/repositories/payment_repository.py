"""SQLite persistence for payments and invoice payment completion timestamps."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from threading import Lock
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Invoice, Payment
from app.database.session import (
    SessionLocal,
    engine,
    initialize_payment_database,
)

_PROOF_FIELDS = {
    "fileName": "proof_file_name",
    "mimeType": "proof_mime_type",
    "sizeBytes": "proof_size_bytes",
    "uploadedAt": "proof_uploaded_at",
    "attachmentReference": "proof_attachment_reference",
}


def to_paise(value: Any) -> int:
    return int(
        (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def from_paise(value: int) -> float:
    return float(Decimal(value) / 100)


def payment_record(payment: Payment) -> dict[str, Any]:
    proof = None
    if payment.proof_file_name is not None:
        proof = {
            "fileName": payment.proof_file_name,
            "mimeType": payment.proof_mime_type,
            "sizeBytes": payment.proof_size_bytes,
            "uploadedAt": payment.proof_uploaded_at,
            "attachmentReference": payment.proof_attachment_reference,
        }
    return {
        "id": payment.id,
        "invoiceId": payment.invoice_id,
        "clientId": payment.client_id,
        "amount": from_paise(payment.amount),
        "method": payment.method,
        "receivedAt": payment.received_at,
        "reference": payment.reference,
        "paymentProof": proof,
    }


class PaymentRepository:
    """Data access only; validation, calculations, and lifecycle stay in services."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        database_engine: Engine = engine,
    ) -> None:
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._initialized = False
        self._initialization_lock = Lock()

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if not self._initialized:
                initialize_payment_database(self._database_engine)
                self._initialized = True

    @staticmethod
    def _refresh_paid_at(
        session: Session, invoice_id: str, invoice_total_paise: int
    ) -> int:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None:
            return 0
        paid_paise = session.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice_id
            )
        )
        paid_paise = int(paid_paise or 0)
        if invoice_total_paise > 0 and paid_paise >= invoice_total_paise:
            invoice.paid_at = session.scalar(
                select(func.max(Payment.received_at)).where(
                    Payment.invoice_id == invoice_id
                )
            )
        else:
            invoice.paid_at = None
        return paid_paise

    def create(
        self, values: dict[str, Any], invoice_total_paise: int
    ) -> dict[str, Any]:
        self._ensure_schema()
        payment = Payment(
            id=values["id"],
            invoice_id=values["invoiceId"],
            client_id=values["clientId"],
            amount=to_paise(values["amount"]),
            method=values["method"],
            received_at=values["receivedAt"],
            reference=values.get("reference"),
        )
        with self._session_factory.begin() as session:
            session.add(payment)
            session.flush()
            self._refresh_paid_at(session, payment.invoice_id, invoice_total_paise)
            session.flush()
            return payment_record(payment)

    def update(
        self,
        payment_id: str,
        values: dict[str, Any],
        invoice_totals_paise: dict[str, int],
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            payment = session.get(Payment, payment_id)
            if payment is None:
                return None
            old_invoice_id = payment.invoice_id
            if "invoiceId" in values:
                payment.invoice_id = values["invoiceId"]
            if "clientId" in values:
                payment.client_id = values["clientId"]
            if "amount" in values:
                payment.amount = to_paise(values["amount"])
            if "method" in values:
                payment.method = values["method"]
            if "receivedAt" in values:
                payment.received_at = values["receivedAt"]
            if "reference" in values:
                payment.reference = values["reference"]
            session.flush()
            self._refresh_paid_at(
                session, old_invoice_id, invoice_totals_paise[old_invoice_id]
            )
            if payment.invoice_id != old_invoice_id:
                self._refresh_paid_at(
                    session,
                    payment.invoice_id,
                    invoice_totals_paise[payment.invoice_id],
                )
            session.flush()
            return payment_record(payment)

    def update_proof(
        self, payment_id: str, metadata: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            payment = session.get(Payment, payment_id)
            if payment is None:
                return None
            if metadata is None:
                for attribute in _PROOF_FIELDS.values():
                    setattr(payment, attribute, None)
            else:
                for api_field, attribute in _PROOF_FIELDS.items():
                    setattr(payment, attribute, metadata.get(api_field))
            session.flush()
            return payment_record(payment)

    def delete(
        self, payment_id: str, invoice_total_paise: int
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            payment = session.get(Payment, payment_id)
            if payment is None:
                return None
            deleted = payment_record(payment)
            invoice_id = payment.invoice_id
            session.delete(payment)
            session.flush()
            self._refresh_paid_at(session, invoice_id, invoice_total_paise)
            session.flush()
            return deleted

    def get_by_id(self, payment_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            payment = session.get(Payment, payment_id)
            return payment_record(payment) if payment is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            payments = session.scalars(
                select(Payment).order_by(Payment.received_at, Payment.id)
            ).all()
            return [payment_record(payment) for payment in payments]

    def list_for_invoice(self, invoice_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            payments = session.scalars(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.received_at, Payment.id)
            ).all()
            return [payment_record(payment) for payment in payments]

    def list_for_client(self, client_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            payments = session.scalars(
                select(Payment)
                .where(Payment.client_id == client_id)
                .order_by(Payment.received_at, Payment.id)
            ).all()
            return [payment_record(payment) for payment in payments]

    def total_paid_paise(self, invoice_id: str, exclude_payment_id: str | None = None) -> int:
        self._ensure_schema()
        with self._session_factory() as session:
            query = select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.invoice_id == invoice_id
            )
            if exclude_payment_id:
                query = query.where(Payment.id != exclude_payment_id)
            return int(session.scalar(query) or 0)

    def total_paid(self, invoice_id: str) -> float:
        return from_paise(self.total_paid_paise(invoice_id))

    def exists_by_id(self, payment_id: str) -> bool:
        return self.get_by_id(payment_id) is not None


payment_repository = PaymentRepository()