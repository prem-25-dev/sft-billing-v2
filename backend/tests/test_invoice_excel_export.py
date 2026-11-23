from __future__ import annotations

import json
import sys
import unittest
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.routes.invoices import router as invoices_router
from app.services.invoice_excel_export_service import (
    InvoiceExcelExport,
    TEMPLATE_PATH,
    UNSUPPORTED_FIELDS,
    _convert_excel_template_to_pdf,
    export_invoice_excel,
    export_invoice_pdf,
    render_invoice_excel,
    render_invoice_pdf,
)
from app.utils.errors import ValidationFailedError


class InvoiceExcelExportTests(unittest.TestCase):
    def setUp(self):
        self.invoice = {
            "id": "invoice-1",
            "number": "001/2026-27",
            "clientId": "client-1",
            "issueDate": "2026-10-22",
            "dueDate": "2026-11-06",
            "gst": {"cgstRate": 0.09, "sgstRate": 0.09},
            "discount": 0,
            "roundOff": -0.1,
            "items": [
                {
                    "id": "item-1",
                    "description": "=1+1",
                    "hsnCode": "9983",
                    "quantity": 2,
                    "unitPrice": 100.25,
                },
                {
                    "id": "item-2",
                    "description": "Consulting",
                    "hsnCode": "9984",
                    "quantity": 1,
                    "unitPrice": 50,
                },
            ],
            "totals": {
                "subtotal": 250.5,
                "taxableValue": 250.5,
                "cgstAmount": 22.55,
                "sgstAmount": 22.55,
                "roundOff": -0.1,
                "total": 295.5,
                "amountInWords": "Two Hundred Ninety Five Rupees and Fifty Paise Only",
            },
        }
        self.client = {
            "id": "client-1",
            "name": "=Client name",
            "contactName": "Ravi",
            "email": "client@example.com",
            "phone": "9876543210",
            "billingAddress": "12 Lake Road\nChennai\n600001",
            "gstin": "33AAAAA0000A1Z5",
        }
        self.business = {
            "name": "Surfine Technology",
            "address": "Anna Nagar, Tiruvallur",
            "email": "billing@example.com",
            "gstin": "33ACSFS8087P1ZC",
            "pan": "ACSFS8087P",
            "bank": {
                "accountHolder": "Surfine Technology",
                "bankName": "Example Bank",
                "branch": "Tiruvallur",
                "accountNumber": "00123456789",
                "ifsc": "EXAM0000123",
            },
            "declaration": "Declaration from business settings.",
            "authorizedSignatory": "Sabari Krishna",
        }

    def test_renders_data_into_each_copy_and_preserves_template_layout(self):
        source = load_workbook(TEMPLATE_PATH)
        result = render_invoice_excel(self.invoice, self.client, self.business)
        output = load_workbook(BytesIO(result), data_only=False)

        self.assertEqual(output.sheetnames, source.sheetnames)
        self.assertEqual(
            [len(output[sheet]._images) for sheet in output.sheetnames],
            [len(source[sheet]._images) for sheet in source.sheetnames],
        )

        for sheet_name in output.sheetnames:
            worksheet = output[sheet_name]
            original = source[sheet_name]
            self.assertEqual(
                set(map(str, worksheet.merged_cells.ranges)),
                set(map(str, original.merged_cells.ranges)),
            )
            self.assertEqual(worksheet.print_area, original.print_area)
            self.assertEqual(worksheet["C3"].style_id, original["C3"].style_id)
            self.assertEqual(worksheet["A2"].value, original["A2"].value)
            self.assertEqual(worksheet["A8"].value, "=Client name")
            self.assertEqual(worksheet["A8"].data_type, "s")
            self.assertEqual(worksheet["A9"].value, "12 Lake Road")
            self.assertEqual(worksheet["A10"].value, "Chennai")
            self.assertEqual(worksheet["A11"].value, "600001")
            self.assertEqual(worksheet["G8"].value, "Invoice No: 001/2026-27")
            self.assertEqual(worksheet["G9"].value, "Date : 22/10/2026")
            self.assertEqual(worksheet["G13"].value, "No. Of Packages : ")
            self.assertEqual(worksheet["B21"].value, "=1+1")
            self.assertEqual(worksheet["B21"].data_type, "s")
            self.assertEqual(worksheet["H21"].value, 200.5)
            self.assertIsNone(worksheet["G21"].value)
            self.assertEqual(worksheet["A22"].value, 2)
            self.assertIsNone(worksheet["A23"].value)
            hsn_column = (
                "A"
                if "A43:B43" in set(map(str, original.merged_cells.ranges))
                else "B"
            )
            self.assertEqual(worksheet[f"{hsn_column}43"].value, "9983")
            self.assertEqual(worksheet[f"{hsn_column}44"].value, "9984")
            self.assertEqual(worksheet["C43"].value, 200.5)
            self.assertEqual(worksheet["D43"].value, 9)
            self.assertEqual(worksheet["A47"].value, "ROUND OFF : -0.10")
            self.assertEqual(worksheet["H46"].value, 250.5)
            self.assertEqual(worksheet["I47"].value, 295.5)
            self.assertEqual(
                worksheet["A49"].value, "Declaration from business settings."
            )
            self.assertIn("Sabari Krishna", worksheet["F49"].value)
            self.assertEqual(worksheet["A51"].value, self.invoice["totals"]["amountInWords"])
            self.assertIn("Rupees", worksheet["A53"].value)
            self.assertEqual(worksheet.row_dimensions[17].hidden, True)

        source.close()
        output.close()

    def test_rejects_unsupported_discount_and_fixed_template_overflow(self):
        discounted = deepcopy(self.invoice)
        discounted["discount"] = 1
        with self.assertRaises(ValidationFailedError) as error:
            render_invoice_excel(discounted, self.client, self.business)
        self.assertIn("invoice.discount", error.exception.errors)

        too_many_items = deepcopy(self.invoice)
        too_many_items["items"] = too_many_items["items"] * 10
        with self.assertRaises(ValidationFailedError) as error:
            render_invoice_excel(too_many_items, self.client, self.business)
        self.assertIn("items", error.exception.errors)

        too_many_hsn_groups = deepcopy(self.invoice)
        too_many_hsn_groups["items"] = [
            {
                "description": f"Item {index}",
                "hsnCode": f"HSN-{index}",
                "quantity": 1,
                "unitPrice": 1,
            }
            for index in range(4)
        ]
        with self.assertRaises(ValidationFailedError) as error:
            render_invoice_excel(too_many_hsn_groups, self.client, self.business)
        self.assertIn("items.hsnCode", error.exception.errors)

    def test_rejects_address_with_more_than_three_explicit_lines(self):
        client = {**self.client, "billingAddress": "One\nTwo\nThree\nFour"}
        with self.assertRaises(ValidationFailedError) as error:
            render_invoice_excel(self.invoice, client, self.business)
        self.assertIn("client.billingAddress", error.exception.errors)

    def test_export_uses_saved_invoice_client_and_business_records(self):
        with (
            patch(
                "app.services.invoice_excel_export_service.invoice_service.get_invoice",
                return_value=self.invoice,
            ) as get_invoice,
            patch(
                "app.services.invoice_excel_export_service.client_service.get_client",
                return_value=self.client,
            ) as get_client,
            patch(
                "app.services.invoice_excel_export_service.business_service.get_business_profile",
                return_value=self.business,
            ) as get_business,
            patch(
                "app.services.invoice_excel_export_service.render_invoice_excel",
                return_value=b"excel-content",
            ) as render,
        ):
            result = export_invoice_excel("invoice-1")

        get_invoice.assert_called_once_with("invoice-1")
        get_client.assert_called_once_with("client-1")
        get_business.assert_called_once_with()
        render.assert_called_once_with(self.invoice, self.client, self.business)
        self.assertEqual(result.content, b"excel-content")
        self.assertEqual(result.file_name, "Invoice_001-2026-27.xlsx")
        self.assertEqual(result.warnings, UNSUPPORTED_FIELDS)

    def test_pdf_renderer_converts_the_rendered_excel_template(self):
        with (
            patch.dict("os.environ", {"SFT_PDF_ENGINE": "excel"}),
            patch(
                "app.services.invoice_excel_export_service.render_invoice_excel",
                return_value=b"rendered-workbook",
            ) as render,
            patch(
                "app.services.invoice_excel_export_service._convert_excel_template_to_pdf",
                return_value=b"%PDF-template",
            ) as convert,
        ):
            result = render_invoice_pdf(self.invoice, self.client, self.business)

        render.assert_called_once_with(
            self.invoice,
            self.client,
            self.business,
            TEMPLATE_PATH,
        )
        convert.assert_called_once_with(b"rendered-workbook")
        self.assertEqual(result, b"%PDF-template")

    def test_default_pdf_engine_draws_the_excel_sheet_without_office(self):
        workbook = render_invoice_excel(self.invoice, self.client, self.business)
        with patch("app.services.invoice_excel_export_service._convert_excel_template_to_pdf") as convert:
            pdf = render_invoice_pdf(self.invoice, self.client, self.business)
        convert.assert_not_called()
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertTrue(workbook)

    def test_pdf_conversion_exports_only_the_original_template_sheet(self):
        pythoncom = ModuleType("pythoncom")
        pythoncom.CoInitialize = MagicMock()
        pythoncom.CoUninitialize = MagicMock()

        worksheet = MagicMock()
        worksheet.ExportAsFixedFormat.side_effect = (
            lambda _format, path, **_options: Path(path).write_bytes(b"%PDF-template")
        )
        workbook = MagicMock()
        workbook.Worksheets.return_value = worksheet

        excel = MagicMock()
        excel.Workbooks.Open.return_value = workbook
        win32com = ModuleType("win32com")
        win32com.client = ModuleType("win32com.client")
        win32com.client.DispatchEx = MagicMock(return_value=excel)

        with (
            patch.object(sys, "platform", "win32"),
            patch.dict(
                sys.modules,
                {
                    "pythoncom": pythoncom,
                    "win32com": win32com,
                    "win32com.client": win32com.client,
                },
            ),
        ):
            result = _convert_excel_template_to_pdf(b"rendered-workbook")

        self.assertEqual(result, b"%PDF-template")
        workbook.Worksheets.assert_called_once_with("original")
        worksheet.ExportAsFixedFormat.assert_called_once()
        workbook.Close.assert_called_once_with(SaveChanges=False)
        excel.Quit.assert_called_once()
        pythoncom.CoUninitialize.assert_called_once()

    def test_pdf_export_uses_saved_records_and_the_template_converter(self):
        with (
            patch(
                "app.services.invoice_excel_export_service.invoice_service.get_invoice",
                return_value=self.invoice,
            ),
            patch(
                "app.services.invoice_excel_export_service.client_service.get_client",
                return_value=self.client,
            ),
            patch(
                "app.services.invoice_excel_export_service.business_service.get_business_profile",
                return_value=self.business,
            ),
            patch(
                "app.services.invoice_excel_export_service.render_invoice_pdf",
                return_value=b"%PDF-template",
            ) as render,
        ):
            result = export_invoice_pdf("invoice-1")

        render.assert_called_once_with(self.invoice, self.client, self.business)
        self.assertEqual(result.content, b"%PDF-template")
        self.assertEqual(result.file_name, "Invoice_001-2026-27.pdf")
        self.assertEqual(result.warnings, UNSUPPORTED_FIELDS)

    def test_export_route_returns_excel_and_omission_warnings(self):
        import uuid
        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(invoices_router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        client = TestClient(app)

        # First, set up authentication
        from app.services.auth_service import create_user
        from app.database.session import get_db_session

        # Create a test user
        db_gen = get_db_session()
        db = next(db_gen)
        try:
            create_user(db, username=unique_username, password="TestPass123!", is_admin=True)
            db.commit()
        finally:
            next(db_gen, None)
            db.close()

        # Login to get a session token
        login_response = client.post(
            "/api/auth/login",
            json={"username": unique_username, "password": "TestPass123!", "remember": True}
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["token"]

        # Use authenticated client
        auth_headers = {"Authorization": f"Bearer {token}"}

        export = InvoiceExcelExport(
            content=b"excel-content",
            file_name="Invoice_001-2026-27.xlsx",
            warnings=UNSUPPORTED_FIELDS,
        )

        with patch(
            "app.routes.invoices.invoice_excel_export_service.export_invoice_excel",
            return_value=export,
        ):
            response = client.get("/api/invoices/invoice-1/excel", headers=auth_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"excel-content")
        self.assertIn("spreadsheetml.sheet", response.headers["content-type"])
        self.assertIn("Invoice_001-2026-27.xlsx", response.headers["content-disposition"])
        self.assertEqual(
            response.headers["x-invoice-export-warnings"],
            json.dumps(UNSUPPORTED_FIELDS),
        )

    def test_pdf_route_returns_pdf_converted_from_template(self):
        import uuid
        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(invoices_router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        client = TestClient(app)

        # First, set up authentication
        from app.services.auth_service import create_user
        from app.database.session import get_db_session

        # Create a test user
        db_gen = get_db_session()
        db = next(db_gen)
        try:
            create_user(db, username=unique_username, password="TestPass123!", is_admin=True)
            db.commit()
        finally:
            next(db_gen, None)
            db.close()

        # Login to get a session token
        login_response = client.post(
            "/api/auth/login",
            json={"username": unique_username, "password": "TestPass123!", "remember": True}
        )
        self.assertEqual(login_response.status_code, 200)
        token = login_response.json()["token"]

        # Use authenticated client
        auth_headers = {"Authorization": f"Bearer {token}"}

        export = InvoiceExcelExport(
            content=b"%PDF-template-copy",
            file_name="Invoice_001-2026-27.pdf",
            warnings=UNSUPPORTED_FIELDS,
        )

        with patch(
            "app.routes.invoices.invoice_excel_export_service.export_invoice_pdf",
            return_value=export,
        ):
            response = client.get("/api/invoices/invoice-1/pdf", headers=auth_headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"%PDF-template-copy")
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertIn("Invoice_001-2026-27.pdf", response.headers["content-disposition"])
        self.assertEqual(
            response.headers["x-invoice-export-warnings"],
            json.dumps(UNSUPPORTED_FIELDS),
        )


if __name__ == "__main__":
    unittest.main()
