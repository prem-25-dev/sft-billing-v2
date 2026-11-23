from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.services import client_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/clients", tags=["clients"], dependencies=[Depends(get_current_user)])


@router.get("")
def list_clients() -> list[dict]:
    try:
        return client_service.list_clients()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{client_id}")
def get_client(client_id: str) -> dict:
    try:
        return client_service.get_client(client_id)
    except Exception as exc:
        raise_as_http(exc)


@router.post("", status_code=201)
def create_client(payload: dict) -> dict:
    try:
        return client_service.create_client(payload)
    except Exception as exc:
        raise_as_http(exc)


@router.put("/{client_id}")
def update_client(client_id: str, payload: dict) -> dict:
    try:
        return client_service.update_client(client_id, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/{client_id}", status_code=200)
def delete_client(client_id: str) -> dict:
    try:
        client_service.delete_client(client_id)
        return {"deleted": True, "id": client_id}
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{client_id}/invoices")
def get_client_invoice_history(client_id: str) -> list[dict]:
    try:
        from app.services import dashboard_service
        client_service.get_client(client_id)  # 404s if missing
        return dashboard_service.client_invoice_history(client_id)
    except Exception as exc:
        raise_as_http(exc)
