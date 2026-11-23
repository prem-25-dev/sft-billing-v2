from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services import dashboard_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(get_current_user)])


@router.get("/summary")
def get_summary() -> dict:
    try:
        return dashboard_service.dashboard_summary()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/outstanding-invoices")
def get_outstanding_invoices() -> list[dict]:
    try:
        return dashboard_service.outstanding_invoices()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/overdue-invoices")
def get_overdue_invoices() -> list[dict]:
    try:
        return dashboard_service.overdue_invoices()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/recent-payments")
def get_recent_payments(limit: int = 10) -> list[dict]:
    try:
        return dashboard_service.recent_payments(limit)
    except Exception as exc:
        raise_as_http(exc)
