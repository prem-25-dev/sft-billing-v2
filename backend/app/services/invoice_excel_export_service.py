"""Render a saved invoice into the bundled Surfine invoice workbook template."""

from __future__ import annotations

import re
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.drawing.image import Image as OpenpyxlImage
from openpyxl.worksheet.worksheet import Worksheet

from app.excel.workbook import WorkbookAccessError
from app.services import business_service, client_service, invoice_service
from app.services.calculation_service import amount_in_words
from app.utils.errors import ValidationFailedError

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "excel"
    / "templates"
    / "Surfine_Bill_format.xlsx"
)
SHEET_NAMES = ("original", "duplicate", "triplicate")
ITEM_START_ROW = 21
ITEM_ROW_COUNT = 19
TAX_SUMMARY_START_ROW = 43
TAX_SUMMARY_ROW_COUNT = 3
MONEY_QUANTUM = Decimal("0.01")
EXCEL_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass(frozen=True)
class CellFieldMapping:
    source_path: str
    cell: str
    transform: str = "text"
    required: bool = False


FIELD_MAPPINGS = {
    "business.name": CellFieldMapping("business.name", "C3", required=True),
    "business.logoUrl": CellFieldMapping("business.logoUrl", "C3", "logo"),
    "business.address": CellFieldMapping("business.address", "C4"),
    "business.pan": CellFieldMapping("business.pan", "C5"),
    "business.gstin": CellFieldMapping("business.gstin", "H5"),
    "business.email": CellFieldMapping("business.email", "C6"),
    "invoice.number": CellFieldMapping("invoice.number", "G8", required=True),
    "invoice.issueDate": CellFieldMapping("invoice.issueDate", "G9", "date", True),
    "client.name": CellFieldMapping("client.name", "A8", required=True),
    "client.phone": CellFieldMapping("client.phone", "A12"),
    "client.gstin": CellFieldMapping("client.gstin", "D12"),
    "invoice.poNumber": CellFieldMapping("invoice.poNumber", "G10"),
    "invoice.poDate": CellFieldMapping("invoice.poDate", "G11", "date"),
    "invoice.transporter": CellFieldMapping("invoice.transporter", "G12"),
    "business.bank.bankName": CellFieldMapping("business.bank.bankName", "A15"),
    "business.bank.accountNumber": CellFieldMapping(
        "business.bank.accountNumber", "D15"
    ),
    "business.bank.branch": CellFieldMapping("business.bank.branch", "A16"),
    "business.bank.ifsc": CellFieldMapping("business.bank.ifsc", "D16"),
    "business.declaration": CellFieldMapping("business.declaration", "A49"),
    "invoice.totals.taxableValue": CellFieldMapping(
        "invoice.totals.taxableValue", "H46", "money"
    ),
    "invoice.totals.roundOff": CellFieldMapping(
        "invoice.totals.roundOff", "A47", "round_off"
    ),
    "invoice.totals.total": CellFieldMapping(
        "invoice.totals.total", "I47", "money", True
    ),
    "invoice.totals.amountInWords": CellFieldMapping(
        "invoice.totals.amountInWords", "A51", required=True
    ),
}

UNSUPPORTED_FIELDS = (
    "Client state",
    "Client PAN, email, contact name, and notes",
    "Business phone",
    "Due date, invoice notes/terms, and supplier code",
    "Product unit and product ID",
    "Package count",
    "Payments, amount paid, balance due, and invoice status",
)


@dataclass(frozen=True)
class InvoiceExcelExport:
    content: bytes
    file_name: str
    warnings: tuple[str, ...]


def _resolve_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationFailedError({field: "Must be a valid number."}) from exc
    if not result.is_finite():
        raise ValidationFailedError({field: "Must be a finite number."})
    return result


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def _date_text(value: Any, field: str) -> str:
    if value in (None, ""):
        return ""
    try:
        parsed = (
            datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
            if "T" in str(value)
            else date.fromisoformat(str(value))
        )
    except ValueError as exc:
        raise ValidationFailedError({field: "Must be a valid ISO date."}) from exc
    return parsed.strftime("%d/%m/%Y")


def _set_text(worksheet: Worksheet, cell_address: str, value: Any) -> None:
    cell = worksheet[cell_address]
    cell.value = "" if value is None else str(value)
    cell.data_type = "s"


def _set_numeric(
    worksheet: Worksheet, cell_address: str, value: Decimal | float | int
) -> None:
    worksheet[cell_address] = float(value)


def _insert_logo_image(worksheet: Worksheet, logo_url: str | None) -> None:
    """Insert business logo image into the worksheet at the logo anchor cell."""
    if not logo_url:
        return

    try:
        # Handle data URI (base64 encoded)
        if logo_url.startswith("data:image/"):
            import base64
            from io import BytesIO
            header, encoded = logo_url.split(",", 1)
            image_data = base64.b64decode(encoded)
            img = OpenpyxlImage(BytesIO(image_data))
        # Handle local file path
        elif logo_url.startswith("file://"):
            from pathlib import Path
            file_path = Path(logo_url[7:])  # Remove file:// prefix
            if file_path.exists():
                img = OpenpyxlImage(str(file_path))
            else:
                return
        # Handle HTTP/HTTPS URLs - download the image
        elif logo_url.startswith(("http://", "https://")):
            import urllib.request
            from io import BytesIO
            try:
                with urllib.request.urlopen(logo_url, timeout=10) as response:
                    image_data = response.read()
                img = OpenpyxlImage(BytesIO(image_data))
            except Exception:
                # Silently ignore download failures - template's embedded logo will be used
                return
        else:
            # Assume local relative path
            from pathlib import Path
            file_path = Path(logo_url)
            if file_path.exists():
                img = OpenpyxlImage(str(file_path))
            else:
                return

        # Set image size (adjust as needed for template)
        img.width = 120
        img.height = 60

        # Anchor at cell C3 (where business name is)
        worksheet.add_image(img, "C3")
    except Exception:
        # Silently ignore logo insertion failures - template's embedded logo will be used
        pass


def _apply_field_mappings(
    worksheet: Worksheet,
    invoice: dict[str, Any],
    client: dict[str, Any],
    business: dict[str, Any],
) -> None:
    sources = {"invoice": invoice, "client": client, "business": business}
    errors: dict[str, str] = {}

    for field_name, mapping in FIELD_MAPPINGS.items():
        source = sources[field_name.split(".", 1)[0]]
        value = _resolve_path(source, mapping.source_path.split(".", 1)[1])
        if mapping.required and value in (None, ""):
            errors[field_name] = "Required for Excel invoice export."
            continue

        if field_name in {"business.pan", "business.gstin", "business.email"}:
            label = {
                "business.pan": "PAN: ",
                "business.gstin": "GSTIN: ",
                "business.email": "Mail ID: ",
            }[field_name]
            _set_text(worksheet, mapping.cell, f"{label}{value or ''}")
        elif field_name in {"client.phone", "client.gstin"}:
            label = "Contact no : " if field_name == "client.phone" else "GSTIN: "
            _set_text(worksheet, mapping.cell, f"{label}{value or ''}")
        elif field_name == "invoice.number":
            _set_text(worksheet, mapping.cell, f"Invoice No: {value}")
        elif field_name == "invoice.issueDate":
            _set_text(worksheet, mapping.cell, f"Date : {_date_text(value, field_name)}")
        elif field_name == "invoice.poNumber":
            _set_text(worksheet, mapping.cell, f"PO No: {value or ''}")
        elif field_name == "invoice.poDate":
            _set_text(worksheet, mapping.cell, f"PO Date : {_date_text(value, field_name)}")
        elif field_name == "invoice.transporter":
            _set_text(worksheet, mapping.cell, f"Transporter: {value or ''}")
        elif field_name.startswith("business.bank."):
            label = {
                "business.bank.bankName": "Bank Name: ",
                "business.bank.accountNumber": "Account Number :",
                "business.bank.branch": "Branch Name: ",
                "business.bank.ifsc": "IFSC code : ",
            }[field_name]
            _set_text(worksheet, mapping.cell, f"{label}{value or ''}")
        elif field_name == "business.declaration":
            if value not in (None, ""):
                _set_text(worksheet, mapping.cell, value)
        elif mapping.transform == "money":
            _set_numeric(worksheet, mapping.cell, _decimal(value or 0, field_name))
        elif field_name == "invoice.totals.roundOff":
            amount = _decimal(value or 0, field_name)
            _set_text(worksheet, mapping.cell, f"ROUND OFF : {amount:.2f}")
        elif mapping.transform == "logo":
            _insert_logo_image(worksheet, value)
        else:
            _set_text(worksheet, mapping.cell, value)

    if errors:
        raise ValidationFailedError(errors)

    bank = business.get("bank") or {}
    if not isinstance(bank, dict):
        raise ValidationFailedError({"business.bank": "Bank details must be an object."})

    address = str(client.get("billingAddress") or "")
    address_lines = address.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if len(address_lines) > 3 and any(line.strip() for line in address_lines[3:]):
        raise ValidationFailedError(
            {"client.billingAddress": "The invoice template supports at most three address lines."}
        )
    for row in (9, 10, 11):
        _set_text(worksheet, f"A{row}", "")
    for row, line in zip((9, 10, 11), address_lines[:3]):
        _set_text(worksheet, f"A{row}", line)

    _set_text(worksheet, "A13", "State: ")
    _set_text(worksheet, "G13", "No. Of Packages : ")

    signatory = business.get("authorizedSignatory")
    if signatory:
        _set_text(worksheet, "F49", f"Authorized Signatory\n{signatory}")

    for cell in ("A17", "A18"):
        _set_text(worksheet, cell, "")


def _invoice_items(invoice: dict[str, Any]) -> list[dict[str, Any]]:
    items = invoice.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationFailedError({"items": "At least one invoice item is required."})
    if len(items) > ITEM_ROW_COUNT:
        raise ValidationFailedError(
            {"items": f"The invoice template supports at most {ITEM_ROW_COUNT} line items."}
        )
    return items


def _tax_groups(
    items: list[dict[str, Any]], invoice: dict[str, Any]
) -> list[dict[str, Any]]:
    grouped: dict[str, Decimal] = {}
    for index, item in enumerate(items):
        hsn_code = str(item.get("hsnCode") or "").strip()
        quantity = _decimal(item.get("quantity"), f"items[{index}].quantity")
        unit_price = _decimal(item.get("unitPrice"), f"items[{index}].unitPrice")
        line_total = quantity * unit_price
        if quantity <= 0 or unit_price < 0:
            raise ValidationFailedError(
                {f"items[{index}]": "Quantity must be positive and unit price non-negative."}
            )
        grouped[hsn_code] = grouped.get(hsn_code, Decimal("0")) + line_total

    if len(grouped) > TAX_SUMMARY_ROW_COUNT:
        raise ValidationFailedError(
            {
                "items.hsnCode": (
                    "The invoice template supports at most "
                    f"{TAX_SUMMARY_ROW_COUNT} distinct HSN/SAC groups."
                )
            }
        )

    totals = invoice.get("totals")
    gst = invoice.get("gst")
    if not isinstance(totals, dict) or not isinstance(gst, dict):
        raise ValidationFailedError({"invoice": "Invoice totals and GST rates are required."})

    taxable_total = _decimal(totals.get("taxableValue"), "invoice.totals.taxableValue")
    cgst_total = _decimal(totals.get("cgstAmount"), "invoice.totals.cgstAmount")
    sgst_total = _decimal(totals.get("sgstAmount"), "invoice.totals.sgstAmount")
    cgst_rate = _decimal(gst.get("cgstRate"), "invoice.gst.cgstRate")
    sgst_rate = _decimal(gst.get("sgstRate"), "invoice.gst.sgstRate")

    codes = list(grouped)
    bases = [_round_money(grouped[code]) for code in codes]
    if bases:
        bases[-1] += _round_money(taxable_total) - sum(bases, Decimal("0"))

    cgst_amounts = [_round_money(base * cgst_rate) for base in bases]
    sgst_amounts = [_round_money(base * sgst_rate) for base in bases]
    if cgst_amounts:
        cgst_amounts[-1] += _round_money(cgst_total) - sum(cgst_amounts, Decimal("0"))
        sgst_amounts[-1] += _round_money(sgst_total) - sum(sgst_amounts, Decimal("0"))

    return [
        {
            "hsnCode": code,
            "taxableValue": bases[index],
            "cgstRate": cgst_rate,
            "cgstAmount": cgst_amounts[index],
            "sgstRate": sgst_rate,
            "sgstAmount": sgst_amounts[index],
        }
        for index, code in enumerate(codes)
    ]


def _write_invoice_items(worksheet: Worksheet, invoice: dict[str, Any]) -> None:
    items = _invoice_items(invoice)
    for row in range(ITEM_START_ROW, ITEM_START_ROW + ITEM_ROW_COUNT):
        for column in ("A", "B", "D", "E", "F", "G", "H"):
            _set_text(worksheet, f"{column}{row}", "")

    for index, item in enumerate(items):
        row = ITEM_START_ROW + index
        quantity = _decimal(item.get("quantity"), f"items[{index}].quantity")
        unit_price = _decimal(item.get("unitPrice"), f"items[{index}].unitPrice")
        line_total = quantity * unit_price
        _set_numeric(worksheet, f"A{row}", index + 1)
        _set_text(worksheet, f"B{row}", item.get("description"))
        _set_text(worksheet, f"D{row}", item.get("hsnCode"))
        _set_numeric(worksheet, f"E{row}", unit_price)
        _set_numeric(worksheet, f"F{row}", quantity)
        _set_text(worksheet, f"G{row}", "")
        _set_numeric(worksheet, f"H{row}", line_total)


def _write_tax_summary(worksheet: Worksheet, invoice: dict[str, Any]) -> None:
    groups = _tax_groups(_invoice_items(invoice), invoice)
    for row in range(
        TAX_SUMMARY_START_ROW, TAX_SUMMARY_START_ROW + TAX_SUMMARY_ROW_COUNT
    ):
        for column in ("A", "B", "C", "D", "E", "F", "G", "H"):
            cell = worksheet[f"{column}{row}"]
            if not isinstance(cell, MergedCell):
                _set_text(worksheet, cell.coordinate, "")

    for index, group in enumerate(groups):
        row = TAX_SUMMARY_START_ROW + index
        hsn_cell = (
            f"A{row}"
            if f"A{row}:B{row}" in {str(area) for area in worksheet.merged_cells.ranges}
            else f"B{row}"
        )
        _set_text(worksheet, hsn_cell, group["hsnCode"])
        _set_numeric(worksheet, f"C{row}", group["taxableValue"])
        _set_numeric(worksheet, f"D{row}", group["cgstRate"] * 100)
        _set_numeric(worksheet, f"E{row}", group["cgstAmount"])
        _set_numeric(worksheet, f"F{row}", group["sgstRate"] * 100)
        _set_numeric(worksheet, f"G{row}", group["sgstAmount"])
        _set_numeric(worksheet, f"H{row}", group["cgstAmount"] + group["sgstAmount"])


def _write_totals(worksheet: Worksheet, invoice: dict[str, Any]) -> None:
    totals = invoice["totals"]
    cgst = _decimal(totals["cgstAmount"], "invoice.totals.cgstAmount")
    sgst = _decimal(totals["sgstAmount"], "invoice.totals.sgstAmount")
    _set_text(
        worksheet,
        "A53",
        amount_in_words(float(_round_money(cgst + sgst))),
    )


def _validate_export(invoice: dict[str, Any]) -> None:
    discount = _decimal(invoice.get("discount", 0), "invoice.discount")
    if discount != 0:
        raise ValidationFailedError(
            {
                "invoice.discount": (
                    "The Excel template has no visible discount line. "
                    "Set discount to zero or use the existing PDF export."
                )
            }
        )


def render_invoice_excel(
    invoice: dict[str, Any],
    client: dict[str, Any],
    business: dict[str, Any],
    template_path: Path = TEMPLATE_PATH,
) -> bytes:
    """Render saved domain values into a new in-memory copy of the template."""
    _validate_export(invoice)
    items = _invoice_items(invoice)
    _tax_groups(items, invoice)

    if not template_path.is_file():
        raise WorkbookAccessError("The invoice template file is missing.")

    try:
        workbook = load_workbook(template_path)
    except Exception as exc:
        raise WorkbookAccessError("The invoice template could not be opened.") from exc

    if not set(SHEET_NAMES).issubset(workbook.sheetnames):
        workbook.close()
        raise WorkbookAccessError("The invoice template is missing a required copy sheet.")

    try:
        for sheet_name in SHEET_NAMES:
            worksheet = workbook[sheet_name]
            _apply_field_mappings(worksheet, invoice, client, business)
            _write_invoice_items(worksheet, invoice)
            _write_tax_summary(worksheet, invoice)
            _write_totals(worksheet, invoice)

        output = BytesIO()
        workbook.save(output)
        return output.getvalue()
    finally:
        workbook.close()


def render_invoice_pdf(
    invoice: dict[str, Any],
    client: dict[str, Any],
    business: dict[str, Any],
    template_path: Path = TEMPLATE_PATH,
) -> bytes:
    """Render the invoice PDF.

    Default engine ("template"): the filled Excel invoice sheet is drawn cell
    for cell, so the PDF is the exact Excel format and needs no Office or
    printer. Other engines via SFT_PDF_ENGINE: "excel" (Microsoft Excel COM,
    needs a working default printer) and "native" (a separate ReportLab layout).
    """
    engine = _pdf_engine()
    if engine == "excel":
        workbook_content = render_invoice_excel(invoice, client, business, template_path)
        return _convert_excel_template_to_pdf(workbook_content)
    if engine == "native":
        from app.services.invoice_pdf_service import render_invoice_pdf_native

        return render_invoice_pdf_native(invoice, client, business)
    from app.services.xlsx_pdf_renderer import render_sheet_pdf

    workbook_content = render_invoice_excel(invoice, client, business, template_path)
    return render_sheet_pdf(workbook_content, "original")


def _pdf_engine() -> str:
    return os.environ.get("SFT_PDF_ENGINE", "template").strip().lower()


def _convert_excel_template_to_pdf(workbook_content: bytes) -> bytes:
    if sys.platform != "win32":
        raise WorkbookAccessError(
            "PDF export requires Microsoft Excel on the Windows machine running the backend."
        )

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise WorkbookAccessError(
            "PDF export requires pywin32 and Microsoft Excel on the Windows machine running the backend."
        ) from exc

    with tempfile.TemporaryDirectory(prefix="sft-invoice-pdf-") as temp_dir:
        temp_path = Path(temp_dir)
        workbook_path = temp_path / "invoice.xlsx"
        pdf_path = temp_path / "invoice.pdf"
        workbook_path.write_bytes(workbook_content)

        excel = None
        workbook = None
        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            workbook = excel.Workbooks.Open(
                str(workbook_path),
                UpdateLinks=0,
                ReadOnly=True,
                AddToMru=False,
            )
            workbook.Worksheets("original").ExportAsFixedFormat(
                0,
                str(pdf_path),
                IgnorePrintAreas=False,
            )
            if not pdf_path.is_file():
                raise WorkbookAccessError("Microsoft Excel did not create the invoice PDF.")
            return pdf_path.read_bytes()
        except WorkbookAccessError:
            raise
        except Exception as exc:
            raise WorkbookAccessError(
                "Could not export the invoice template to PDF. Ensure Microsoft Excel is installed "
                "on the machine running the backend."
            ) from exc
        finally:
            try:
                if workbook is not None:
                    workbook.Close(SaveChanges=False)
            finally:
                try:
                    if excel is not None:
                        excel.Quit()
                finally:
                    if com_initialized:
                        pythoncom.CoUninitialize()


def _safe_file_name(invoice_number: str) -> str:
    safe_number = re.sub(r"[^A-Za-z0-9._-]+", "-", invoice_number).strip("-._")
    return f"Invoice_{safe_number or 'export'}.xlsx"


def export_invoice_excel(invoice_id: str) -> InvoiceExcelExport:
    invoice = invoice_service.get_invoice(invoice_id)
    client = client_service.get_client(invoice["clientId"])
    business = business_service.get_business_profile()
    content = render_invoice_excel(invoice, client, business)
    return InvoiceExcelExport(
        content=content,
        file_name=_safe_file_name(str(invoice["number"])),
        warnings=UNSUPPORTED_FIELDS,
    )


def export_invoice_pdf(invoice_id: str) -> InvoiceExcelExport:
    invoice = invoice_service.get_invoice(invoice_id)
    client = client_service.get_client(invoice["clientId"])
    business = business_service.get_business_profile()
    content = render_invoice_pdf(invoice, client, business)
    return InvoiceExcelExport(
        content=content,
        file_name=f"{Path(_safe_file_name(str(invoice['number']))).stem}.pdf",
        warnings=[] if _pdf_engine() == "native" else UNSUPPORTED_FIELDS,
    )