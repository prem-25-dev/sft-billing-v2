from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Response
from fastapi.responses import Response

from app.auth import get_current_user
from app.services import invoice_excel_export_service, invoice_service
from app.services.numbering_service import reserve_invoice_number
from app.utils.validators import new_id
from app.utils.http_errors import raise_as_http

router = APIRouter(prefix="/api/invoices", tags=["invoices"], dependencies=[Depends(get_current_user)])
_EXCEL_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
_PDF_MIME_TYPE = "application/pdf"


@router.post("/reserve-number")
def reserve_number(payload: dict | None = None) -> dict:
    try:
        payload = payload or {}
        reservation_id = payload.get("invoiceId") or new_id("iv")
        number = reserve_invoice_number(reservation_id)
        return {"invoiceId": reservation_id, "number": number}
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/reserve-number/{invoice_id}")
def release_reservation(invoice_id: str) -> dict:
    """Release a previously reserved invoice number.

    This allows the frontend to clean up ghost reservations when
    invoice creation is cancelled or fails.
    """
    try:
        released = invoice_number_repository.release_reservation(invoice_id)
        return {"released": released, "invoiceId": invoice_id}
    except Exception as exc:
        raise_as_http(exc)


@router.get("")
def list_invoices() -> list[dict]:
    try:
        return invoice_service.list_invoices()
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{invoice_id}")
def get_invoice(invoice_id: str) -> dict:
    try:
        return invoice_service.get_invoice(invoice_id)
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{invoice_id}/excel")
def export_invoice_excel(invoice_id: str) -> Response:
    try:
        export = invoice_excel_export_service.export_invoice_excel(invoice_id)
        return Response(
            content=export.content,
            media_type=_EXCEL_MIME_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{export.file_name}"',
                "X-Invoice-Export-Warnings": json.dumps(export.warnings),
            },
        )
    except Exception as exc:
        raise_as_http(exc)


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: str) -> Response:
    try:
        export = invoice_excel_export_service.export_invoice_pdf(invoice_id)
        return Response(
            content=export.content,
            media_type=_PDF_MIME_TYPE,
            headers={
                "Content-Disposition": f'attachment; filename="{export.file_name}"',
                "X-Invoice-Export-Warnings": json.dumps(export.warnings),
            },
        )
    except Exception as exc:
        raise_as_http(exc)


@router.post("", status_code=201)
def create_invoice(payload: dict) -> dict:
    try:
        return invoice_service.create_invoice(payload)
    except Exception as exc:
        raise_as_http(exc)


@router.put("/{invoice_id}")
def update_invoice(invoice_id: str, payload: dict) -> dict:
    try:
        return invoice_service.update_invoice(invoice_id, payload)
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/{invoice_id}", status_code=200)
def delete_invoice(invoice_id: str) -> dict:
    try:
        invoice_service.delete_invoice(invoice_id)
        return {"deleted": True, "id": invoice_id}
    except Exception as exc:
        raise_as_http(exc)


@router.delete("/clear-history", status_code=200)
def clear_invoice_history(payload: dict | None = None) -> dict:
    try:
        confirmation_token = (payload or {}).get("confirmation_token")
        return invoice_service.clear_invoice_history(confirmation_token)
    except Exception as exc:
        raise_as_http(exc)
