"""Authentication dependencies for SFT Billing.

This module re-exports authentication dependencies from the auth routes module
to provide a clean import path for other modules.
"""

from app.routes.auth import (
    get_current_user,
    get_optional_user,
)

__all__ = [
    "get_current_user",
    "get_optional_user",
]