"""Invoice CRUD, including its owned InvoiceItems rows and derived totals/status.

An Invoice returned from this service always includes `items` (joined
from SQLite) and `totals`/`status` (computed fresh from calculation_service).
Payment data and activity logging remain Excel-backed compatibility boundaries.
"""
from __future__ import annotations

from typing import Any

from app.excel.workbook import workbook_lock
from app.repositories.client_repository import client_repository
from app.repositories.invoice_repository import invoice_repository
from app.repositories.payment_repository import payment_repository
from app.services import activity_service
from app.services.calculation_service import compute_invoice_status, compute_invoice_totals
from app.services.numbering_service import (
    get_reserved_invoice_number,
    reserve_invoice_number,
)
from app.utils.errors import ConflictError, NotFoundError, ValidationFailedError
from app.utils.validators import is_valid_iso_date, new_id, now_iso


def _validate_header(payload: dict[str, Any], partial: bool = False) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not partial or "clientId" in payload:
        if not payload.get("clientId"):
            errors["clientId"] = "Select a client."
    if not partial or "issueDate" in payload:
        if not payload.get("issueDate") or not is_valid_iso_date(payload["issueDate"]):
            errors["issueDate"] = "Issue date must be a valid date."
    if not partial or "dueDate" in payload:
        if not payload.get("dueDate") or not is_valid_iso_date(payload["dueDate"]):
            errors["dueDate"] = "Due date must be a valid date."
    gst = payload.get("gst")
    if gst is not None:
        cgst = gst.get("cgstRate")
        sgst = gst.get("sgstRate")
        if cgst is None or not (0 <= cgst <= 1):
            errors["gst.cgstRate"] = "CGST rate must be between 0 and 1 (e.g. 0.09 for 9%)."
        if sgst is None or not (0 <= sgst <= 1):
            errors["gst.sgstRate"] = "SGST rate must be between 0 and 1 (e.g. 0.09 for 9%)."
    discount = payload.get("discount")
    if discount is not None and discount < 0:
        errors["discount"] = "Discount can't be negative."
    return errors


def _validate_items(items: list[dict[str, Any]]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not items:
        errors["items"] = "Add at least one line item."
        return errors
    for index, item in enumerate(items):
        if not (item.get("description") or "").strip():
            errors[f"items[{index}].description"] = "Description is required."
        quantity = item.get("quantity")
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            errors[f"items[{index}].quantity"] = "Quantity must be a number greater than zero."
        unit_price = item.get("unitPrice")
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            errors[f"items[{index}].unitPrice"] = "Unit price must be a non-negative number."
    return errors


def _client_exists(client_id: str) -> bool:
    return client_repository.exists_by_id(client_id)


def _hydrate(invoice_row: dict[str, Any]) -> dict[str, Any]:
    items = invoice_row["items"]
    paid_amount = payment_repository.total_paid(invoice_row["id"])
    totals = compute_invoice_totals(
        items=items,
        cgst_rate=float(invoice_row["cgstRate"]),
        sgst_rate=float(invoice_row["sgstRate"]),
        discount=float(invoice_row["discount"] or 0),
        round_off=float(invoice_row["roundOff"] or 0),
        paid_amount=paid_amount,
    )
    status = compute_invoice_status(
        is_draft=bool(invoice_row["isDraft"]),
        cancelled_at=invoice_row.get("cancelledAt"),
        paid_at=invoice_row.get("paidAt"),
        paid_amount=paid_amount,
        total=totals["total"],
        due_date=invoice_row["dueDate"],
    )
    return {
        "id": invoice_row["id"],
        "number": invoice_row["number"],
        "clientId": invoice_row["clientId"],
        "issueDate": invoice_row["issueDate"],
        "dueDate": invoice_row["dueDate"],
        "gst": {"cgstRate": float(invoice_row["cgstRate"]), "sgstRate": float(invoice_row["sgstRate"])},
        "discount": float(invoice_row["discount"] or 0),
        "roundOff": float(invoice_row["roundOff"] or 0),
        "notes": invoice_row.get("notes"),
        "terms": invoice_row.get("terms"),
        "supplierCode": invoice_row.get("supplierCode"),
        "poNumber": invoice_row.get("poNumber"),
        "poDate": invoice_row.get("poDate"),
        "transporter": invoice_row.get("transporter"),
        "items": [
            {
                "id": i["id"],
                "invoiceId": i["invoiceId"],
                "productId": i.get("productId"),
                "description": i["description"],
                "hsnCode": i.get("hsnCode"),
                "quantity": float(i["quantity"]),
                "unitPrice": float(i["unitPrice"]),
            }
            for i in items
        ],
        "isDraft": bool(invoice_row["isDraft"]),
        "sentAt": invoice_row.get("sentAt"),
        "billedAt": invoice_row.get("billedAt"),
        "viewedAt": invoice_row.get("viewedAt"),
        "paidAt": invoice_row.get("paidAt"),
        "cancelledAt": invoice_row.get("cancelledAt"),
        "status": status,
        "totals": totals,
    }


def list_invoices() -> list[dict[str, Any]]:
    return [_hydrate(row) for row in invoice_repository.list_all()]


def get_invoice(invoice_id: str) -> dict[str, Any]:
    invoice = invoice_repository.get_by_id(invoice_id)
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return _hydrate(invoice)


def list_invoices_for_client(client_id: str) -> list[dict[str, Any]]:
    return [inv for inv in list_invoices() if inv["clientId"] == client_id]


def _create_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    header_errors = _validate_header(payload)
    items = payload.get("items") or []
    item_errors = _validate_items(items)
    errors = {**header_errors, **item_errors}
    if "gst" not in payload or payload.get("gst") is None:
        errors["gst"] = "GST rates are required."
    if errors:
        raise ValidationFailedError(errors)

    if not _client_exists(payload["clientId"]):
        raise NotFoundError(f"Client {payload['clientId']} not found.")

    invoice_id = payload.get("id") or new_id("iv")
    reserved = get_reserved_invoice_number(invoice_id)
    if reserved is None and payload.get("number"):
        raise ConflictError("Invoice number must be reserved by the server.")
    is_draft = bool(payload.get("isDraft", True))
    invoice_row = {
        "id": invoice_id,
        "clientId": payload["clientId"],
        "issueDate": payload["issueDate"],
        "dueDate": payload["dueDate"],
        "cgstRate": payload["gst"]["cgstRate"],
        "sgstRate": payload["gst"]["sgstRate"],
        "discount": payload.get("discount", 0) or 0,
        "roundOff": payload.get("roundOff", 0) or 0,
        "notes": payload.get("notes"),
        "terms": payload.get("terms"),
        "supplierCode": payload.get("supplierCode"),
        "poNumber": payload.get("poNumber"),
        "poDate": payload.get("poDate"),
        "transporter": payload.get("transporter"),
        "isDraft": is_draft,
        # Billing is distinct from sending. A billed invoice gets billedAt,
        # while sentAt remains unset until the explicit send action.
        "billedAt": None if is_draft else payload.get("billedAt") or now_iso(),
        "sentAt": payload.get("sentAt"),
        "viewedAt": None,
        "paidAt": None,
        "cancelledAt": None,
    }
    for key, value in payload.items():
        if key.endswith("Snapshot"):
            invoice_row[key] = value
    item_rows = [
        {
            "id": item.get("id") or new_id("li"),
            "invoiceId": invoice_id,
            "productId": item.get("productId"),
            "description": item["description"].strip(),
            "hsnCode": item.get("hsnCode"),
            "quantity": float(item["quantity"]),
            "unitPrice": item["unitPrice"],
        }
        for item in items
    ]

    # Reserve number and create invoice in a single transaction to avoid ghost reservations.
    with invoice_repository._session_factory.begin() as session:
        number = reserved or reserve_invoice_number(invoice_id, session=session)
        invoice_row["number"] = number
        created = invoice_repository.create(invoice_row, item_rows, session=session)
        if created is None:
            raise NotFoundError(f"Client {payload['clientId']} not found.")

    # Activity persistence remains in the legacy Excel-backed subsystem.
    activity_service.add_activity_event({
        "type": "invoice_created",
        "summary": f"Invoice {number} created",
        "clientId": payload["clientId"],
        "invoiceId": invoice_id,
    })
    return _hydrate(created)


def create_invoice(payload: dict[str, Any]) -> dict[str, Any]:
    with workbook_lock():
        return _create_invoice(payload)


def update_invoice(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    current = invoice_repository.get_by_id(invoice_id)
    if current is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")

    header_errors = _validate_header(payload, partial=True)
    items = payload.get("items")
    item_errors = _validate_items(items) if items is not None else {}
    errors = {**header_errors, **item_errors}
    if errors:
        raise ValidationFailedError(errors)

    if payload.get("clientId") and not _client_exists(payload["clientId"]):
        raise NotFoundError(f"Client {payload['clientId']} not found.")

    updated = dict(current)
    simple_fields = [
        "clientId", "issueDate", "dueDate", "discount", "roundOff",
        "notes", "terms", "supplierCode", "poNumber", "poDate", "transporter",
    ]
    for field in simple_fields:
        if field in payload and payload[field] is not None:
            updated[field] = payload[field]
    if payload.get("gst"):
        updated["cgstRate"] = payload["gst"]["cgstRate"]
        updated["sgstRate"] = payload["gst"]["sgstRate"]

    was_draft = bool(current["isDraft"])
    if "isDraft" in payload and payload["isDraft"] is not None:
        updated["isDraft"] = payload["isDraft"]
        if was_draft and not payload["isDraft"] and not updated.get("billedAt"):
            updated["billedAt"] = payload.get("billedAt") or now_iso()
    if "sentAt" in payload and payload["sentAt"] is not None:
        updated["sentAt"] = payload["sentAt"]
    if "cancelledAt" in payload and payload["cancelledAt"] is not None:
        updated["cancelledAt"] = payload["cancelledAt"]

    for key, value in payload.items():
        if key.endswith("Snapshot"):
            updated[key] = value
    item_rows = None
    if items is not None:
        item_rows = [
            {
                "id": item.get("id") or new_id("li"),
                "invoiceId": invoice_id,
                "productId": item.get("productId"),
                "description": item["description"].strip(),
                "hsnCode": item.get("hsnCode"),
                "quantity": float(item["quantity"]),
                "unitPrice": item["unitPrice"],
            }
            for item in items
        ]
    persisted = invoice_repository.update(invoice_id, updated, item_rows)
    if persisted is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return _hydrate(persisted)


def delete_invoice(invoice_id: str) -> None:
    if not invoice_repository.delete(invoice_id):
        raise NotFoundError(f"Invoice {invoice_id} not found.")


def clear_invoice_history(confirmation_token: str) -> dict[str, int]:
    """
    Clear all invoice history while preserving clients and products.

    This operation is irreversible and requires explicit confirmation.
    Deletes: invoices, invoice_items, payments, inventory_movements linked to invoices,
    invoice_number_reservations, and activities linked to invoices.

    Preserves: clients, products, product stock, inventory balances, workspace settings,
    business profile, and unrelated activity logs.

    Args:
        confirmation_token: Must be exactly "CLEAR_INVOICE_HISTORY" to confirm

    Returns:
        Dictionary with counts of deleted records
    """
    if confirmation_token != "CLEAR_INVOICE_HISTORY":
        raise ValidationFailedError(
            {"confirmation": "Invalid confirmation token. Must be 'CLEAR_INVOICE_HISTORY'."}
        )

    from app.database.session import SessionLocal
    from app.database.models import (
        Invoice, InvoiceItem, Payment, InventoryMovement,
        InvoiceNumberReservation, Activity
    )
    from sqlalchemy import delete, func, select

    deleted_counts = {
        "invoices": 0,
        "invoice_items": 0,
        "payments": 0,
        "inventory_movements": 0,
        "invoice_number_reservations": 0,
        "activities": 0,
    }

    with SessionLocal.begin() as session:
        # Get all invoice IDs first
        invoice_ids = [row[0] for row in session.execute(select(Invoice.id)).all()]

        if not invoice_ids:
            return deleted_counts

        # 1. Delete invoice_items (FK to invoices with RESTRICT)
        result = session.execute(delete(InvoiceItem).where(InvoiceItem.invoice_id.in_(invoice_ids)))
        deleted_counts["invoice_items"] = result.rowcount

        # 2. Delete payments (FK constraint on invoiceId+clientId with RESTRICT)
        result = session.execute(delete(Payment).where(Payment.invoice_id.in_(invoice_ids)))
        deleted_counts["payments"] = result.rowcount

        # 3. Delete inventory_movements linked to invoices (FK with RESTRICT)
        result = session.execute(
            delete(InventoryMovement).where(InventoryMovement.invoice_id.in_(invoice_ids))
        )
        deleted_counts["inventory_movements"] = result.rowcount

        # 4. Delete invoice_number_reservations for these invoices
        result = session.execute(
            delete(InvoiceNumberReservation).where(
                InvoiceNumberReservation.reserved_for.in_(invoice_ids)
            )
        )
        deleted_counts["invoice_number_reservations"] = result.rowcount

        # 5. Delete activities linked to invoices (FK with SET NULL, but we want clean history)
        result = session.execute(delete(Activity).where(Activity.invoice_id.in_(invoice_ids)))
        deleted_counts["activities"] = result.rowcount

        # 6. Finally delete all invoices
        result = session.execute(delete(Invoice).where(Invoice.id.in_(invoice_ids)))
        deleted_counts["invoices"] = result.rowcount

        # Session will commit on exit from context manager

    return deleted_counts
