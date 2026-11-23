"""SQLite payment persistence and durable filesystem-proof orchestration.

Existing payment deletion remains physical because the API already exposes it;
financial-retention policy may tighten that behavior separately. Historical
Excel payments are intentionally left untouched and are not included in totals.
"""
from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from app.repositories.invoice_repository import invoice_repository
from app.repositories.payment_repository import (
    payment_repository,
    to_paise,
)
from app.services import activity_service
from app.services.calculation_service import compute_invoice_totals
from app.services.payment_proof_service import (
    AttachmentEnrichmentError,
    AttachmentReadbackError,
    AttachmentSecurityError,
    AttachmentServiceError,
    AttachmentUpload,
    AttachmentValidationError,
    get_payment_proof_service,
)
from app.utils.errors import NotFoundError, ValidationFailedError
from app.utils.validators import new_id, now_iso

VALID_METHODS = {"bank_transfer", "card", "upi", "cheque", "cash"}
_PROOF_UPLOAD_KEY = "_proof_upload"
_ALLOWED_PROOF_ERROR_STAGES = {"write", "readback", "metadata_enrichment", "cleanup"}
logger = logging.getLogger(__name__)


def _validate(payload: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not payload.get("invoiceId"):
        errors["invoiceId"] = "Invoice is required."
    amount = payload.get("amount")
    if (
        amount is None
        or isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(float(amount))
        or amount <= 0
    ):
        errors["amount"] = "Amount must be a number greater than zero."
    if payload.get("method") not in VALID_METHODS:
        errors["method"] = "Select a valid payment method."
    return errors


def list_payments() -> list[dict[str, Any]]:
    return payment_repository.list_all()


def list_payments_for_invoice(invoice_id: str) -> list[dict[str, Any]]:
    return payment_repository.list_for_invoice(invoice_id)


def get_payment(payment_id: str) -> dict[str, Any]:
    payment = payment_repository.get_by_id(payment_id)
    if payment is None:
        raise NotFoundError(f"Payment {payment_id} not found.")
    return payment


def _invoice_total_paise(invoice: dict[str, Any]) -> int:
    totals = compute_invoice_totals(
        items=invoice["items"],
        cgst_rate=float(invoice["cgstRate"]),
        sgst_rate=float(invoice["sgstRate"]),
        discount=float(invoice["discount"] or 0),
        round_off=float(invoice["roundOff"] or 0),
    )
    return to_paise(totals["total"])


def _get_invoice(invoice_id: str) -> dict[str, Any]:
    invoice = invoice_repository.get_by_id(invoice_id)
    if invoice is None:
        raise NotFoundError(f"Invoice {invoice_id} not found.")
    return invoice


def _allocate_payment_id(requested_id: Any) -> str:
    if isinstance(requested_id, str) and requested_id.strip():
        return requested_id
    for _ in range(100):
        candidate = new_id("pm")
        if not payment_repository.exists_by_id(candidate):
            return candidate
    raise RuntimeError("Could not allocate a unique payment identity.")


def _coerce_proof_upload(payload: Mapping[str, Any]) -> AttachmentUpload | None:
    raw_upload = payload.get(_PROOF_UPLOAD_KEY)
    if raw_upload is None:
        return None
    if isinstance(raw_upload, (list, tuple)):
        raise AttachmentValidationError(
            "Payment proof must contain one uploaded file.",
            category="multiple_uploads",
            stage="write",
            retryable=False,
        )
    if isinstance(raw_upload, AttachmentUpload):
        return raw_upload
    if isinstance(raw_upload, Mapping):
        return AttachmentUpload.from_mapping(raw_upload)
    raise AttachmentValidationError(
        "Payment proof upload is invalid.",
        category="invalid_upload",
        stage="write",
        retryable=False,
    )


def _proof_error(
    payment_id: str,
    error: Exception,
    *,
    default_stage: str = "write",
) -> dict[str, Any]:
    """Map internal proof failures to one safe, actionable response error."""
    if isinstance(error, AttachmentReadbackError):
        code = "proof_unavailable"
        stage = "readback"
        message = "Payment was recorded, but its proof could not be read back. Retry the proof upload."
    elif isinstance(error, AttachmentValidationError) or isinstance(error, AttachmentSecurityError):
        code = "proof_invalid"
        stage = "write"
        message = "Payment was recorded, but the proof upload is invalid. Choose one valid file and retry."
    else:
        code = "proof_storage_failed"
        stage = getattr(error, "stage", default_stage)
        if stage not in _ALLOWED_PROOF_ERROR_STAGES:
            stage = default_stage if default_stage in _ALLOWED_PROOF_ERROR_STAGES else "write"
        if stage == "readback":
            message = "Payment was recorded, but its proof could not be read back. Retry the proof upload."
            code = "proof_unavailable"
        elif stage == "metadata_enrichment":
            message = "Payment was recorded, but its proof metadata could not be saved. Retry the proof upload."
        else:
            message = "Payment was recorded, but its proof could not be stored. Retry the proof upload."

    retryable = getattr(error, "retryable", None)
    if not isinstance(retryable, bool):
        retryable = code != "proof_invalid"

    return {
        "code": code,
        "stage": stage,
        "message": message,
        "paymentId": payment_id,
        "retryable": retryable,
    }


def _log_cleanup_diagnostic(payment_id: str, error: Exception) -> None:
    diagnostic = getattr(error, "cleanup_diagnostic_category", None)
    if diagnostic:
        # Only the safe category and stable domain id are logged; never an OS
        # exception, configured root, or server filesystem path.
        logger.warning(
            "Payment proof cleanup diagnostic category=%s payment_id=%s",
            diagnostic,
            payment_id,
        )


def _retained_payment(payment_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_payment(payment_id)
    except NotFoundError:
        # The durable row was already committed before proof handling began.
        # A reload failure must not manufacture a second payment or lose the
        # identity that the caller can use to retry proof handling.
        return fallback


def _proof_failure(
    payment_id: str,
    fallback: dict[str, Any],
    error: Exception,
    *,
    default_stage: str = "write",
) -> dict[str, Any]:
    _log_cleanup_diagnostic(payment_id, error)
    retained = _retained_payment(payment_id, fallback)
    return {
        "payment": retained,
        "proofError": _proof_error(payment_id, error, default_stage=default_stage),
    }


def _persist_proof(
    payment_id: str,
    upload: AttachmentUpload,
    fallback_payment: dict[str, Any],
) -> dict[str, Any]:
    """Stage/read/enrich one proof before cleaning any prior proof file."""
    try:
        current_payment = payment_repository.get_by_id(payment_id)
        if current_payment is None:
            raise AttachmentEnrichmentError(
                "Payment proof metadata could not be enriched.",
                category="payment_not_found",
                stage="metadata_enrichment",
                retryable=True,
            )

        previous_proof = current_payment.get("paymentProof")
        prior_reference = (
            previous_proof.get("attachmentReference")
            if isinstance(previous_proof, Mapping)
            else None
        )
        attachment_service = get_payment_proof_service()

        def enrich(metadata: dict[str, Any]) -> None:
            if payment_repository.update_proof(payment_id, metadata) is None:
                raise AttachmentEnrichmentError(
                    "Payment proof metadata could not be enriched.",
                    category="payment_not_found",
                    stage="metadata_enrichment",
                    retryable=True,
                )

        replacement = attachment_service.replace(
            payment_id,
            upload,
            prior_reference=prior_reference,
            metadata_enricher=enrich,
        )
        if not replacement.prior_cleanup.success:
            logger.warning(
                "Payment proof cleanup diagnostic category=%s payment_id=%s",
                replacement.prior_cleanup.diagnostic_category or "cleanup_failed",
                payment_id,
            )
        return {"payment": get_payment(payment_id)}
    except AttachmentServiceError as error:
        return _proof_failure(
            payment_id,
            fallback_payment,
            error,
            default_stage="metadata_enrichment",
        )
    except Exception as error:
        # Keep filesystem and metadata adapter failures inside the existing
        # proof-specific retained-payment
        # envelope instead of turning it into a duplicate/retryable payment.
        return _proof_failure(
            payment_id,
            fallback_payment,
            error,
            default_stage="metadata_enrichment",
        )


def _get_existing_payments_paise(invoice_id: str, exclude_payment_id: str | None = None) -> int:
    """Get total of existing payments for an invoice, optionally excluding one payment ID."""
    return payment_repository.total_paid_paise(invoice_id, exclude_payment_id=exclude_payment_id)


def _validate_payment_amount(
    invoice_id: str,
    new_amount_paise: int,
    invoice_total_paise: int,
    existing_payment_id: str | None = None,
) -> None:
    """
    Validate that the new payment amount doesn't exceed the remaining balance.

    Args:
        invoice_id: The invoice ID
        new_amount_paise: The new payment amount in paise
        invoice_total_paise: The total invoice amount in paise
        existing_payment_id: If replacing a payment, exclude this payment from existing total

    Raises:
        ValidationFailedError: If cumulative payments would exceed invoice total
    """
    existing_paid_paise = _get_existing_payments_paise(invoice_id, exclude_payment_id=existing_payment_id)
    remaining_paise = invoice_total_paise - existing_paid_paise

    if new_amount_paise > remaining_paise:
        remaining_rupees = remaining_paise / 100.0
        new_amount_rupees = new_amount_paise / 100.0
        raise ValidationFailedError({
            "amount": f"Payment amount ({new_amount_rupees:.2f}) exceeds remaining balance ({remaining_rupees:.2f}). "
                      f"Invoice total: {invoice_total_paise/100:.2f}, already paid: {existing_paid_paise/100:.2f}."
        })


def record_payment(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a payment in SQLite once, then optionally enrich its proof metadata."""
    errors = _validate(payload)
    if errors:
        raise ValidationFailedError(errors)

    # Validate the invoice before inspecting proof data or allocating an id.
    invoice_id = payload["invoiceId"]
    invoice_row = _get_invoice(invoice_id)
    requested_id = payload.get("id")
    existing_payment = None
    if isinstance(requested_id, str) and requested_id.strip():
        existing_payment = payment_repository.get_by_id(requested_id)

    # A POST carrying an existing payment id is the approved replacement
    # boundary. It must never append another ledger row or emit activity.
    if existing_payment is not None:
        if existing_payment.get("invoiceId") != invoice_id:
            raise ValidationFailedError(
                {"invoiceId": "This payment identity is already associated with another invoice."}
            )

        # Validate replacement amount against remaining balance (excluding the payment being replaced)
        new_amount_paise = to_paise(Decimal(str(payload["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        invoice_total_paise = _invoice_total_paise(invoice_row)
        _validate_payment_amount(invoice_id, new_amount_paise, invoice_total_paise, existing_payment_id=requested_id)

        # Update the payment amount if it changed
        if "amount" in payload:
            updated = payment_repository.update(
                requested_id,
                {"amount": float(Decimal(str(payload["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))},
                {invoice_id: invoice_total_paise},
            )
            if updated is None:
                raise NotFoundError(f"Payment {requested_id} not found during update.")
            existing_payment = updated

        try:
            proof_upload = _coerce_proof_upload(payload)
        except AttachmentServiceError as error:
            return _proof_failure(requested_id, existing_payment, error)
        if proof_upload is None:
            return existing_payment
        return _persist_proof(requested_id, proof_upload, existing_payment)

    payment_id = _allocate_payment_id(requested_id)
    client_id = payload.get("clientId") or invoice_row["clientId"]
    if client_id != invoice_row["clientId"]:
        raise ValidationFailedError(
            {"clientId": "Client must match the selected invoice."}
        )

    # Validate new payment amount against remaining balance
    new_amount_paise = to_paise(Decimal(str(payload["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    invoice_total_paise = _invoice_total_paise(invoice_row)
    _validate_payment_amount(invoice_id, new_amount_paise, invoice_total_paise)

    row = {
        "id": payment_id,
        "invoiceId": invoice_id,
        "clientId": client_id,
        "amount": float(Decimal(str(payload["amount"])).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "method": payload["method"],
        "receivedAt": payload.get("receivedAt") or now_iso(),
        "reference": (payload.get("reference") or "").strip() or None,
    }
    row = payment_repository.create(row, invoice_total_paise)

    activity_service.add_activity_event({
        "type": "payment_received",
        "occurredAt": row["receivedAt"],
        "summary": f"Payment of {row['amount']} received for invoice {invoice_row['number']}",
        "clientId": client_id,
        "invoiceId": invoice_id,
        "paymentId": payment_id,
        "amount": row["amount"],
    })

    try:
        proof_upload = _coerce_proof_upload(payload)
    except AttachmentServiceError as error:
        return _proof_failure(payment_id, row, error)
    if proof_upload is None:
        return row
    return _persist_proof(payment_id, proof_upload, row)


def delete_payment(payment_id: str) -> None:
    existing = payment_repository.get_by_id(payment_id)
    if existing is None:
        raise NotFoundError(f"Payment {payment_id} not found.")
    invoice = _get_invoice(existing["invoiceId"])
    deleted = payment_repository.delete(payment_id, _invoice_total_paise(invoice))
    if deleted is None:
        raise NotFoundError(f"Payment {payment_id} not found.")
    proof = deleted.get("paymentProof")
    reference = proof.get("attachmentReference") if isinstance(proof, Mapping) else None
    if reference:
        cleanup = get_payment_proof_service().cleanup_reference(
            reference, payment_id=payment_id
        )
        if not cleanup.success:
            logger.warning(
                "Payment proof cleanup diagnostic category=%s payment_id=%s",
                cleanup.diagnostic_category or "cleanup_failed",
                payment_id,
            )