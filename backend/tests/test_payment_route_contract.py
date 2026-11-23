import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.models.schemas import PaymentCreate, PaymentProof
from app.routes.payments import router


PAYMENT_PAYLOAD = {
    "id": "pm-route-contract",
    "invoiceId": "invoice-route-contract",
    "clientId": "client-route-contract",
    "amount": 1250,
    "method": "upi",
    "receivedAt": "2025-06-15T10:30:00+00:00",
    "reference": "ROUTE-CONTRACT",
}
PAYMENT_RESPONSE = {**PAYMENT_PAYLOAD}


class PaymentRouteContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uuid
        cls.unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        cls.client = TestClient(app)

        # Set up authentication using global database
        from app.services.auth_service import create_user, get_user_by_username
        from app.database.session import get_db_session

        db_gen = get_db_session()
        db = next(db_gen)
        try:
            existing_user = get_user_by_username(db, cls.unique_username)
            if existing_user is None:
                create_user(db, username=cls.unique_username, password="TestPass123!", is_admin=True)
                db.commit()
        finally:
            next(db_gen, None)
            db.close()

        # Login to get a session token
        login_response = cls.client.post(
            "/api/auth/login",
            json={"username": cls.unique_username, "password": "TestPass123!", "remember": True}
        )
        cls.auth_headers = {"Authorization": f"Bearer {login_response.json()['token']}"}

    def test_json_payment_keeps_existing_service_boundary_and_response_shape(self):
        with patch(
            "app.routes.payments.payment_service.record_payment",
            return_value=PAYMENT_RESPONSE,
        ) as record_payment:
            response = self.client.post("/api/payments", json=PAYMENT_PAYLOAD, headers=self.auth_headers)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json(), PAYMENT_RESPONSE)
        record_payment.assert_called_once_with(PAYMENT_PAYLOAD)

    def test_multipart_request_accepts_exactly_one_proof_file_without_client_reference(self):
        form_fields = {
            key: str(value)
            for key, value in PAYMENT_PAYLOAD.items()
            if key != "amount"
        }
        form_fields["amount"] = "1250"

        with patch(
            "app.routes.payments.payment_service.record_payment",
            return_value=PAYMENT_RESPONSE,
        ) as record_payment:
            response = self.client.post(
                "/api/payments",
                data=form_fields,
                files={"proof": ("receipt.pdf", b"proof-bytes", "application/pdf")},
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 201)
        delegated_payload = record_payment.call_args.args[0]
        upload = delegated_payload.pop("_proof_upload")
        self.assertEqual(delegated_payload["amount"], 1250.0)
        self.assertEqual(upload["fileName"], "receipt.pdf")
        self.assertEqual(upload["mimeType"], "application/pdf")
        self.assertEqual(upload["sizeBytes"], len(b"proof-bytes"))
        self.assertEqual(upload["content"], b"proof-bytes")
        self.assertNotIn("attachmentReference", upload)

    def test_client_supplied_attachment_reference_is_rejected_before_service_call(self):
        payload = {
            **PAYMENT_PAYLOAD,
            "attachmentReference": "payment-proofs/not-client-owned",
        }

        with patch("app.routes.payments.payment_service.record_payment") as record_payment:
            response = self.client.post("/api/payments", json=payload, headers=self.auth_headers)

        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        self.assertIn("attachmentReference", detail["errors"])
        self.assertEqual(detail["proofError"]["code"], "proof_invalid")
        self.assertFalse(detail["proofError"]["retryable"])
        record_payment.assert_not_called()

    def test_multiple_uploaded_files_are_rejected(self):
        with patch("app.routes.payments.payment_service.record_payment") as record_payment:
            response = self.client.post(
                "/api/payments",
                data={key: str(value) for key, value in PAYMENT_PAYLOAD.items()},
                files=[
                    ("proof", ("first.pdf", b"first", "application/pdf")),
                    ("proof", ("second.pdf", b"second", "application/pdf")),
                ],
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["proofError"]["code"], "proof_invalid")
        record_payment.assert_not_called()

    def test_schema_exposes_response_proof_but_rejects_request_reference(self):
        proof = PaymentProof(
            fileName="receipt.pdf",
            mimeType="application/pdf",
            sizeBytes=11,
            uploadedAt="2025-06-15T10:30:00+00:00",
            attachmentReference="payment-proofs/pm-route-contract/token",
        )
        self.assertEqual(proof.attachmentReference, "payment-proofs/pm-route-contract/token")

        with self.assertRaises(ValidationError):
            PaymentCreate.model_validate(
                {
                    **PAYMENT_PAYLOAD,
                    "attachmentReference": proof.attachmentReference,
                }
            )

    def test_service_proof_envelopes_are_preserved_by_the_route(self):
        retained_payment = {**PAYMENT_RESPONSE}
        proof_error = {
            "code": "proof_unavailable",
            "stage": "readback",
            "message": "Payment was recorded, but its proof could not be read back. Retry the proof upload.",
            "paymentId": PAYMENT_PAYLOAD["id"],
            "retryable": True,
        }
        with patch(
            "app.routes.payments.payment_service.record_payment",
            return_value={"payment": retained_payment, "proofError": proof_error},
        ):
            response = self.client.post("/api/payments", json=PAYMENT_PAYLOAD, headers=self.auth_headers)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["payment"], retained_payment)
        self.assertEqual(response.json()["detail"]["proofError"], proof_error)

        with patch(
            "app.routes.payments.payment_service.record_payment",
            return_value={"payment": retained_payment},
        ):
            success = self.client.post("/api/payments", json=PAYMENT_PAYLOAD, headers=self.auth_headers)

        self.assertEqual(success.status_code, 201)
        self.assertEqual(success.json(), {"payment": retained_payment})


if __name__ == "__main__":
    unittest.main()
