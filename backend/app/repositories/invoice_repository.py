"""SQLite persistence for invoices and their owned line items."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from threading import Lock
from typing import Any

from sqlalchemy import Engine, delete, inspect, select, text
from sqlalchemy.orm import Session, selectinload, sessionmaker

from app.database.models import (
    Client,
    InventoryMovement,
    Invoice,
    InvoiceItem,
    InvoiceNumberReservation,
    Payment,
)
from app.database.session import SessionLocal, engine, initialize_invoice_database
from app.utils.errors import ConflictError

_INVOICE_FIELDS = {
    "id": "id",
    "number": "number",
    "clientId": "client_id",
    "issueDate": "issue_date",
    "dueDate": "due_date",
    "cgstRate": "cgst_rate",
    "sgstRate": "sgst_rate",
    "discount": "discount",
    "roundOff": "round_off",
    "notes": "notes",
    "terms": "terms",
    "supplierCode": "supplier_code",
    "poNumber": "po_number",
    "poDate": "po_date",
    "transporter": "transporter",
    "isDraft": "is_draft",
    "sentAt": "sent_at",
    "viewedAt": "viewed_at",
    "paidAt": "paid_at",
    "cancelledAt": "cancelled_at",
    "billedAt": "billed_at",
    "customerNameSnapshot": "customer_name_snapshot",
    "customerAddressSnapshot": "customer_address_snapshot",
    "customerPhoneSnapshot": "customer_phone_snapshot",
    "customerEmailSnapshot": "customer_email_snapshot",
    "customerGstinSnapshot": "customer_gstin_snapshot",
    "customerPanSnapshot": "customer_pan_snapshot",
    "businessNameSnapshot": "business_name_snapshot",
    "businessLogoUrlSnapshot": "business_logo_url_snapshot",
    "businessAddressSnapshot": "business_address_snapshot",
    "businessPhoneSnapshot": "business_phone_snapshot",
    "businessEmailSnapshot": "business_email_snapshot",
    "businessGstinSnapshot": "business_gstin_snapshot",
    "businessPanSnapshot": "business_pan_snapshot",
    "businessBankAccountHolderSnapshot": "business_bank_account_holder_snapshot",
    "businessBankNameSnapshot": "business_bank_name_snapshot",
    "businessBankBranchSnapshot": "business_bank_branch_snapshot",
    "businessBankAccountNumberSnapshot": "business_bank_account_number_snapshot",
    "businessBankIfscSnapshot": "business_bank_ifsc_snapshot",
    "businessDeclarationSnapshot": "business_declaration_snapshot",
    "authorizedSignatureReferenceSnapshot": "authorized_signature_reference_snapshot",
}
_ITEM_FIELDS = {
    "id": "id",
    "invoiceId": "invoice_id",
    "productId": "product_id",
    "description": "description",
    "hsnCode": "hsn_code",
    "quantity": "quantity",
    "unitPrice": "unit_price",
}
_MONEY_INVOICE_FIELDS = {"discount", "roundOff"}
_MONEY_ITEM_FIELDS = {"unitPrice"}


def _to_paise(value: Any) -> int:
    return int(
        (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _from_paise(value: int) -> Decimal:
    return Decimal(value) / 100


def _mapped_values(
    values: dict[str, Any],
    fields: dict[str, str],
    money_fields: set[str] | None = None,
) -> dict[str, Any]:
    money_fields = money_fields or set()
    return {
        attribute: _to_paise(value) if api_field in money_fields else value
        for api_field, attribute in fields.items()
        if api_field in values
        for value in (values[api_field],)
    }


def _item_record(item: InvoiceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "invoiceId": item.invoice_id,
        "productId": item.product_id,
        "description": item.description,
        "hsnCode": item.hsn_code,
        "quantity": item.quantity,
        "unitPrice": _from_paise(item.unit_price),
    }


def _invoice_record(invoice: Invoice, *, include_items: bool = True) -> dict[str, Any]:
    record = {
        api_field: getattr(invoice, attribute)
        for api_field, attribute in _INVOICE_FIELDS.items()
    }
    record["discount"] = _from_paise(invoice.discount)
    record["roundOff"] = _from_paise(invoice.round_off)
    if include_items:
        record["items"] = [_item_record(item) for item in invoice.items]
    return record


class InvoiceRepository:
    """Persistence operations; invoice validation and lifecycle stay in services."""

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
                initialize_invoice_database(self._database_engine)
                self._initialized = True

    @staticmethod
    def _invoice_query():
        return select(Invoice).options(selectinload(Invoice.items)).order_by(text("rowid"))

    @staticmethod
    def _make_items(invoice_id: str, items: list[dict[str, Any]]) -> list[InvoiceItem]:
        prepared: list[InvoiceItem] = []
        for item in items:
            values = _mapped_values(item, _ITEM_FIELDS, _MONEY_ITEM_FIELDS)
            values["invoice_id"] = invoice_id
            prepared.append(InvoiceItem(**values))
        return prepared

    def create(
        self, values: dict[str, Any], items: list[dict[str, Any]], session: Session | None = None
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        if session is not None:
            invoice_values = _mapped_values(values, _INVOICE_FIELDS, _MONEY_INVOICE_FIELDS)
            invoice = Invoice(**invoice_values)
            session.add(invoice)
            invoice.items.extend(self._make_items(invoice.id, items))
            session.flush()
            return _invoice_record(invoice)
        with self._session_factory.begin() as new_session:
            invoice_values = _mapped_values(values, _INVOICE_FIELDS, _MONEY_INVOICE_FIELDS)
            invoice = Invoice(**invoice_values)
            new_session.add(invoice)
            invoice.items.extend(self._make_items(invoice.id, items))
            new_session.flush()
            return _invoice_record(invoice)

    def get_by_id(self, invoice_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            invoice = session.scalar(
                self._invoice_query().where(Invoice.id == invoice_id)
            )
            return _invoice_record(invoice) if invoice is not None else None

    def get_by_number(self, number: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            invoice = session.scalar(
                self._invoice_query().where(Invoice.number == number)
            )
            return _invoice_record(invoice) if invoice is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            invoices = session.scalars(self._invoice_query()).all()
            return [_invoice_record(invoice) for invoice in invoices]

    def update(
        self,
        invoice_id: str,
        values: dict[str, Any],
        items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            invoice = session.scalar(
                self._invoice_query().where(Invoice.id == invoice_id)
            )
            if invoice is None:
                return None

            changes = _mapped_values(values, _INVOICE_FIELDS, _MONEY_INVOICE_FIELDS)
            for attribute, value in changes.items():
                setattr(invoice, attribute, value)

            if items is not None:
                session.execute(
                    delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
                )
                session.flush()
                session.expire(invoice, ["items"])
                invoice.items.extend(self._make_items(invoice_id, items))

            session.flush()
            return _invoice_record(invoice)

    def delete(self, invoice_id: str) -> bool:
        self._ensure_schema()
        existing_tables = set(inspect(self._database_engine).get_table_names())
        with self._session_factory.begin() as session:
            invoice = session.get(Invoice, invoice_id)
            if invoice is None:
                return False
            if not invoice.is_draft:
                raise ConflictError(
                    "Billed invoices cannot be permanently deleted. No cancellation or correction workflow is available here."
                )
            if any(
                (
                    invoice.billed_at,
                    invoice.sent_at,
                    invoice.viewed_at,
                    invoice.paid_at,
                    invoice.cancelled_at,
                )
            ):
                raise ConflictError(
                    "This draft invoice has billing, delivery, payment, or cancellation history and cannot be deleted."
                )
            if "payments" in existing_tables and session.scalar(
                select(Payment.id).where(Payment.invoice_id == invoice_id).limit(1)
            ) is not None:
                raise ConflictError(
                    "This invoice has payment history and cannot be deleted."
                )
            if "inventory_movements" in existing_tables and session.scalar(
                select(InventoryMovement.id)
                .where(InventoryMovement.invoice_id == invoice_id)
                .limit(1)
            ) is not None:
                raise ConflictError(
                    "This invoice has inventory history and cannot be deleted."
                )
            if "invoice_number_reservations" in existing_tables:
                reservation = session.scalar(
                    select(InvoiceNumberReservation).where(
                        InvoiceNumberReservation.reserved_for == invoice_id
                    )
                )
                if reservation is not None:
                    reservation.reserved_for = None
            session.execute(
                delete(InvoiceItem).where(InvoiceItem.invoice_id == invoice_id)
            )
            session.delete(invoice)
            session.flush()
            return True

    def exists_by_id(self, invoice_id: str) -> bool:
        self._ensure_schema()
        with self._session_factory() as session:
            return session.scalar(
                select(Invoice.id).where(Invoice.id == invoice_id).limit(1)
            ) is not None

    def list_items_for_invoice(self, invoice_id: str) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            items = session.scalars(
                select(InvoiceItem)
                .where(InvoiceItem.invoice_id == invoice_id)
                .order_by(text("rowid"))
            ).all()
            return [_item_record(item) for item in items]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            item = session.get(InvoiceItem, item_id)
            return _item_record(item) if item is not None else None

    def create_item(
        self, invoice_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            invoice = session.get(Invoice, invoice_id)
            if invoice is None:
                return None
            item_values = _mapped_values(values, _ITEM_FIELDS, _MONEY_ITEM_FIELDS)
            item_values["invoice_id"] = invoice_id
            item = InvoiceItem(**item_values)
            session.add(item)
            session.flush()
            return _item_record(item)

    def update_item(
        self, item_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            item = session.get(InvoiceItem, item_id)
            if item is None:
                return None
            for attribute, value in _mapped_values(
                values, _ITEM_FIELDS, _MONEY_ITEM_FIELDS
            ).items():
                if attribute != "invoice_id":
                    setattr(item, attribute, value)
            session.flush()
            return _item_record(item)

    def delete_item(self, item_id: str) -> bool:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            item = session.get(InvoiceItem, item_id)
            if item is None:
                return False
            session.delete(item)
            session.flush()
            return True


invoice_repository = InvoiceRepository()
