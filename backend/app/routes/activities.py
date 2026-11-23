from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services import activity_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/activities", tags=["activities"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_activity() -> list[dict]:
    try:
        return activity_service.list_activity()
    except Exception as exc:
        raise_as_http(exc)


@router.post("", status_code=201)
def add_activity_event(payload: dict) -> dict:
    try:
        return activity_service.add_activity_event(payload)
    except Exception as exc:
        raise_as_http(exc)
