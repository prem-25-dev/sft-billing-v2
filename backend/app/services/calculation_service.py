"""Invoice totals + amount-in-words.

Deliberately a line-for-line port of the frontend's
src/lib/invoiceMath.ts (computeInvoiceTotals) and src/lib/amountInWords.ts
so the backend and frontend can never disagree on what an invoice adds
up to. If either changes, update both.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two_digits(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return f"{_TENS[tens]}{' ' + _ONES[ones] if ones else ''}"


def _three_digits(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} Hundred")
    if rest:
        parts.append(_two_digits(rest))
    return " ".join(parts)


def _integer_to_indian_words(value: int) -> str:
    if value == 0:
        return "Zero"
    crore, remainder = divmod(value, 10_000_000)
    lakh, remainder = divmod(remainder, 100_000)
    thousand, hundred = divmod(remainder, 1000)

    parts = []
    if crore:
        parts.append(f"{_three_digits(crore)} Crore")
    if lakh:
        parts.append(f"{_three_digits(lakh)} Lakh")
    if thousand:
        parts.append(f"{_three_digits(thousand)} Thousand")
    if hundred:
        parts.append(_three_digits(hundred))
    return " ".join(parts)


def amount_in_words(total: float) -> str:
    total_paise = round(round(abs(total), 2) * 100)
    rupees, paise = divmod(total_paise, 100)

    rupee_words = f"{_integer_to_indian_words(rupees)} Rupees"
    paise_words = f" and {_integer_to_indian_words(paise)} Paise" if paise > 0 else ""
    return f"{rupee_words}{paise_words} Only"


def compute_invoice_totals(
    items: list[dict[str, Any]],
    cgst_rate: float,
    sgst_rate: float,
    discount: float,
    round_off: float,
    paid_amount: float = 0.0,
) -> dict[str, Any]:
    subtotal = sum(float(item["quantity"]) * float(item["unitPrice"]) for item in items)
    taxable_value = max(0.0, subtotal - discount)
    cgst_amount = taxable_value * cgst_rate
    sgst_amount = taxable_value * sgst_rate
    raw_total = taxable_value + cgst_amount + sgst_amount
    total = max(0.0, raw_total + round_off)
    balance_due = max(0.0, round(total - paid_amount, 2))

    return {
        "subtotal": round(subtotal, 2),
        "taxableValue": round(taxable_value, 2),
        "cgstAmount": round(cgst_amount, 2),
        "sgstAmount": round(sgst_amount, 2),
        "discount": round(discount, 2),
        "rawTotal": round(raw_total, 2),
        "roundOff": round(round_off, 2),
        "total": round(total, 2),
        "paidAmount": round(paid_amount, 2),
        "balanceDue": balance_due,
        "amountInWords": amount_in_words(total),
    }


def suggest_round_off(raw_total: float) -> float:
    return round(round(raw_total) - raw_total, 2)


def compute_invoice_status(
    is_draft: bool,
    cancelled_at: str | None,
    paid_at: str | None,
    paid_amount: float,
    total: float,
    due_date: str,
    as_of: datetime | None = None,
) -> str:
    """Mirrors the frontend's getInvoiceStatus, extended with partially_paid/cancelled
    (statuses the current frontend derives only from isDraft/paidAt/dueDate; the backend
    tracks the richer set the spec calls for, using paid_amount vs total for the split)."""
    if cancelled_at:
        return "cancelled"
    if is_draft:
        return "draft"
    if paid_at and paid_amount >= total > 0:
        return "paid"
    if paid_amount > 0 and paid_amount < total:
        return "partially_paid"

    as_of = as_of or datetime.now(timezone.utc)
    try:
        due = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except ValueError:
        return "sent"

    if as_of > due:
        return "overdue"
    return "sent"
