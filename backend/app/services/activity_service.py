"""Activity/audit-event service backed by SQLite.

Legacy Excel activity rows remain available in the workbook but are not
imported or included in active reads.
"""

from __future__ import annotations

from typing import Any

from app.repositories.activity_repository import activity_repository
from app.utils.validators import new_id, now_iso


def list_activity() -> list[dict[str, Any]]:
    return activity_repository.list_all()


def get_activity(activity_id: str) -> dict[str, Any] | None:
    return activity_repository.get_by_id(activity_id)


def list_recent_activity(limit: int = 10) -> list[dict[str, Any]]:
    return activity_repository.list_recent(limit)


def list_activity_for_client(client_id: str) -> list[dict[str, Any]]:
    return activity_repository.list_by_client(client_id)


def list_activity_for_invoice(invoice_id: str) -> list[dict[str, Any]]:
    return activity_repository.list_by_invoice(invoice_id)


def list_activity_for_payment(payment_id: str) -> list[dict[str, Any]]:
    return activity_repository.list_by_payment(payment_id)


def add_activity_event(payload: dict[str, Any]) -> dict[str, Any]:
    row = {
        "id": new_id("ev"),
        "type": payload["type"],
        "occurredAt": payload.get("occurredAt") or now_iso(),
        "summary": payload["summary"],
        "clientId": payload.get("clientId"),
        "invoiceId": payload.get("invoiceId"),
        "paymentId": payload.get("paymentId"),
        "amount": payload.get("amount"),
    }
    return activity_repository.create(row)
