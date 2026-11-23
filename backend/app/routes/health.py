from __future__ import annotations

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import get_db_session

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check(db: Session = Depends(get_db_session)) -> dict:
    """
    Lightweight health check for Tauri startup polling.
    Only verifies database connectivity - does not load workbook.
    """
    try:
        # Simple database connectivity check
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc

    return {
        "status": "ok",
        "database": "connected" if db_ok else "disconnected",
    }


@router.get("/health/detailed")
def detailed_health_check() -> dict:
    """
    Detailed health check including workbook validation.
    Used for diagnostics, not for startup polling.
    """
    from app.excel.workbook import WORKBOOK_PATH
    from app.excel.constants import ALL_SHEETS
    from app.excel.workbook import load_workbook_safely

    try:
        wb = load_workbook_safely()
        sheets_ok = all(name in wb.sheetnames for name in ALL_SHEETS)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Workbook unavailable: {exc}") from exc
    return {
        "status": "ok",
        "workbook": str(WORKBOOK_PATH),
        "workbookExists": WORKBOOK_PATH.exists(),
        "sheets": ALL_SHEETS,
        "sheetsOk": sheets_ok,
    }
