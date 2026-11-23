from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.services import product_service
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/products", tags=["products"], dependencies=[Depends(get_current_user)])


@router.get("/next-code")
def get_next_product_code() -> dict:
    try:
        return {"code": product_service.get_next_product_code()}
    except Exception as exc:
        raise_as_http(exc)


@router.get("")
def list_products(
    search: str | None = None,
    active: bool | None = None,
    product_type: str | None = Query(default=None, alias="type"),
) -> list[dict]:
    try:
        return product_service.list_products(search, active, product_type)
    except Exception as exc:
        raise_as_http(exc)


@router.post("", status_code=201)
def create_product(payload: dict) -> dict:
    try:
        return product_service.create_product(payload)
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{product_id}/stock")
def get_product_stock(product_id: str) -> dict:
    try:
        product = product_service.get_product(product_id)
        return {
            "productId": product["id"],
            "stockOnHand": product["stockOnHand"],
            "unit": product["unit"],
        }
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{product_id}/movements")
def list_inventory_movements(
    product_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[dict]:
    try:
        return product_service.list_inventory_movements(product_id, limit, offset)
    except Exception as exc:
        raise_as_http(exc)


@router.post("/{product_id}/movements", status_code=201)
def record_inventory_movement(product_id: str, payload: dict) -> dict:
    try:
        return product_service.record_inventory_movement(product_id, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.patch("/{product_id}/status")
def set_product_active(product_id: str, payload: dict) -> dict:
    try:
        return product_service.set_product_active(
            product_id,
            payload.get("isActive"),
        )
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{product_id}")
def get_product(product_id: str) -> dict:
    try:
        return product_service.get_product(product_id)
    except Exception as exc:
        raise_as_http(exc)


@router.put("/{product_id}")
def update_product(product_id: str, payload: dict) -> dict:
    try:
        return product_service.update_product(product_id, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/{product_id}", status_code=204)
def delete_product(product_id: str) -> None:
    try:
        product_service.delete_product(product_id)
    except Exception as exc:
        raise_as_http(exc)
