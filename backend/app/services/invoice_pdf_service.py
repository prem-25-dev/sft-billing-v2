"""Native GST tax-invoice PDF renderer.

Produces the invoice PDF directly with ReportLab so it works on any machine
(no Microsoft Excel / COM automation needed) and can be previewed inline.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.calculation_service import amount_in_words

INK = colors.HexColor("#14141c")
MUTED = colors.HexColor("#5c5c6c")
FAINT = colors.HexColor("#8c8c9c")
LINE = colors.HexColor("#e2e2ec")
ACCENT = colors.HexColor("#635bff")
SOFT = colors.HexColor("#f4f4fa")

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=9, leading=12.5, textColor=INK)
_MUTED = ParagraphStyle("muted", parent=_BASE, textColor=MUTED, fontSize=8.5, leading=12)
_SMALL = ParagraphStyle("small", parent=_BASE, textColor=FAINT, fontSize=7.5, leading=10)
_LABEL = ParagraphStyle("label", parent=_BASE, textColor=FAINT, fontSize=7.2, leading=10, fontName="Helvetica-Bold")
_H = ParagraphStyle("h", parent=_BASE, fontName="Helvetica-Bold", fontSize=15, leading=19)
_NAME = ParagraphStyle("name", parent=_BASE, fontName="Helvetica-Bold", fontSize=10.5, leading=14)
_RIGHT = ParagraphStyle("right", parent=_BASE, alignment=TA_RIGHT)
_RIGHT_B = ParagraphStyle("rightb", parent=_RIGHT, fontName="Helvetica-Bold")
_TH = ParagraphStyle("th", parent=_BASE, fontName="Helvetica-Bold", fontSize=7.6, leading=10, textColor=MUTED)
_TH_R = ParagraphStyle("thr", parent=_TH, alignment=TA_RIGHT)


def _money(value: Any) -> str:
    amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return f"{sign}{whole}.{frac}"


def _qty(value: Any) -> str:
    number = Decimal(str(value or 0))
    return f"{number:f}".rstrip("0").rstrip(".") if "." in f"{number:f}" else f"{number:f}"


def _date(value: Any) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d %b %Y")
    except ValueError:
        return str(value)[:10]


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def _p(text: str, style: ParagraphStyle = _BASE) -> Paragraph:
    return Paragraph(text, style)


def render_invoice_pdf_native(invoice: dict[str, Any], client: dict[str, Any], business: dict[str, Any]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"Invoice {invoice.get('number', '')}",
        author=str(business.get("name") or "SFT Billing"),
    )
    width = A4[0] - 32 * mm
    totals = invoice.get("totals") or {}
    gst = invoice.get("gst") or {}
    story: list[Any] = []

    # ── Header: business + invoice meta ─────────────────────────────
    biz_lines = [f"<b>{_esc(business.get('name') or 'Your business')}</b>"]
    biz_block = [_p(biz_lines[0], _H)]
    if business.get("address"):
        biz_block.append(_p(_esc(business["address"]), _MUTED))
    contact = " · ".join(str(v) for v in (business.get("phone"), business.get("email")) if v)
    if contact:
        biz_block.append(_p(_esc(contact), _MUTED))
    ids = "   ".join(
        f"{label} {value}" for label, value in (("GSTIN", business.get("gstin")), ("PAN", business.get("pan"))) if value
    )
    if ids:
        biz_block.append(_p(_esc(ids), _MUTED))

    status = "DRAFT" if invoice.get("isDraft") else "TAX INVOICE"
    meta_rows = [
        [_p(status, ParagraphStyle("st", parent=_RIGHT_B, textColor=ACCENT, fontSize=10, leading=13))],
        [_p(f"<font color='#8c8c9c'>Invoice no.</font>  <b>{_esc(invoice.get('number'))}</b>", _RIGHT)],
        [_p(f"<font color='#8c8c9c'>Issued</font>  {_date(invoice.get('issueDate'))}", _RIGHT)],
        [_p(f"<font color='#8c8c9c'>Due</font>  {_date(invoice.get('dueDate'))}", _RIGHT)],
    ]
    meta = Table(meta_rows, colWidths=[width * 0.38])
    meta.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    header = Table([[biz_block, meta]], colWidths=[width * 0.62, width * 0.38])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [header, Spacer(1, 5 * mm), HRFlowable(width="100%", thickness=0.8, color=ACCENT), Spacer(1, 5 * mm)]

    # ── Bill to / order details ─────────────────────────────────────
    bill: list[Any] = [_p("BILL TO", _LABEL), Spacer(1, 1.5 * mm), _p(_esc(client.get("name")), _NAME)]
    if client.get("contactName"):
        bill.append(_p(_esc(client["contactName"]), _MUTED))
    if client.get("billingAddress"):
        bill.append(_p(_esc(client["billingAddress"]), _MUTED))
    cids = "   ".join(f"{k} {v}" for k, v in (("GSTIN", client.get("gstin")), ("PAN", client.get("pan"))) if v)
    if cids:
        bill.append(_p(_esc(cids), _MUTED))

    order: list[Any] = [_p("ORDER DETAILS", _LABEL), Spacer(1, 1.5 * mm)]
    detail_pairs = (
        ("P.O. no.", invoice.get("poNumber")),
        ("P.O. date", _date(invoice.get("poDate")) if invoice.get("poDate") else None),
        ("Supplier code", invoice.get("supplierCode")),
        ("Transporter", invoice.get("transporter")),
    )
    shown = [(k, v) for k, v in detail_pairs if v]
    if shown:
        for k, v in shown:
            order.append(_p(f"<font color='#8c8c9c'>{k}</font>  {_esc(v)}", _BASE))
    else:
        order.append(_p("—", _MUTED))
    info = Table([[bill, order]], colWidths=[width * 0.56, width * 0.44])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [info, Spacer(1, 6 * mm)]

    # ── Items ───────────────────────────────────────────────────────
    cols = [width * w for w in (0.055, 0.395, 0.1, 0.09, 0.15, 0.21)]
    rows: list[list[Any]] = [[
        _p("#", _TH), _p("DESCRIPTION", _TH), _p("HSN/SAC", _TH), _p("QTY", _TH_R), _p("RATE", _TH_R), _p("AMOUNT", _TH_R),
    ]]
    for index, item in enumerate(invoice.get("items") or [], start=1):
        qty = Decimal(str(item.get("quantity") or 0))
        rate = Decimal(str(item.get("unitPrice") or 0))
        rows.append([
            _p(str(index), _MUTED), _p(_esc(item.get("description")), _BASE), _p(_esc(item.get("hsnCode") or "—"), _MUTED),
            _p(_qty(qty), _RIGHT), _p(_money(rate), _RIGHT), _p(_money(qty * rate), _RIGHT_B),
        ])
    items = Table(rows, colWidths=cols, repeatRows=1)
    items.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), SOFT),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [items, Spacer(1, 4 * mm)]

    # ── Totals ──────────────────────────────────────────────────────
    def pct(rate: Any) -> str:
        return f"{Decimal(str(rate or 0)) * 100:.1f}".rstrip("0").rstrip(".")

    total_rows: list[list[Any]] = [
        [_p("Subtotal", _MUTED), _p(_money(totals.get("subtotal")), _RIGHT)],
    ]
    if Decimal(str(totals.get("discount") or 0)) != 0:
        total_rows.append([_p("Discount", _MUTED), _p("- " + _money(totals.get("discount")), _RIGHT)])
        total_rows.append([_p("Taxable value", _MUTED), _p(_money(totals.get("taxableValue")), _RIGHT)])
    total_rows += [
        [_p(f"CGST @ {pct(gst.get('cgstRate'))}%", _MUTED), _p(_money(totals.get("cgstAmount")), _RIGHT)],
        [_p(f"SGST @ {pct(gst.get('sgstRate'))}%", _MUTED), _p(_money(totals.get("sgstAmount")), _RIGHT)],
    ]
    if Decimal(str(totals.get("roundOff") or 0)) != 0:
        total_rows.append([_p("Round off", _MUTED), _p(_money(totals.get("roundOff")), _RIGHT)])
    summary = Table(total_rows, colWidths=[width * 0.22, width * 0.2])
    summary.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
    grand = Table(
        [[_p("<b>Total due</b>", ParagraphStyle("gt", parent=_BASE, textColor=colors.white, fontSize=10)),
          _p(f"<b>INR {_money(totals.get('total'))}</b>", ParagraphStyle("gv", parent=_RIGHT, textColor=colors.white, fontSize=11, leading=14))]],
        colWidths=[width * 0.16, width * 0.26],
    )
    grand.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), ACCENT), ("TOPPADDING", (0, 0), (-1, -1), 7),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 7), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    words = _p(f"<font color='#8c8c9c'>Amount in words</font><br/>{_esc(amount_in_words(float(totals.get('total') or 0)))}", _BASE)
    right = Table([[summary], [grand]], colWidths=[width * 0.42])
    right.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    block = Table([[words, right]], colWidths=[width * 0.54, width * 0.46])
    block.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [KeepTogether(block), Spacer(1, 8 * mm)]

    # ── Bank / declaration / signatory ──────────────────────────────
    bank = business.get("bank") or {}
    bank_lines = [_p("BANK DETAILS", _LABEL), Spacer(1, 1.5 * mm)]
    for label, key in (("Account holder", "accountHolder"), ("Bank", "bankName"), ("Branch", "branch"),
                       ("Account no.", "accountNumber"), ("IFSC", "ifsc")):
        if bank.get(key):
            bank_lines.append(_p(f"<font color='#8c8c9c'>{label}</font>  {_esc(bank[key])}", _BASE))
    sign = [_p(f"For <b>{_esc(business.get('name') or '')}</b>", _RIGHT), Spacer(1, 14 * mm),
            _p(_esc(business.get("authorizedSignatory") or "Authorized Signatory"), _RIGHT)]
    foot = Table([[bank_lines, sign]], colWidths=[width * 0.6, width * 0.4])
    foot.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story.append(KeepTogether([foot]))
    decl = invoice.get("terms") or business.get("declaration")
    if decl or invoice.get("notes"):
        story += [Spacer(1, 6 * mm), HRFlowable(width="100%", thickness=0.4, color=LINE), Spacer(1, 2 * mm)]
        if invoice.get("notes"):
            story.append(_p(f"<b>Notes:</b> {_esc(invoice['notes'])}", _SMALL))
        if decl:
            story.append(_p(f"<b>Declaration:</b> {_esc(decl)}", _SMALL))
    story += [Spacer(1, 3 * mm), _p("This is a computer-generated invoice.", _SMALL)]

    doc.build(story)
    return buffer.getvalue()
