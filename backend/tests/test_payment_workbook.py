import unittest

from app.excel.constants import (
    PAYMENT_PROOF_HEADERS,
    SHEET_PAYMENTS,
)
from app.excel.rows import append_row, read_rows, update_payment_proof
from app.excel.workbook import create_new_workbook, ensure_sheets_present


class PaymentWorkbookTests(unittest.TestCase):
    def _payment(self):
        return {
            "id": "payment-1",
            "invoiceId": "invoice-1",
            "clientId": "client-1",
            "amount": 1250.5,
            "method": "bank_transfer",
            "receivedAt": "2025-05-01T10:00:00+00:00",
            "reference": "UTR-1",
        }

    def _proof(self, reference="payment-proofs/payment-1/proof-a.pdf"):
        return {
            "fileName": "proof-a.pdf",
            "mimeType": "application/pdf",
            "sizeBytes": 128,
            "uploadedAt": "2025-05-01T10:01:00+00:00",
            "attachmentReference": reference,
        }

    def test_new_payment_headers_are_appended_after_existing_columns(self):
        wb = create_new_workbook()
        ws = wb[SHEET_PAYMENTS]

        headers = [ws.cell(row=1, column=index).value for index in range(1, ws.max_column + 1)]

        self.assertEqual(headers[-len(PAYMENT_PROOF_HEADERS) :], PAYMENT_PROOF_HEADERS)

    def test_legacy_payment_sheet_migration_preserves_columns_rows_and_blank_proof(self):
        wb = create_new_workbook()
        ws = wb[SHEET_PAYMENTS]
        append_row(ws, SHEET_PAYMENTS, self._payment())
        legacy_headers = [
            ws.cell(row=1, column=index).value
            for index in range(1, ws.max_column - len(PAYMENT_PROOF_HEADERS) + 1)
        ]
        ws.delete_cols(len(legacy_headers) + 1, len(PAYMENT_PROOF_HEADERS))

        changed = ensure_sheets_present(wb)

        headers = [ws.cell(row=1, column=index).value for index in range(1, ws.max_column + 1)]
        self.assertTrue(changed)
        self.assertEqual(headers[: len(legacy_headers)], legacy_headers)
        self.assertEqual(headers[-len(PAYMENT_PROOF_HEADERS) :], PAYMENT_PROOF_HEADERS)
        self.assertEqual(read_rows(ws, SHEET_PAYMENTS)[0]["id"], "payment-1")
        self.assertIsNone(read_rows(ws, SHEET_PAYMENTS)[0]["paymentProof"])
        self.assertTrue(
            all(
                ws.cell(row=2, column=headers.index(header) + 1).value is None
                for header in PAYMENT_PROOF_HEADERS
            )
        )

    def test_partial_proof_metadata_is_unavailable_not_reconstructed(self):
        wb = create_new_workbook()
        ws = wb[SHEET_PAYMENTS]
        append_row(ws, SHEET_PAYMENTS, self._payment())
        headers = {
            ws.cell(row=1, column=index).value: index
            for index in range(1, ws.max_column + 1)
        }
        ws.cell(row=2, column=headers["proof_fileName"], value="proof-a.pdf")
        ws.cell(row=2, column=headers["proof_mimeType"], value="application/pdf")

        row = read_rows(ws, SHEET_PAYMENTS)[0]

        self.assertEqual(row["id"], "payment-1")
        self.assertIsNone(row["paymentProof"])
        self.assertTrue(row["proofUnavailable"])

    def test_enrichment_and_replacement_update_one_row_and_round_trip_nested_proof(self):
        wb = create_new_workbook()
        ws = wb[SHEET_PAYMENTS]
        append_row(ws, SHEET_PAYMENTS, self._payment())
        initial_row_count = ws.max_row

        enriched = update_payment_proof(ws, "payment-1", self._proof())
        self.assertEqual(ws.max_row, initial_row_count)
        self.assertEqual(enriched["paymentProof"], self._proof())
        self.assertEqual(len(read_rows(ws, SHEET_PAYMENTS)), 1)

        replacement = self._proof("payment-proofs/payment-1/proof-b.pdf")
        replacement["fileName"] = "proof-b.pdf"
        replaced = update_payment_proof(ws, "payment-1", replacement)

        self.assertEqual(ws.max_row, initial_row_count)
        self.assertEqual(len(read_rows(ws, SHEET_PAYMENTS)), 1)
        self.assertEqual(replaced["paymentProof"], replacement)
        self.assertEqual(read_rows(ws, SHEET_PAYMENTS)[0]["paymentProof"], replacement)

    def test_partial_proof_is_rejected_when_writing_enrichment(self):
        wb = create_new_workbook()
        ws = wb[SHEET_PAYMENTS]
        append_row(ws, SHEET_PAYMENTS, self._payment())

        with self.assertRaises(ValueError):
            update_payment_proof(ws, "payment-1", {"fileName": "proof.pdf"})

        self.assertIsNone(read_rows(ws, SHEET_PAYMENTS)[0]["paymentProof"])


if __name__ == "__main__":
    unittest.main()
