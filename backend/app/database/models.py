"""Initial SQLite schema for the billing domain.

Monetary values are stored as integer paise (100 paise per rupee). Business
dates use YYYY-MM-DD strings; event timestamps use ISO-8601 UTC strings. These
date and timestamp conventions are documented here but are not normalized or
validated by the ORM. Product weight and inventory quantities are stored as
integer thousandths of their declared unit; stock remains unknown until an
opening-stock movement is recorded.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        Index("ix_users_username", "username"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    recovery_key_hash: Mapped[str | None] = mapped_column("recoveryKeyHash", String)
    mobile: Mapped[str | None] = mapped_column("mobile", String)
    is_admin: Mapped[bool] = mapped_column("isAdmin", Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column("createdAt", String, nullable=False)
    last_login_at: Mapped[str | None] = mapped_column("lastLoginAt", String)

    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", passive_deletes="all"
    )
    reset_tokens: Mapped[list[PasswordResetToken]] = relationship(
        back_populates="user", passive_deletes="all"
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_user_id", "userId"),
        Index("ix_sessions_expires_at", "expiresAt"),
        Index("ix_sessions_token_hash", "tokenHash", unique=True),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("users.id", name="fk_sessions_userId_users", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column("tokenHash", String, nullable=False)
    expires_at: Mapped[str] = mapped_column("expiresAt", String, nullable=False)
    created_at: Mapped[str] = mapped_column("createdAt", String, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column("lastUsedAt", String)

    user: Mapped[User] = relationship(back_populates="sessions")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_user_id", "userId"),
        Index("ix_password_reset_tokens_token_hash", "tokenHash", unique=True),
        Index("ix_password_reset_tokens_expires_at", "expiresAt"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("users.id", name="fk_password_reset_tokens_userId_users", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column("tokenHash", String, nullable=False)
    expires_at: Mapped[str] = mapped_column("expiresAt", String, nullable=False)
    used_at: Mapped[str | None] = mapped_column("usedAt", String)
    created_at: Mapped[str] = mapped_column("createdAt", String, nullable=False)

    user: Mapped[User] = relationship(back_populates="reset_tokens")


class BusinessProfileRecord(Base):
    __tablename__ = "business_profile"
    __table_args__ = (CheckConstraint("id = 1", name="ck_business_profile_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    name: Mapped[str] = mapped_column(String, nullable=False)
    logo_url: Mapped[str | None] = mapped_column("logoUrl", String)
    address: Mapped[str] = mapped_column(String, nullable=False)
    email: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String)
    gstin: Mapped[str | None] = mapped_column(String)
    pan: Mapped[str | None] = mapped_column(String)
    bank_account_holder: Mapped[str | None] = mapped_column("bank_accountHolder", String)
    bank_bank_name: Mapped[str | None] = mapped_column("bank_bankName", String)
    bank_branch: Mapped[str | None] = mapped_column("bank_branch", String)
    bank_account_number: Mapped[str | None] = mapped_column("bank_accountNumber", String)
    bank_ifsc: Mapped[str | None] = mapped_column("bank_ifsc", String)
    declaration: Mapped[str | None] = mapped_column(String)
    authorized_signatory: Mapped[str | None] = mapped_column("authorizedSignatory", String)
    default_gst_cgst_rate: Mapped[float | None] = mapped_column("defaultGst_cgstRate", Float)
    default_gst_sgst_rate: Mapped[float | None] = mapped_column("defaultGst_sgstRate", Float)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    contact_name: Mapped[str | None] = mapped_column("contactName", String)
    email: Mapped[str | None] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    billing_address: Mapped[str] = mapped_column("billingAddress", String, nullable=False)
    gstin: Mapped[str] = mapped_column(String, nullable=False)
    pan: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)

    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="client", passive_deletes="all"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="client",
        passive_deletes="all",
        foreign_keys="Payment.client_id",
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="client", passive_deletes="all"
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "type IN ('product', 'service')",
            name="ck_products_type",
        ),
        CheckConstraint("defaultUnitPrice >= 0", name="ck_products_defaultUnitPrice"),
        CheckConstraint(
            "defaultGstRate >= 0 AND defaultGstRate <= 1",
            name="ck_products_defaultGstRate",
        ),
        CheckConstraint(
            "weightMilli IS NULL OR weightMilli >= 0",
            name="ck_products_weightMilli",
        ),
        CheckConstraint(
            "(weightMilli IS NULL AND weightUnit IS NULL) OR "
            "(weightMilli IS NOT NULL AND weightUnit IS NOT NULL)",
            name="ck_products_weight_pair",
        ),
        CheckConstraint(
            "weightUnit IS NULL OR weightUnit IN ('g', 'kg', 'ml', 'L')",
            name="ck_products_weightUnit",
        ),
        CheckConstraint(
            "purchaseCost IS NULL OR purchaseCost >= 0",
            name="ck_products_purchaseCost",
        ),
        CheckConstraint(
            "lowStockThresholdMilli IS NULL OR lowStockThresholdMilli >= 0",
            name="ck_products_lowStockThresholdMilli",
        ),
        CheckConstraint(
            "stockOnHandMilli IS NULL OR stockOnHandMilli >= 0",
            name="ck_products_stockOnHandMilli",
        ),
        CheckConstraint(
            "type = 'product' OR lowStockThresholdMilli IS NULL",
            name="ck_products_service_no_stock_threshold",
        ),
        CheckConstraint(
            "type = 'product' OR stockOnHandMilli IS NULL",
            name="ck_products_service_no_stock",
        ),
        UniqueConstraint("code", name="uq_products_code"),
        Index("ix_products_isActive_type_name", "isActive", "type", "name"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    product_type: Mapped[str] = mapped_column("type", String, nullable=False)
    hsn_code: Mapped[str] = mapped_column("hsnCode", String, nullable=False)
    unit: Mapped[str] = mapped_column(String, nullable=False)
    default_unit_price: Mapped[int] = mapped_column(
        "defaultUnitPrice", Integer, nullable=False
    )
    default_gst_rate: Mapped[float] = mapped_column(
        "defaultGstRate", Float, nullable=False
    )
    weight_milli: Mapped[int | None] = mapped_column("weightMilli", Integer)
    weight_unit: Mapped[str | None] = mapped_column("weightUnit", String)
    purchase_cost: Mapped[int | None] = mapped_column("purchaseCost", Integer)
    low_stock_threshold_milli: Mapped[int | None] = mapped_column(
        "lowStockThresholdMilli", Integer
    )
    stock_on_hand_milli: Mapped[int | None] = mapped_column(
        "stockOnHandMilli", Integer
    )
    is_active: Mapped[bool] = mapped_column(
        "isActive", Boolean, nullable=False, default=True
    )
    created_at: Mapped[str] = mapped_column("createdAt", String, nullable=False)
    updated_at: Mapped[str] = mapped_column("updatedAt", String, nullable=False)

    inventory_movements: Mapped[list[InventoryMovement]] = relationship(
        back_populates="product", passive_deletes="all"
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "type IN ('opening', 'receipt', 'issue', 'adjustment')",
            name="ck_inventory_movements_type",
        ),
        CheckConstraint(
            "(type = 'opening' AND quantityChangeMilli >= 0) OR "
            "(type = 'receipt' AND quantityChangeMilli > 0) OR "
            "(type = 'issue' AND quantityChangeMilli < 0) OR "
            "(type = 'adjustment' AND quantityChangeMilli != 0)",
            name="ck_inventory_movements_quantity_change",
        ),
        CheckConstraint(
            "resultingBalanceMilli >= 0",
            name="ck_inventory_movements_resulting_balance",
        ),
        CheckConstraint(
            "type != 'adjustment' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_inventory_movements_adjustment_reason",
        ),
        UniqueConstraint(
            "idempotencyKey",
            name="uq_inventory_movements_idempotencyKey",
        ),
        Index(
            "uq_inventory_movements_opening_product",
            "productId",
            unique=True,
            sqlite_where=text("type = 'opening'"),
        ),
        Index(
            "uq_inventory_movements_invoice_issue",
            "invoiceId",
            "productId",
            unique=True,
            sqlite_where=text("invoiceId IS NOT NULL AND type = 'issue'"),
        ),
        Index(
            "ix_inventory_movements_product_occurredAt",
            "productId",
            "occurredAt",
        ),
        Index("ix_inventory_movements_invoiceId", "invoiceId"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(
        "productId",
        ForeignKey(
            "products.id",
            name="fk_inventory_movements_productId_products",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    movement_type: Mapped[str] = mapped_column("type", String, nullable=False)
    quantity_change_milli: Mapped[int] = mapped_column(
        "quantityChangeMilli", Integer, nullable=False
    )
    resulting_balance_milli: Mapped[int] = mapped_column(
        "resultingBalanceMilli", Integer, nullable=False
    )
    occurred_at: Mapped[str] = mapped_column("occurredAt", String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        "idempotencyKey", String, nullable=False
    )
    invoice_id: Mapped[str | None] = mapped_column(
        "invoiceId",
        ForeignKey(
            "invoices.id",
            name="fk_inventory_movements_invoiceId_invoices",
            ondelete="RESTRICT",
        ),
    )
    reference: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(String)

    product: Mapped[Product] = relationship(back_populates="inventory_movements")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("number", name="uq_invoices_number"),
        UniqueConstraint("id", "clientId", name="uq_invoices_id_clientId"),
        Index("ix_invoices_clientId", "clientId"),
        Index("ix_invoices_issueDate", "issueDate"),
        Index("ix_invoices_dueDate", "dueDate"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    number: Mapped[str] = mapped_column(String, nullable=False)
    client_id: Mapped[str] = mapped_column(
        "clientId",
        ForeignKey("clients.id", name="fk_invoices_clientId_clients", ondelete="RESTRICT"),
        nullable=False,
    )
    issue_date: Mapped[str] = mapped_column("issueDate", String, nullable=False)
    due_date: Mapped[str] = mapped_column("dueDate", String, nullable=False)
    cgst_rate: Mapped[float] = mapped_column("cgstRate", Float, nullable=False)
    sgst_rate: Mapped[float] = mapped_column("sgstRate", Float, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    round_off: Mapped[int] = mapped_column("roundOff", Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(String)
    terms: Mapped[str | None] = mapped_column(String)
    supplier_code: Mapped[str | None] = mapped_column("supplierCode", String)
    po_number: Mapped[str | None] = mapped_column("poNumber", String)
    po_date: Mapped[str | None] = mapped_column("poDate", String)
    transporter: Mapped[str | None] = mapped_column(String)
    is_draft: Mapped[bool] = mapped_column("isDraft", Boolean, nullable=False, default=True)
    sent_at: Mapped[str | None] = mapped_column("sentAt", String)
    viewed_at: Mapped[str | None] = mapped_column("viewedAt", String)
    paid_at: Mapped[str | None] = mapped_column("paidAt", String)
    cancelled_at: Mapped[str | None] = mapped_column("cancelledAt", String)
    billed_at: Mapped[str | None] = mapped_column("billedAt", String)

    customer_name_snapshot: Mapped[str | None] = mapped_column("customerNameSnapshot", String)
    customer_address_snapshot: Mapped[str | None] = mapped_column("customerAddressSnapshot", String)
    customer_phone_snapshot: Mapped[str | None] = mapped_column("customerPhoneSnapshot", String)
    customer_email_snapshot: Mapped[str | None] = mapped_column("customerEmailSnapshot", String)
    customer_gstin_snapshot: Mapped[str | None] = mapped_column("customerGstinSnapshot", String)
    customer_pan_snapshot: Mapped[str | None] = mapped_column("customerPanSnapshot", String)
    business_name_snapshot: Mapped[str | None] = mapped_column("businessNameSnapshot", String)
    business_logo_url_snapshot: Mapped[str | None] = mapped_column("businessLogoUrlSnapshot", String)
    business_address_snapshot: Mapped[str | None] = mapped_column("businessAddressSnapshot", String)
    business_phone_snapshot: Mapped[str | None] = mapped_column("businessPhoneSnapshot", String)
    business_email_snapshot: Mapped[str | None] = mapped_column("businessEmailSnapshot", String)
    business_gstin_snapshot: Mapped[str | None] = mapped_column("businessGstinSnapshot", String)
    business_pan_snapshot: Mapped[str | None] = mapped_column("businessPanSnapshot", String)
    business_bank_account_holder_snapshot: Mapped[str | None] = mapped_column(
        "businessBankAccountHolderSnapshot", String
    )
    business_bank_name_snapshot: Mapped[str | None] = mapped_column(
        "businessBankNameSnapshot", String
    )
    business_bank_branch_snapshot: Mapped[str | None] = mapped_column(
        "businessBankBranchSnapshot", String
    )
    business_bank_account_number_snapshot: Mapped[str | None] = mapped_column(
        "businessBankAccountNumberSnapshot", String
    )
    business_bank_ifsc_snapshot: Mapped[str | None] = mapped_column(
        "businessBankIfscSnapshot", String
    )
    business_declaration_snapshot: Mapped[str | None] = mapped_column(
        "businessDeclarationSnapshot", String
    )
    authorized_signature_reference_snapshot: Mapped[str | None] = mapped_column(
        "authorizedSignatureReferenceSnapshot", String
    )

    client: Mapped[Client] = relationship(back_populates="invoices")
    items: Mapped[list[InvoiceItem]] = relationship(
        back_populates="invoice", passive_deletes="all"
    )
    payments: Mapped[list[Payment]] = relationship(
        back_populates="invoice",
        passive_deletes="all",
        foreign_keys="Payment.invoice_id",
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="invoice", passive_deletes="all"
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (Index("ix_invoice_items_invoiceId", "invoiceId"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(
        "invoiceId",
        ForeignKey(
            "invoices.id",
            name="fk_invoice_items_invoiceId_invoices",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    product_id: Mapped[str | None] = mapped_column("productId", String)
    description: Mapped[str] = mapped_column(String, nullable=False)
    hsn_code: Mapped[str | None] = mapped_column("hsnCode", String)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    unit_price: Mapped[int] = mapped_column("unitPrice", Integer, nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["invoiceId", "clientId"],
            ["invoices.id", "invoices.clientId"],
            name="fk_payments_invoice_client",
            ondelete="RESTRICT",
        ),
        Index("ix_payments_invoiceId", "invoiceId"),
        Index("ix_payments_clientId", "clientId"),
        Index("ix_payments_receivedAt", "receivedAt"),
        UniqueConstraint("proof_attachmentReference", name="uq_payments_proof_attachmentReference"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    invoice_id: Mapped[str] = mapped_column("invoiceId", String, nullable=False)
    client_id: Mapped[str] = mapped_column(
        "clientId",
        ForeignKey("clients.id", name="fk_payments_clientId_clients", ondelete="RESTRICT"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[str] = mapped_column("receivedAt", String, nullable=False)
    reference: Mapped[str | None] = mapped_column(String)
    proof_file_name: Mapped[str | None] = mapped_column("proof_fileName", String)
    proof_mime_type: Mapped[str | None] = mapped_column("proof_mimeType", String)
    proof_size_bytes: Mapped[int | None] = mapped_column("proof_sizeBytes", Integer)
    proof_uploaded_at: Mapped[str | None] = mapped_column("proof_uploadedAt", String)
    proof_attachment_reference: Mapped[str | None] = mapped_column(
        "proof_attachmentReference", String
    )

    invoice: Mapped[Invoice] = relationship(
        back_populates="payments", foreign_keys=[invoice_id]
    )
    client: Mapped[Client] = relationship(
        back_populates="payments", foreign_keys=[client_id]
    )
    activities: Mapped[list[Activity]] = relationship(
        back_populates="payment", passive_deletes="all"
    )


class InvoiceNumberReservation(Base):
    __tablename__ = "invoice_number_reservations"
    __table_args__ = (
        UniqueConstraint("financialYear", "sequence", name="uq_invoice_reservations_year_sequence"),
        UniqueConstraint("reservedFor", name="uq_invoice_reservations_reservedFor"),
        Index("ix_invoice_number_reservations_financialYear", "financialYear"),
    )

    number: Mapped[str] = mapped_column(String, primary_key=True)
    financial_year: Mapped[str] = mapped_column("financialYear", String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_for: Mapped[str | None] = mapped_column("reservedFor", String)
    reserved_at: Mapped[str] = mapped_column("reservedAt", String, nullable=False)


class Activity(Base):
    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_occurredAt", "occurredAt"),
        Index("ix_activities_clientId", "clientId"),
        Index("ix_activities_invoiceId", "invoiceId"),
        Index("ix_activities_paymentId", "paymentId"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[str] = mapped_column("occurredAt", String, nullable=False)
    summary: Mapped[str] = mapped_column(String, nullable=False)
    client_id: Mapped[str | None] = mapped_column(
        "clientId",
        ForeignKey(
            "clients.id",
            name="fk_activities_clientId_clients",
            ondelete="SET NULL",
        ),
    )
    invoice_id: Mapped[str | None] = mapped_column(
        "invoiceId",
        ForeignKey(
            "invoices.id",
            name="fk_activities_invoiceId_invoices",
            ondelete="SET NULL",
        ),
    )
    payment_id: Mapped[str | None] = mapped_column(
        "paymentId",
        ForeignKey(
            "payments.id",
            name="fk_activities_paymentId_payments",
            ondelete="SET NULL",
        ),
    )
    amount: Mapped[int | None] = mapped_column(Integer)

    client: Mapped[Client | None] = relationship(back_populates="activities")
    invoice: Mapped[Invoice | None] = relationship(back_populates="activities")
    payment: Mapped[Payment | None] = relationship(back_populates="activities")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_occurredAt", "occurredAt"),
        Index("ix_notifications_category", "category"),
        Index("ix_notifications_read", "read"),
        Index("ix_notifications_category_read", "category", "read"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    message: Mapped[str] = mapped_column(String, nullable=False)
    reference_id: Mapped[str | None] = mapped_column("referenceId", String)
    reference_type: Mapped[str | None] = mapped_column("referenceType", String)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    occurred_at: Mapped[str] = mapped_column("occurredAt", String, nullable=False)
    read_at: Mapped[str | None] = mapped_column("readAt", String)


class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"
    __table_args__ = (
        Index("ix_recovery_attempts_username", "username"),
        Index("ix_recovery_attempts_created_at", "createdAt"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column("createdAt", String, nullable=False)
