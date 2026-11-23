"""Cross-cutting read views: dashboard summary, outstanding/overdue lists, recent payments."""
from __future__ import annotations

from typing import Any

from app.services import invoice_service, payment_service


def dashboard_summary() -> dict[str, Any]:
    invoices = invoice_service.list_invoices()
    total_invoiced = sum(inv["totals"]["total"] for inv in invoices if not inv["isDraft"])
    total_collected = sum(inv["totals"]["paidAmount"] for inv in invoices)
    outstanding = sum(inv["totals"]["balanceDue"] for inv in invoices if inv["status"] not in ("draft", "cancelled"))
    overdue_count = sum(1 for inv in invoices if inv["status"] == "overdue")
    draft_count = sum(1 for inv in invoices if inv["status"] == "draft")
    return {
        "invoiceCount": len(invoices),
        "totalInvoiced": round(total_invoiced, 2),
        "totalCollected": round(total_collected, 2),
        "totalOutstanding": round(outstanding, 2),
        "overdueCount": overdue_count,
        "draftCount": draft_count,
    }


def outstanding_invoices() -> list[dict[str, Any]]:
    return [inv for inv in invoice_service.list_invoices() if inv["totals"]["balanceDue"] > 0 and inv["status"] not in ("draft", "cancelled")]


def overdue_invoices() -> list[dict[str, Any]]:
    return [inv for inv in invoice_service.list_invoices() if inv["status"] == "overdue"]


def recent_payments(limit: int = 10) -> list[dict[str, Any]]:
    payments = sorted(payment_service.list_payments(), key=lambda p: p.get("receivedAt") or "", reverse=True)
    return payments[:limit]


def client_invoice_history(client_id: str) -> list[dict[str, Any]]:
    return invoice_service.list_invoices_for_client(client_id)
