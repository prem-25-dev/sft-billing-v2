"""Standalone InvoiceItem CRUD backed by the Invoice SQLite repository."""
from __future__ import annotations

from typing import Any

from app.repositories.invoice_repository import invoice_repository
from app.utils.errors import NotFoundError, ValidationFailedError
from app.utils.validators import new_id


def _validate(payload: dict[str, Any], partial: bool = False) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not partial or "description" in payload:
        if not (payload.get("description") or "").strip():
            errors["description"] = "Description is required."
    if not partial or "quantity" in payload:
        quantity = payload.get("quantity")
        if not isinstance(quantity, (int, float)) or quantity <= 0:
            errors["quantity"] = "Quantity must be a number greater than zero."
    if not partial or "unitPrice" in payload:
        unit_price = payload.get("unitPrice")
        if not isinstance(unit_price, (int, float)) or unit_price < 0:
            errors["unitPrice"] = "Unit price must be a non-negative number."
    return errors


def list_items_for_invoice(invoice_id: str) -> list[dict[str, Any]]:
    if not invoice_repository.exists_by_id(invoice_id):
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return invoice_repository.list_items_for_invoice(invoice_id)


def get_item(item_id: str) -> dict[str, Any]:
    item = invoice_repository.get_item(item_id)
    if item is None:
        raise NotFoundError(f"Invoice item {item_id} not found.")
    return item


def create_item(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    errors = _validate(payload)
    if errors:
        raise ValidationFailedError(errors)

    row = {
        "id": payload.get("id") or new_id("li"),
        "invoiceId": invoice_id,
        "productId": payload.get("productId"),
        "description": payload["description"].strip(),
        "hsnCode": payload.get("hsnCode"),
        "quantity": float(payload["quantity"]),
        "unitPrice": payload["unitPrice"],
    }
    item = invoice_repository.create_item(invoice_id, row)
    if item is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return item


def update_item(item_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    errors = _validate(payload, partial=True)
    if errors:
        raise ValidationFailedError(errors)

    changes = {
        field: payload[field]
        for field in ("productId", "description", "hsnCode", "quantity", "unitPrice")
        if field in payload and payload[field] is not None
    }
    if "description" in changes:
        changes["description"] = changes["description"].strip()
    if "quantity" in changes:
        changes["quantity"] = float(changes["quantity"])

    item = invoice_repository.update_item(item_id, changes)
    if item is None:
        raise NotFoundError(f"Invoice item {item_id} not found.")
    return item


def delete_item(item_id: str) -> None:
    if not invoice_repository.delete_item(item_id):
        raise NotFoundError(f"Invoice item {item_id} not found.")
