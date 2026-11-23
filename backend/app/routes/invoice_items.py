from __future__ import annotations

from fastapi import APIRouter

from app.services import invoice_item_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/invoice-items", tags=["invoice-items"])


@router.get("")
def list_items_for_invoice(invoiceId: str) -> list[dict]:
    try:
        return invoice_item_service.list_items_for_invoice(invoiceId)
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{item_id}")
def get_item(item_id: str) -> dict:
    try:
        return invoice_item_service.get_item(item_id)
    except Exception as exc:
        raise_as_http(exc)


@router.post("", status_code=201)
def create_item(invoiceId: str, payload: dict) -> dict:
    try:
        return invoice_item_service.create_item(invoiceId, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.put("/{item_id}")
def update_item(item_id: str, payload: dict) -> dict:
    try:
        return invoice_item_service.update_item(item_id, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/{item_id}", status_code=200)
def delete_item(item_id: str) -> dict:
    try:
        invoice_item_service.delete_item(item_id)
        return {"deleted": True, "id": item_id}
    except Exception as exc:
        raise_as_http(exc)
