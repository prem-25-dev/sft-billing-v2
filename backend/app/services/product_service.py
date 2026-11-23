"""Product catalog and controlled inventory movement rules."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.repositories.product_repository import product_repository
from app.utils.errors import ConflictError, NotFoundError, ValidationFailedError
from app.utils.validators import new_id

_PRODUCT_TEXT_FIELDS = ("code", "name", "hsnCode", "unit")
_PRODUCT_TYPES = {"product", "service"}
_MOVEMENT_TYPES = {"opening", "receipt", "issue", "adjustment"}


def get_next_product_code() -> str:
    """Get the next available sequential product code (SFT-XXX format)."""
    existing_codes = product_repository.list_products()
    max_seq = 0
    for product in existing_codes:
        code = product.get("code", "")
        if code.startswith("SFT-"):
            try:
                num = int(code.replace("SFT-", ""))
                if num > max_seq:
                    max_seq = num
            except (ValueError, AttributeError):
                pass
    return f"SFT-{str(max_seq + 1).zfill(3)}"


def _decimal(value: Any, field: str, errors: dict[str, str]) -> Decimal | None:
    if isinstance(value, bool):
        errors[field] = "Enter a valid number."
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        errors[field] = "Enter a valid number."
        return None
    if not result.is_finite():
        errors[field] = "Enter a finite number."
        return None
    return result


def _paise(value: Any, field: str, errors: dict[str, str]) -> int | None:
    amount = _decimal(value, field, errors)
    if amount is None:
        return None
    if amount < 0:
        errors[field] = "Must be nonnegative."
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _milli_quantity(
    value: Any,
    field: str,
    errors: dict[str, str],
    *,
    signed: bool = False,
) -> int | None:
    quantity = _decimal(value, field, errors)
    if quantity is None:
        return None
    if not signed and quantity < 0:
        errors[field] = "Must be nonnegative."
        return None
    scaled = quantity * 1000
    if scaled != scaled.to_integral_value():
        errors[field] = "Use no more than three decimal places."
        return None
    return int(scaled)


def _text(value: Any, field: str, errors: dict[str, str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        errors[field] = "This field is required."
        return None
    return value.strip()


def _product_response(record: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "defaultUnitPrice",
        "purchaseCost",
        "weight",
        "lowStockThreshold",
        "stockOnHand",
    ):
        if record[field] is not None:
            record[field] = float(record[field])
    return record


def _movement_response(record: dict[str, Any]) -> dict[str, Any]:
    record["quantityChange"] = float(record["quantityChange"])
    record["resultingBalance"] = float(record["resultingBalance"])
    return record


def _prepare_product(
    payload: dict[str, Any],
    *,
    partial: bool,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}

    for field in _PRODUCT_TEXT_FIELDS:
        if not partial or field in payload:
            value = _text(payload.get(field), field, errors)
            if value is not None:
                values[field] = value.upper() if field == "code" else value

    if not partial or "type" in payload:
        product_type = payload.get("type")
        if not isinstance(product_type, str) or product_type not in _PRODUCT_TYPES:
            errors["type"] = "Type must be 'product' or 'service'."
        else:
            values["type"] = product_type

    if not partial or "defaultUnitPrice" in payload:
        value = _paise(payload.get("defaultUnitPrice"), "defaultUnitPrice", errors)
        if value is not None:
            values["defaultUnitPricePaise"] = value

    if not partial or "defaultGstRate" in payload:
        rate = _decimal(payload.get("defaultGstRate"), "defaultGstRate", errors)
        if rate is not None:
            if not Decimal(0) <= rate <= Decimal(1):
                errors["defaultGstRate"] = "GST rate must be between 0 and 1."
            else:
                values["defaultGstRate"] = float(rate)

    if not partial or "weight" in payload or "weightUnit" in payload:
        weight = payload.get("weight", existing.get("weight") if existing else None)
        weight_unit = payload.get(
            "weightUnit", existing.get("weightUnit") if existing else None
        )
        if weight is None and weight_unit is None:
            values["weightMilli"] = None
            values["weightUnit"] = None
        elif weight is None or weight_unit is None:
            errors["weight"] = "Weight and weightUnit must be provided together."
        else:
            parsed_weight = _milli_quantity(weight, "weight", errors)
            if parsed_weight is not None:
                values["weightMilli"] = parsed_weight
            if weight_unit not in {"g", "kg", "ml", "L"}:
                errors["weightUnit"] = "Use one of: g, kg, ml, or L."
            else:
                values["weightUnit"] = weight_unit

    if "purchaseCost" in payload:
        purchase_cost = payload.get("purchaseCost")
        if purchase_cost is None:
            values["purchaseCostPaise"] = None
        else:
            parsed_cost = _paise(purchase_cost, "purchaseCost", errors)
            if parsed_cost is not None:
                values["purchaseCostPaise"] = parsed_cost

    if "lowStockThreshold" in payload:
        threshold = payload.get("lowStockThreshold")
        if threshold is None:
            values["lowStockThresholdMilli"] = None
        else:
            parsed_threshold = _milli_quantity(
                threshold, "lowStockThreshold", errors
            )
            if parsed_threshold is not None:
                values["lowStockThresholdMilli"] = parsed_threshold

    resulting_type = values.get("type", existing.get("type") if existing else None)
    resulting_threshold = values.get(
        "lowStockThresholdMilli",
        existing.get("lowStockThreshold") if existing else None,
    )
    if resulting_type == "service" and resulting_threshold is not None:
        errors["lowStockThreshold"] = "Services cannot have a stock threshold."

    if "isActive" in payload:
        if not isinstance(payload["isActive"], bool):
            errors["isActive"] = "Must be true or false."
        else:
            values["isActive"] = payload["isActive"]

    if errors:
        raise ValidationFailedError(errors)
    return values


def list_products(
    search: str | None = None,
    is_active: bool | None = None,
    product_type: str | None = None,
) -> list[dict[str, Any]]:
    if product_type is not None and (
        not isinstance(product_type, str) or product_type not in _PRODUCT_TYPES
    ):
        raise ValidationFailedError(
            {"type": "Type must be 'product' or 'service'."}
        )
    return [
        _product_response(product)
        for product in product_repository.list_products(
            search, is_active, product_type
        )
    ]


def get_product(product_id: str) -> dict[str, Any]:
    product = product_repository.get_by_id(product_id)
    if product is None:
        raise NotFoundError(f"Product {product_id} not found.")
    return _product_response(product)


def create_product(payload: dict[str, Any]) -> dict[str, Any]:
    values = _prepare_product(payload, partial=False)
    values["id"] = payload.get("id") or new_id("pr")
    if not isinstance(values["id"], str) or not values["id"].strip():
        raise ValidationFailedError({"id": "Must be nonempty text."})
    if product_repository.code_exists(values["code"]):
        raise ConflictError("A product with this code already exists.")
    return _product_response(product_repository.create(values))


def update_product(product_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    existing = get_product(product_id)
    values = _prepare_product(payload, partial=True, existing=existing)
    if "code" in values and product_repository.code_exists(
        values["code"], excluding_id=product_id
    ):
        raise ConflictError("A product with this code already exists.")
    updated = product_repository.update(product_id, values)
    if updated is None:
        raise NotFoundError(f"Product {product_id} not found.")
    return _product_response(updated)


def set_product_active(product_id: str, is_active: bool) -> dict[str, Any]:
    if not isinstance(is_active, bool):
        raise ValidationFailedError({"isActive": "Must be true or false."})
    updated = product_repository.set_active(product_id, is_active)
    if updated is None:
        raise NotFoundError(f"Product {product_id} not found.")
    return _product_response(updated)


def delete_product(product_id: str) -> None:
    product_repository.delete(product_id)


def record_inventory_movement(
    product_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    errors: dict[str, str] = {}
    movement_type = payload.get("type")
    if not isinstance(movement_type, str) or movement_type not in _MOVEMENT_TYPES:
        errors["type"] = "Use opening, receipt, issue, or adjustment."

    idempotency_key = _text(payload.get("idempotencyKey"), "idempotencyKey", errors)
    if idempotency_key is not None and len(idempotency_key) > 200:
        errors["idempotencyKey"] = "Must be 200 characters or fewer."

    signed = movement_type == "adjustment"
    quantity = _milli_quantity(
        payload.get("quantity"), "quantity", errors, signed=signed
    )
    if quantity is not None:
        if movement_type == "issue":
            if quantity <= 0:
                errors["quantity"] = "Issue quantity must be greater than zero."
            else:
                quantity = -quantity
        elif movement_type == "receipt" and quantity <= 0:
            errors["quantity"] = "Receipt quantity must be greater than zero."
        elif movement_type == "adjustment" and quantity == 0:
            errors["quantity"] = "Adjustment quantity cannot be zero."
    if movement_type == "adjustment":
        reason = _text(payload.get("reason"), "reason", errors)
    else:
        reason = payload.get("reason")
        if reason is not None and not isinstance(reason, str):
            errors["reason"] = "Must be text."
        elif reason is not None:
            reason = reason.strip() or None

    values: dict[str, str | None] = {}
    for field in ("invoiceId", "reference", "notes"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            errors[field] = "Must be text."
        else:
            values[field] = value.strip() or None if value is not None else None

    if errors:
        raise ValidationFailedError(errors)
    if quantity is None or idempotency_key is None:
        raise ValidationFailedError({"quantity": "A valid quantity is required."})
    try:
        return _movement_response(
            product_repository.record_movement(
                product_id=product_id,
                movement_type=movement_type,
                quantity_change_milli=quantity,
                idempotency_key=idempotency_key,
                invoice_id=values["invoiceId"],
                reference=values["reference"],
                reason=reason,
                notes=values["notes"],
            )
        )
    except ValueError as exc:
        raise ValidationFailedError({"reason": str(exc)}) from exc


def list_inventory_movements(
    product_id: str, limit: int = 100, offset: int = 0
) -> list[dict[str, Any]]:
    if not 1 <= limit <= 500:
        raise ValidationFailedError({"limit": "Must be between 1 and 500."})
    if offset < 0:
        raise ValidationFailedError({"offset": "Must be nonnegative."})
    return [
        _movement_response(movement)
        for movement in product_repository.list_movements(product_id, limit, offset)
    ]
