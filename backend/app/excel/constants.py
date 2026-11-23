"""Workbook-level constants: sheet names and column headers.

Every sheet's header row is defined once here and used both when
creating a fresh workbook and when reading/writing rows, so the column
order never drifts between the two.
"""
from __future__ import annotations

SHEET_BUSINESS_PROFILE = "BusinessProfile"
SHEET_CLIENTS = "Clients"
SHEET_INVOICES = "Invoices"
SHEET_INVOICE_ITEMS = "InvoiceItems"
SHEET_PAYMENTS = "Payments"
SHEET_ACTIVITIES = "Activities"
SHEET_INVOICE_NUMBER_RESERVATIONS = "InvoiceNumberReservations"

ALL_SHEETS = [
    SHEET_BUSINESS_PROFILE,
    SHEET_CLIENTS,
    SHEET_INVOICES,
    SHEET_INVOICE_ITEMS,
    SHEET_PAYMENTS,
    SHEET_ACTIVITIES,
    SHEET_INVOICE_NUMBER_RESERVATIONS,
]

# BusinessProfile is a single-record "key/value" sheet (one header row +
# exactly one data row) rather than a table, since there's only ever one
# business identity for this workspace.
BUSINESS_PROFILE_HEADERS = [
    "name", "logoUrl", "address", "email", "phone", "gstin", "pan",
    "bank_accountHolder", "bank_bankName", "bank_branch", "bank_accountNumber", "bank_ifsc",
    "declaration", "authorizedSignatory", "defaultGst_cgstRate", "defaultGst_sgstRate",
]

CLIENTS_HEADERS = [
    "id", "name", "contactName", "email", "phone", "billingAddress", "gstin", "pan", "notes",
]

INVOICE_NUMBER_RESERVATIONS_HEADERS = ["number", "financialYear", "sequence", "reservedFor", "reservedAt"]

INVOICES_HEADERS = [
    "id", "number", "clientId", "issueDate", "dueDate",
    "cgstRate", "sgstRate", "discount", "roundOff",
    "notes", "terms", "supplierCode", "poNumber", "poDate", "transporter",
    "isDraft", "sentAt", "viewedAt", "paidAt", "cancelledAt", "billedAt",
]

INVOICE_ITEMS_HEADERS = [
    "id", "invoiceId", "productId", "description", "hsnCode", "quantity", "unitPrice",
]

# Payment proof is stored as optional metadata beside the payment row.  The
# workbook keeps these storage names stable while row adapters expose the
# nested ``paymentProof`` domain value to services.
PAYMENT_PROOF_HEADERS = [
    "proof_fileName",
    "proof_mimeType",
    "proof_sizeBytes",
    "proof_uploadedAt",
    "proof_attachmentReference",
]

PAYMENTS_HEADERS = [
    "id", "invoiceId", "clientId", "amount", "method", "receivedAt", "reference",
    *PAYMENT_PROOF_HEADERS,
]

PAYMENT_PROOF_HEADER_TO_FIELD = {
    "proof_fileName": "fileName",
    "proof_mimeType": "mimeType",
    "proof_sizeBytes": "sizeBytes",
    "proof_uploadedAt": "uploadedAt",
    "proof_attachmentReference": "attachmentReference",
}

ACTIVITIES_HEADERS = [
    "id", "type", "occurredAt", "summary", "clientId", "invoiceId", "paymentId", "amount",
]

HEADERS_BY_SHEET = {
    SHEET_BUSINESS_PROFILE: BUSINESS_PROFILE_HEADERS,
    SHEET_CLIENTS: CLIENTS_HEADERS,
    SHEET_INVOICES: INVOICES_HEADERS,
    SHEET_INVOICE_ITEMS: INVOICE_ITEMS_HEADERS,
    SHEET_PAYMENTS: PAYMENTS_HEADERS,
    SHEET_ACTIVITIES: ACTIVITIES_HEADERS,
    SHEET_INVOICE_NUMBER_RESERVATIONS: INVOICE_NUMBER_RESERVATIONS_HEADERS,
}
