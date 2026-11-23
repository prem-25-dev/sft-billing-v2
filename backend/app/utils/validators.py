"""Small standalone helpers with no workbook/service knowledge."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match(value))


def is_valid_gstin(value: str) -> bool:
    return bool(GSTIN_PATTERN.match(value.upper()))


def is_valid_iso_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False
