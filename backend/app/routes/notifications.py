from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services import notification_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/notifications", tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_notifications(limit: int | None = None, unread_only: bool = False, category: str | None = None) -> list[dict]:
    try:
        if unread_only:
            return notification_service.list_unread_notifications(category)
        return notification_service.list_notifications(limit)
    except Exception as exc:
        raise_as_http(exc)


@router.get("/unread-count")
def count_unread(category: str | None = None) -> dict:
    try:
        count = notification_service.count_unread_notifications(category)
        return {"count": count, "category": category}
    except Exception as exc:
        raise_as_http(exc)


@router.get("/categories")
def get_categories() -> dict:
    try:
        return notification_service.get_notification_categories()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/types")
def get_types() -> dict:
    try:
        return notification_service.get_notification_types()
    except Exception as exc:
        raise_as_http(exc)


@router.post("/{notification_id}/read")
def mark_read(notification_id: str) -> dict:
    try:
        result = notification_service.mark_notification_read(notification_id)
        if result is None:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Notification not found")
        return result
    except Exception as exc:
        raise_as_http(exc)


@router.post("/read-all")
def mark_all_read(category: str | None = None) -> dict:
    try:
        count = notification_service.mark_all_notifications_read(category)
        return {"count": count}
    except Exception as exc:
        raise_as_http(exc)


@router.post("/test")
def create_test_notification() -> dict:
    """Create a test notification for development."""
    try:
        from app.utils.validators import new_id, now_iso
        from app.repositories.notification_repository import notification_repository

        notification_id = new_id("ntf")
        result = notification_repository.create({
            "id": notification_id,
            "type": "test_notification",
            "category": "system",
            "title": "Test Notification",
            "message": "This is a test notification",
            "referenceId": None,
            "referenceType": None,
            "read": False,
            "occurredAt": now_iso(),
            "readAt": None,
        })
        return result
    except Exception as exc:
        raise_as_http(exc)