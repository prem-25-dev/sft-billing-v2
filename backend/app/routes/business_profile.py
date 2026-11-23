from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services import business_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/business-profile", tags=["business-profile"], dependencies=[Depends(get_current_user)])


@router.get("")
def get_business_profile() -> dict:
    try:
        return business_service.get_business_profile()
    except Exception as exc:
        raise_as_http(exc)


@router.put("")
def update_business_profile(payload: dict) -> dict:
    try:
        return business_service.update_business_profile(payload)
    except Exception as exc:
        raise_as_http(exc)
