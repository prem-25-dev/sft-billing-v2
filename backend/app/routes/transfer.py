"""First-run setup and copy-data endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database.session import get_db_session
from app.routes.auth import get_current_user
from app.services import transfer_service
from app.services.auth_service import admin_exists

MAX_PACK_BYTES = 200 * 1024 * 1024

setup_router = APIRouter(prefix="/api/setup", tags=["setup"])
transfer_router = APIRouter(
    prefix="/api/transfer", tags=["transfer"], dependencies=[Depends(get_current_user)]
)


class ExportRequest(BaseModel):
    master: bool = True
    business: bool = True
    transactions: bool = False


@setup_router.get("/status")
def setup_status(db: Session = Depends(get_db_session)):
    """What the first-run wizard needs to know."""
    clients = db.execute(text("SELECT COUNT(*) FROM clients")).scalar_one()
    products = db.execute(text("SELECT COUNT(*) FROM products")).scalar_one()
    return {
        "needs_account": not admin_exists(db),
        "clients": clients,
        "products": products,
    }


@setup_router.post("/restore")
async def restore(file: UploadFile = File(...), db: Session = Depends(get_db_session)):
    """Load a data file from another PC. Only allowed before an account exists."""
    if admin_exists(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "This PC is already set up.")
    data = await file.read()
    if len(data) > MAX_PACK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The data file is too large.")
    db.close()  # release our connection before the file-level copy
    try:
        manifest = transfer_service.restore_pack(data)
    except transfer_service.TransferError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return {"ok": True, "counts": manifest["counts"], "includes": manifest["includes"]}


@transfer_router.get("/summary")
def summary():
    return transfer_service.summary()


@transfer_router.post("/export")
def export(request: ExportRequest):
    try:
        data, filename = transfer_service.export_pack(
            request.master, request.business, request.transactions
        )
    except transfer_service.TransferError as error:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(error)) from None
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
