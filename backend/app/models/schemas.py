"""Pydantic schemas for SFT Billing.

These mirror the frontend TypeScript types 1:1 (src/types/*.ts in
sft-billing-phase2.2-gst) so the eventual apiDataProvider.ts implementation
of DataProvider can map straight onto these response shapes without any
field renaming.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

GSTIN_PATTERN = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"


# ---------------------------------------------------------------------------
# Business profile
# ---------------------------------------------------------------------------
class BankDetails(BaseModel):
    accountHolder: str
    bankName: str
    branch: str
    accountNumber: str
    ifsc: str


class DefaultGst(BaseModel):
    cgstRate: float = Field(ge=0, le=1)
    sgstRate: float = Field(ge=0, le=1)


class BusinessProfile(BaseModel):
    name: str
    logoUrl: Optional[str] = None
    address: str
    email: EmailStr
    phone: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    bank: Optional[BankDetails] = None
    declaration: Optional[str] = None
    authorizedSignatory: Optional[str] = None
    defaultGst: Optional[DefaultGst] = None


class BusinessProfileUpdate(BaseModel):
    name: Optional[str] = None
    logoUrl: Optional[str] = None
    address: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    bank: Optional[BankDetails] = None
    declaration: Optional[str] = None
    authorizedSignatory: Optional[str] = None
    defaultGst: Optional[DefaultGst] = None


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
class ClientBase(BaseModel):
    name: str = Field(min_length=1)
    contactName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    billingAddress: str = Field(min_length=1)
    gstin: str = Field(min_length=1)
    pan: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("email", "phone", "pan", mode="before")
    @classmethod
    def normalize_blank_optional_contacts(cls, value: Any) -> Optional[str]:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("gstin")
    @classmethod
    def validate_gstin(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return v
        import re

        if not re.match(GSTIN_PATTERN, v.upper()):
            raise ValueError("Invalid GSTIN format")
        return v.upper()


class ClientCreate(ClientBase):
    id: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    contactName: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    billingAddress: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("email", "phone", "pan", mode="before")
    @classmethod
    def normalize_blank_optional_contacts(cls, value: Any) -> Optional[str]:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class Client(ClientBase):
    id: str


# ---------------------------------------------------------------------------
# Invoice line items
# ---------------------------------------------------------------------------
class InvoiceLineItemBase(BaseModel):
    productId: Optional[str] = None
    description: str = Field(min_length=1)
    hsnCode: Optional[str] = None
    quantity: float = Field(gt=0)
    unitPrice: float = Field(ge=0)


class InvoiceLineItemCreate(InvoiceLineItemBase):
    id: Optional[str] = None
    invoiceId: Optional[str] = None


class InvoiceLineItemUpdate(BaseModel):
    productId: Optional[str] = None
    description: Optional[str] = None
    hsnCode: Optional[str] = None
    quantity: Optional[float] = Field(default=None, gt=0)
    unitPrice: Optional[float] = Field(default=None, ge=0)


class InvoiceLineItem(InvoiceLineItemBase):
    id: str
    invoiceId: str


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
class InvoiceStatus(str, Enum):
    draft = "draft"
    sent = "sent"
    partially_paid = "partially_paid"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"


class InvoiceGst(BaseModel):
    cgstRate: float = Field(ge=0, le=1)
    sgstRate: float = Field(ge=0, le=1)


class InvoiceBase(BaseModel):
    clientId: str
    issueDate: str
    dueDate: str
    gst: InvoiceGst
    discount: float = Field(default=0, ge=0)
    roundOff: float = 0
    notes: Optional[str] = None
    terms: Optional[str] = None
    supplierCode: Optional[str] = None
    poNumber: Optional[str] = None
    poDate: Optional[str] = None
    transporter: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    id: Optional[str] = None
    number: Optional[str] = None
    items: list[InvoiceLineItemBase] = Field(default_factory=list)
    isDraft: bool = True


class InvoiceUpdate(BaseModel):
    clientId: Optional[str] = None
    issueDate: Optional[str] = None
    dueDate: Optional[str] = None
    gst: Optional[InvoiceGst] = None
    discount: Optional[float] = None
    roundOff: Optional[float] = None
    notes: Optional[str] = None
    terms: Optional[str] = None
    supplierCode: Optional[str] = None
    poNumber: Optional[str] = None
    poDate: Optional[str] = None
    transporter: Optional[str] = None
    items: Optional[list[InvoiceLineItemBase]] = None
    isDraft: Optional[bool] = None
    sentAt: Optional[str] = None
    billedAt: Optional[str] = None
    cancelledAt: Optional[str] = None


class InvoiceTotals(BaseModel):
    subtotal: float
    taxableValue: float
    cgstAmount: float
    sgstAmount: float
    discount: float
    rawTotal: float
    roundOff: float
    total: float
    paidAmount: float
    balanceDue: float
    amountInWords: str


class Invoice(InvoiceBase):
    id: str
    number: str
    items: list[InvoiceLineItem] = Field(default_factory=list)
    isDraft: bool
    sentAt: Optional[str] = None
    viewedAt: Optional[str] = None
    paidAt: Optional[str] = None
    billedAt: Optional[str] = None
    cancelledAt: Optional[str] = None
    status: InvoiceStatus
    totals: InvoiceTotals


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
class PaymentMethod(str, Enum):
    bank_transfer = "bank_transfer"
    card = "card"
    upi = "upi"
    cheque = "cheque"
    cash = "cash"


class PaymentProof(BaseModel):
    """Metadata for the one currently managed proof attachment on a payment."""

    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)
    sizeBytes: int = Field(ge=0)
    uploadedAt: str = Field(min_length=1)
    attachmentReference: str = Field(min_length=1)


class PaymentProofUpload(BaseModel):
    """Internal, input-only representation of one multipart proof upload.

    ``content`` is held only for the current request and is never part of a
    persisted payment or workbook row.  The attachment reference is
    deliberately absent: it is generated by the backend after the payment
    row has a durable identity.
    """

    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1)
    mimeType: str = Field(min_length=1)
    sizeBytes: int = Field(ge=0)
    content: bytes = Field(repr=False)


class PaymentProofErrorCode(str, Enum):
    proof_storage_failed = "proof_storage_failed"
    proof_unavailable = "proof_unavailable"
    proof_invalid = "proof_invalid"


class PaymentProofErrorStage(str, Enum):
    write = "write"
    readback = "readback"
    metadata_enrichment = "metadata_enrichment"
    cleanup = "cleanup"


class PaymentProofError(BaseModel):
    """Actionable proof failure returned while retaining the payment row."""

    model_config = ConfigDict(extra="forbid")

    code: PaymentProofErrorCode
    stage: PaymentProofErrorStage
    message: str = Field(min_length=1)
    paymentId: str = Field(min_length=1)
    retryable: bool


class PaymentBase(BaseModel):
    # Request models must reject proof metadata and all other unknown fields;
    # attachment references are server-generated and are never client input.
    model_config = ConfigDict(extra="forbid")

    invoiceId: str
    amount: float = Field(gt=0)
    method: PaymentMethod
    receivedAt: Optional[str] = None
    reference: Optional[str] = None


class PaymentCreate(PaymentBase):
    id: Optional[str] = None
    clientId: Optional[str] = None


class Payment(PaymentBase):
    id: str
    clientId: str
    receivedAt: str
    paymentProof: Optional[PaymentProof] = None


class RecordPaymentResult(BaseModel):
    """Payment response envelope used when proof handling reports a failure."""

    model_config = ConfigDict(extra="forbid")

    payment: Payment
    proofError: Optional[PaymentProofError] = None


# ---------------------------------------------------------------------------
# Activities
# ---------------------------------------------------------------------------
class ActivityEventType(str, Enum):
    invoice_created = "invoice_created"
    invoice_sent = "invoice_sent"
    invoice_viewed = "invoice_viewed"
    invoice_became_overdue = "invoice_became_overdue"
    invoice_reminder_sent = "invoice_reminder_sent"
    invoice_marked_paid = "invoice_marked_paid"
    payment_received = "payment_received"
    client_added = "client_added"
    note_added = "note_added"


class ActivityEventCreate(BaseModel):
    type: ActivityEventType
    occurredAt: Optional[str] = None
    summary: str
    clientId: Optional[str] = None
    invoiceId: Optional[str] = None
    paymentId: Optional[str] = None
    amount: Optional[float] = None


class ActivityEvent(ActivityEventCreate):
    id: str
    occurredAt: str
