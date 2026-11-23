"""Notification service for business and system events."""

from __future__ import annotations

from typing import Any

from app.repositories.notification_repository import notification_repository
from app.utils.validators import new_id, now_iso


NOTIFICATION_CATEGORIES = {
    "business": "Business Activity",
    "payments": "Payments",
    "clients": "Clients",
    "products": "Products",
    "settings": "Settings",
    "updates": "Software Updates",
    "system": "System",
}

NOTIFICATION_TYPES = {
    "invoice_created": ("business", "Invoice Created"),
    "invoice_updated": ("business", "Invoice Updated"),
    "invoice_cancelled": ("business", "Invoice Cancelled"),
    "payment_received": ("payments", "Payment Received"),
    "payment_updated": ("payments", "Payment Updated"),
    "client_created": ("clients", "Client Created"),
    "client_updated": ("clients", "Client Updated"),
    "product_created": ("products", "Product Created"),
    "product_updated": ("products", "Product Updated"),
    "settings_changed": ("settings", "Settings Changed"),
    "update_available": ("updates", "Update Available"),
    "update_downloaded": ("updates", "Update Downloaded"),
    "update_installed": ("updates", "Update Installed"),
    "update_failed": ("updates", "Update Failed"),
    "app_new_version": ("updates", "New Version Running"),
}


def _validate_category(category: str) -> str:
    if category not in NOTIFICATION_CATEGORIES:
        raise ValueError(f"Invalid notification category: {category}")
    return category


def _validate_type(type_: str) -> str:
    if type_ not in NOTIFICATION_TYPES:
        raise ValueError(f"Invalid notification type: {type_}")
    return type_


def create_notification(
    type_: str,
    title: str,
    message: str,
    reference_id: str | None = None,
    reference_type: str | None = None,
) -> dict[str, Any]:
    """Create a notification for a business or system event."""
    _validate_type(type_)
    category, _ = NOTIFICATION_TYPES[type_]
    _validate_category(category)

    notification_id = new_id("ntf")
    occurred_at = now_iso()

    values = {
        "id": notification_id,
        "type": type_,
        "category": category,
        "title": title,
        "message": message,
        "referenceId": reference_id,
        "referenceType": reference_type,
        "read": False,
        "occurredAt": occurred_at,
        "readAt": None,
    }

    return notification_repository.create(values)


def create_business_notification(
    type_: str,
    title: str,
    message: str,
    reference_id: str | None = None,
    reference_type: str | None = None,
) -> dict[str, Any]:
    """Create a business activity notification (invoice, payment, client, product)."""
    return create_notification(type_, title, message, reference_id, reference_type)


def create_update_notification(
    type_: str,
    title: str,
    message: str,
    reference_id: str | None = None,
    reference_type: str | None = None,
) -> dict[str, Any]:
    """Create a software update notification."""
    return create_notification(type_, title, message, reference_id, reference_type)


def list_notifications(limit: int | None = None) -> list[dict[str, Any]]:
    return notification_repository.list_all(limit)


def list_unread_notifications(category: str | None = None) -> list[dict[str, Any]]:
    return notification_repository.list_unread(category)


def count_unread_notifications(category: str | None = None) -> int:
    return notification_repository.count_unread(category)


def mark_notification_read(notification_id: str) -> dict[str, Any] | None:
    return notification_repository.mark_read(notification_id)


def mark_all_notifications_read(category: str | None = None) -> int:
    return notification_repository.mark_all_read(category)


def get_notification_categories() -> dict[str, str]:
    return dict(NOTIFICATION_CATEGORIES)


def get_notification_types() -> dict[str, tuple[str, str]]:
    return dict(NOTIFICATION_TYPES)