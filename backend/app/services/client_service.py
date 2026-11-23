"""Client CRUD business rules backed by SQLite.

The Excel Clients sheet remains untouched as legacy data for Excel-backed
domains; active Client API CRUD reads and writes only through the repository.
"""
from __future__ import annotations

import re
from typing import Any

from app.repositories.client_repository import client_repository
from app.utils.errors import NotFoundError, ValidationFailedError
from app.utils.validators import is_valid_email, is_valid_gstin, new_id


def _validate(payload: dict[str, Any], partial: bool = False) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not partial or "name" in payload:
        if not (payload.get("name") or "").strip():
            errors["name"] = "Client name is required."
    for field in ("email", "phone", "pan"):
        value = payload.get(field)
        if field in payload and value is not None and not isinstance(value, str):
            errors[field] = (
                "Enter a valid email address."
                if field == "email"
                else "Must be text."
            )
    if isinstance(payload.get("email"), str):
        email = payload["email"].strip()
        if email and not is_valid_email(email):
            errors["email"] = "Enter a valid email address."
    if isinstance(payload.get("phone"), str):
        phone = payload["phone"].strip()
        if not phone:
            errors["phone"] = "Phone number is required."
        else:
            phone_digits = re.sub(r"\D", "", phone)
            if len(phone_digits) != 10:
                errors["phone"] = "Phone number must be exactly 10 digits."
    if not partial or "billingAddress" in payload:
        if not (payload.get("billingAddress") or "").strip():
            errors["billingAddress"] = "Billing address is required."
    gstin = payload.get("gstin")
    if (not partial or "gstin" in payload) and gstin is not None:
        if gstin and gstin.strip() and not is_valid_gstin(gstin):
            errors["gstin"] = "Invalid GSTIN format."
    return errors


def list_clients() -> list[dict[str, Any]]:
    return client_repository.list_all()


def get_client(client_id: str) -> dict[str, Any]:
    client = client_repository.get_by_id(client_id)
    if client is None:
        raise NotFoundError(f"Client {client_id} not found.")
    return client


def create_client(payload: dict[str, Any]) -> dict[str, Any]:
    errors = _validate(payload)
    if errors:
        raise ValidationFailedError(errors)

    row = {
        "id": payload.get("id") or new_id("cl"),
        "name": payload["name"].strip(),
        "contactName": (payload.get("contactName") or "").strip() or None,
        "email": _optional_text(payload.get("email")),
        "phone": _optional_text(payload.get("phone")),
        "billingAddress": payload["billingAddress"].strip(),
        "gstin": (payload.get("gstin") or "").strip().upper() or None,
        "pan": _optional_text(payload.get("pan"), uppercase=True),
        "notes": (payload.get("notes") or "").strip() or None,
    }
    return client_repository.create(row)


def update_client(client_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    errors = _validate(payload, partial=True)
    if errors:
        raise ValidationFailedError(errors)

    changes: dict[str, Any] = {}
    for key in ("name", "contactName", "email", "phone", "billingAddress", "notes", "pan"):
        if key in payload:
            value = payload[key]
            # Skip None values for optional fields to avoid clearing them
            if value is None and key in ("email", "phone", "pan"):
                continue
            if key in {"email", "phone", "pan"}:
                changes[key] = _optional_text(
                    value, uppercase=key == "pan"
                )
            elif value is not None:
                changes[key] = (
                    value.strip()
                    if isinstance(value, str)
                    else value
                )
    if "gstin" in payload and payload["gstin"] is not None:
        changes["gstin"] = payload["gstin"].strip().upper() or None

    persisted = client_repository.update(client_id, changes)
    if persisted is None:
        raise NotFoundError(f"Client {client_id} not found.")
    return persisted


def delete_client(client_id: str) -> None:
    if not client_repository.delete(client_id):
        raise NotFoundError(f"Client {client_id} not found.")


def _optional_text(value: Any, uppercase: bool = False) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("Optional Client contact values must be strings or null.")
    normalized = value.strip()
    if uppercase:
        normalized = normalized.upper()
    return normalized or None
