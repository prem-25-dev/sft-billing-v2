"""Business Profile behavior and API-shape conversion."""
from __future__ import annotations

from typing import Any

from app.repositories.business_profile_repository import business_profile_repository

_DEFAULTS: dict[str, Any] = {
    "name": "Your Company",
    "logoUrl": None,
    "address": "",
    "email": "billing@example.com",
    "phone": None,
    "gstin": None,
    "pan": None,
    "bank_accountHolder": None,
    "bank_bankName": None,
    "bank_branch": None,
    "bank_accountNumber": None,
    "bank_ifsc": None,
    "declaration": None,
    "authorizedSignatory": None,
    "defaultGst_cgstRate": 0.09,
    "defaultGst_sgstRate": 0.09,
}


def _row_to_profile(row: dict[str, Any]) -> dict[str, Any]:
    bank = None
    if row.get("bank_accountHolder") or row.get("bank_accountNumber"):
        bank = {
            "accountHolder": row.get("bank_accountHolder") or "",
            "bankName": row.get("bank_bankName") or "",
            "branch": row.get("bank_branch") or "",
            "accountNumber": row.get("bank_accountNumber") or "",
            "ifsc": row.get("bank_ifsc") or "",
        }
    default_gst = None
    if row.get("defaultGst_cgstRate") is not None:
        default_gst = {
            "cgstRate": float(row.get("defaultGst_cgstRate") or 0),
            "sgstRate": float(row.get("defaultGst_sgstRate") or 0),
        }
    return {
        "name": row.get("name", _DEFAULTS["name"]),
        "logoUrl": row.get("logoUrl"),
        "address": row.get("address") or "",
        "email": row.get("email", _DEFAULTS["email"]),
        "phone": row.get("phone"),
        "gstin": row.get("gstin"),
        "pan": row.get("pan"),
        "bank": bank,
        "declaration": row.get("declaration"),
        "authorizedSignatory": row.get("authorizedSignatory"),
        "defaultGst": default_gst,
    }


def get_business_profile() -> dict[str, Any]:
    current = business_profile_repository.get_current()
    return _row_to_profile(current if current is not None else _DEFAULTS)


def update_business_profile(update: dict[str, Any]) -> dict[str, Any]:
    current = business_profile_repository.get_current()
    flat: dict[str, Any] = dict(current if current is not None else _DEFAULTS)

    for key, value in update.items():
        if value is None:
            continue
        if key == "bank" and isinstance(value, dict):
            flat["bank_accountHolder"] = value.get("accountHolder")
            flat["bank_bankName"] = value.get("bankName")
            flat["bank_branch"] = value.get("branch")
            flat["bank_accountNumber"] = value.get("accountNumber")
            flat["bank_ifsc"] = value.get("ifsc")
        elif key == "defaultGst" and isinstance(value, dict):
            flat["defaultGst_cgstRate"] = value.get("cgstRate")
            flat["defaultGst_sgstRate"] = value.get("sgstRate")
        else:
            flat[key] = value

    persisted = business_profile_repository.save_current(flat)
    return _row_to_profile(persisted)
