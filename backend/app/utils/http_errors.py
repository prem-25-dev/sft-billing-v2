"""Maps our internal errors to HTTP responses, once, instead of every route repeating try/except."""
from __future__ import annotations

from fastapi import HTTPException

from app.utils.errors import ConflictError, NotFoundError, ValidationFailedError
from app.excel.workbook import WorkbookAccessError


def raise_as_http(exc: Exception) -> None:
    if isinstance(exc, ValidationFailedError):
        raise HTTPException(status_code=422, detail={"message": "Validation failed", "errors": exc.errors})
    if isinstance(exc, NotFoundError):
        raise HTTPException(status_code=404, detail=exc.message)
    if isinstance(exc, ConflictError):
        raise HTTPException(status_code=409, detail=exc.message)
    if isinstance(exc, WorkbookAccessError):
        raise HTTPException(status_code=503, detail=str(exc))
    raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")
