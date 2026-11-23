import re
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy.orm import sessionmaker

from app.excel import workbook as workbook_module
from app.excel.constants import (
    PAYMENT_PROOF_HEADERS,
    SHEET_ACTIVITIES,
    SHEET_CLIENTS,
    SHEET_INVOICE_ITEMS,
    SHEET_INVOICES,
    SHEET_PAYMENTS,
)
from app.excel.rows import append_row, read_rows
from app.excel.workbook import create_new_workbook
from app.database.session import create_database_engine, shutdown_database
from app.repositories.client_repository import ClientRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.activity_repository import ActivityRepository
from app.routes.payments import router
from app.services import activity_service, payment_service
from app.services.payment_proof_service import (
    AttachmentReadbackError,
    AttachmentSecurityError,
    AttachmentWriteError,
    CleanupResult,
    PaymentProofAttachmentService,
)


class PaymentPersistenceIntegrationTests(unittest.TestCase):
    """Exercise the payment route against a real temporary workbook boundary."""

    @classmethod
    def setUpClass(cls):
        import uuid
        cls.unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        cls.client = TestClient(app)
        cls._auth_setup_done = False

    def _ensure_auth(self):
        if not self._auth_setup_done:
            from app.services.auth_service import create_user, get_user_by_username
            from app.database.session import get_db_session

            # Create a test user in the global database (or use existing one)
            db_gen = get_db_session()
            db = next(db_gen)
            try:
                existing_user = get_user_by_username(db, self.unique_username)
                if existing_user is None:
                    create_user(db, username=self.unique_username, password="TestPass123!", is_admin=True)
                    db.commit()
            finally:
                next(db_gen, None)
                db.close()

            # Login to get a session token
            login_response = self.client.post(
                "/api/auth/login",
                json={"username": self.unique_username, "password": "TestPass123!", "remember": True}
            )
            self.assertEqual(login_response.status_code, 200)
            self.token = login_response.json()["token"]
            self.auth_headers = {"Authorization": f"Bearer {self.token}"}
            self._auth_setup_done = True
            self.token = login_response.json()["token"]
            self.auth_headers = {"Authorization": f"Bearer {self.token}"}
            self._auth_setup_done = True

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        temp_root = Path(self.temp_dir.name)
        self.data_dir = temp_root / "data"
        self.workbook_path = self.data_dir / "SFT_Billing.xlsx"
        self.backups_dir = temp_root / "backups"
        self.attachment_root = temp_root / "payment-proofs"
        self.data_dir.mkdir(parents=True)

        workbook = create_new_workbook()
        workbook.save(self.workbook_path)

        self.engine = create_database_engine(
            f"sqlite:///{(temp_root / 'payments.db').as_posix()}"
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.client_repository = ClientRepository(self.session_factory, self.engine)
        self.invoice_repository = InvoiceRepository(self.session_factory, self.engine)
        self.payment_repository = PaymentRepository(self.session_factory, self.engine)
        self.activity_repository = ActivityRepository(
            self.session_factory, self.engine
        )
        self.client_repository.create(
            {
                "id": "client-integration",
                "name": "Integration Client",
                "contactName": "Integration Contact",
                "email": "integration@example.com",
                "phone": "123",
                "billingAddress": "Integration Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "notes": None,
            }
        )
        self.invoice_repository._ensure_schema()
        self.payment_repository._ensure_schema()
        self.activity_repository._ensure_schema()
        self.invoice_repository.create(
            {
                "id": "invoice-integration",
                "number": "INV-INTEGRATION",
                "clientId": "client-integration",
                "issueDate": "2025-06-01",
                "dueDate": "2025-06-30",
                "cgstRate": 0.09,
                "sgstRate": 0.09,
                "discount": 0,
                "roundOff": 0,
                "isDraft": False,
            },
            [
                {
                    "id": "line-integration",
                    "description": "Integration service",
                    "quantity": 1,
                    "unitPrice": 1000,
                }
            ],
        )
        self.attachment_service = PaymentProofAttachmentService(self.attachment_root)
        self.runtime = ExitStack()
        self.runtime.enter_context(
            patch.object(workbook_module, "WORKBOOK_PATH", self.workbook_path)
        )
        self.runtime.enter_context(patch.object(workbook_module, "DATA_DIR", self.data_dir))
        self.runtime.enter_context(
            patch.object(workbook_module, "BACKUPS_DIR", self.backups_dir)
        )
        self.runtime.enter_context(
            patch.object(payment_service, "invoice_repository", self.invoice_repository)
        )
        self.runtime.enter_context(
            patch.object(payment_service, "payment_repository", self.payment_repository)
        )
        self.runtime.enter_context(
            patch.object(
                activity_service,
                "activity_repository",
                self.activity_repository,
            )
        )
        self.runtime.enter_context(
            patch.object(
                payment_service,
                "get_payment_proof_service",
                return_value=self.attachment_service,
            )
        )
        self._ensure_auth()

    def tearDown(self):
        self.runtime.close()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def _payment_rows(self):
        return self.payment_repository.list_all()

    def _activity_rows(self):
        return self.activity_repository.list_all()

    @staticmethod
    def _payment_payload(payment_id=None, *, invoice_id="invoice-integration"):
        payload = {
            "invoiceId": invoice_id,
            "amount": 1180,  # Matches invoice total: 1000 + 90 CGST + 90 SGST
            "method": "upi",
            "receivedAt": "2025-06-15T10:30:00+00:00",
            "reference": "INTEGRATION-REFERENCE",
        }
        if payment_id is not None:
            payload["id"] = payment_id
        return payload

    def _post_proof(self, payload, content=b"proof-content", filename="receipt.pdf"):
        form = {key: str(value) for key, value in payload.items()}
        return self.client.post(
            "/api/payments",
            data=form,
            files={"proof": (filename, content, "application/pdf")},
            headers=self.auth_headers,
        )

    @staticmethod
    def _payment_from_response(response):
        body = response.json()
        return body.get("payment", body)

    def _assert_single_payment_activity(self, payment_id):
        payments = self._payment_rows()
        activities = self._activity_rows()
        self.assertEqual(len(payments), 1)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]["type"], "payment_received")
        self.assertEqual(activities[0]["paymentId"], payment_id)
        self.assertEqual(activities[0]["invoiceId"], "invoice-integration")
        self.assertEqual(activities[0]["paymentId"], payments[0]["id"])

    def _assert_proof_failure(
        self,
        response,
        *,
        payment_id,
        stage,
        code,
        prior_proof=None,
    ):
        self.assertEqual(response.status_code, 422)
        detail = response.json()["detail"]
        payment = detail["payment"]
        proof_error = detail["proofError"]
        self.assertEqual(payment["id"], payment_id)
        self.assertEqual(payment["invoiceId"], "invoice-integration")
        self.assertEqual(payment["paymentProof"], prior_proof)
        self.assertEqual(proof_error["code"], code)
        self.assertEqual(proof_error["stage"], stage)
        self.assertEqual(proof_error["paymentId"], payment_id)
        self.assertTrue(proof_error["message"])
        self.assertIsInstance(proof_error["retryable"], bool)
        return payment, proof_error

    def test_post_and_get_without_proof_allocates_identity_and_survives_reload(self):
        response = self.client.post(
            "/api/payments",
            json=self._payment_payload(),
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        payment = response.json()
        self.assertTrue(payment["id"].startswith("pm_"))
        self.assertEqual(payment["invoiceId"], "invoice-integration")
        self.assertEqual(payment["clientId"], "client-integration")
        self.assertIsNone(payment["paymentProof"])

        listed = self.client.get("/api/payments", headers=self.auth_headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json(), [payment])
        fetched = self.client.get(f"/api/payments/{payment['id']}", headers=self.auth_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), payment)

        reloaded = self._payment_rows()[0]
        self.assertEqual(reloaded["id"], payment["id"])
        self.assertEqual(reloaded["invoiceId"], "invoice-integration")
        self.assertIsNone(reloaded["paymentProof"])
        self._assert_single_payment_activity(payment["id"])

        workbook = workbook_module.load_workbook_safely()
        headers = {
            workbook[SHEET_PAYMENTS].cell(row=1, column=index).value: index
            for index in range(1, workbook[SHEET_PAYMENTS].max_column + 1)
        }
        for header in PAYMENT_PROOF_HEADERS:
            self.assertIsNone(
                workbook[SHEET_PAYMENTS].cell(row=2, column=headers[header]).value
            )

    def test_post_and_get_with_proof_writes_blank_row_before_proof_and_persists_after_reload(self):
        payment_id = "pm-integration-proof"
        durable_snapshots = []
        proof_stage_snapshots = []
        original_activity = activity_service.add_activity_event
        original_replace = self.attachment_service.replace

        def observe_activity(event):
            durable_snapshots.append(self._payment_rows())
            return original_activity(event)

        def observe_proof_stage(payment_id_arg, upload, **kwargs):
            rows = self._payment_rows()
            proof_stage_snapshots.append(rows[0]["paymentProof"])
            return original_replace(payment_id_arg, upload, **kwargs)

        with patch.object(
            activity_service,
            "add_activity_event",
            side_effect=observe_activity,
        ) as activity, patch.object(
            self.attachment_service,
            "replace",
            side_effect=observe_proof_stage,
        ) as replace:
            response = self._post_proof(
                self._payment_payload(payment_id),
                content=b"persisted-proof",
            )

        self.assertEqual(response.status_code, 201)
        payment = self._payment_from_response(response)
        self.assertEqual(payment["id"], payment_id)
        self.assertEqual(payment["invoiceId"], "invoice-integration")
        self.assertEqual(payment["clientId"], "client-integration")
        self.assertEqual(payment["paymentProof"]["fileName"], "receipt.pdf")
        self.assertEqual(payment["paymentProof"]["sizeBytes"], len(b"persisted-proof"))
        reference = payment["paymentProof"]["attachmentReference"]
        self.assertRegex(reference, rf"^{re.escape(payment_id)}/[a-f0-9]{{32}}$")
        self.assertTrue((self.attachment_root / reference).is_file())
        self.assertEqual(durable_snapshots[0][0]["paymentProof"], None)
        self.assertEqual(proof_stage_snapshots, [None])
        self.assertEqual(activity.call_count, 1)
        self.assertEqual(replace.call_count, 1)

        listed = self.client.get("/api/payments", headers=self.auth_headers).json()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["paymentProof"], payment["paymentProof"])
        fetched = self.client.get(f"/api/payments/{payment_id}", headers=self.auth_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["paymentProof"], payment["paymentProof"])
        self._assert_single_payment_activity(payment_id)

    def test_payment_validation_and_unknown_invoice_never_create_payment_or_activity(self):
        invalid = self.client.post(
            "/api/payments",
            json={
                "invoiceId": "invoice-integration",
                "amount": 0,
                "method": "upi",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("amount", invalid.json()["detail"]["errors"])
        self.assertEqual(self._payment_rows(), [])
        self.assertEqual(self._activity_rows(), [])

        unknown_invoice = self.client.post(
            "/api/payments",
            json=self._payment_payload("pm-unknown-invoice", invoice_id="invoice-missing"),
            headers=self.auth_headers,
        )
        self.assertEqual(unknown_invoice.status_code, 404)
        self.assertEqual(self._payment_rows(), [])
        self.assertEqual(self._activity_rows(), [])

    def test_legacy_excel_payments_are_not_imported_or_modified(self):
        workbook = load_workbook(self.workbook_path)
        append_row(
            workbook[SHEET_PAYMENTS],
            SHEET_PAYMENTS,
            {
                "id": "pm-legacy",
                "invoiceId": "invoice-integration",
                "clientId": "client-integration",
                "amount": 100,
                "method": "cash",
                "receivedAt": "2025-06-10T10:00:00+00:00",
                "reference": "LEGACY",
            },
        )
        worksheet = workbook[SHEET_PAYMENTS]
        worksheet.delete_cols(
            worksheet.max_column - len(PAYMENT_PROOF_HEADERS) + 1,
            len(PAYMENT_PROOF_HEADERS),
        )
        workbook.save(self.workbook_path)
        legacy_payment_rows = read_rows(worksheet, SHEET_PAYMENTS)
        legacy_workbook_hash = self.workbook_path.read_bytes()

        active_payments = self.client.get("/api/payments", headers=self.auth_headers)
        self.assertEqual(active_payments.status_code, 200)
        self.assertEqual(active_payments.json(), [])
        self.assertEqual(self._payment_rows(), [])
        self.assertEqual(self.workbook_path.read_bytes(), legacy_workbook_hash)
        reloaded = load_workbook(self.workbook_path, read_only=True, data_only=True)
        try:
            self.assertEqual(
                read_rows(reloaded[SHEET_PAYMENTS], SHEET_PAYMENTS),
                legacy_payment_rows,
            )
        finally:
            reloaded.close()

    def test_reference_safety_rejects_client_metadata_and_keeps_generated_reference_opaque(self):
        fabricated = self.client.post(
            "/api/payments",
            json={
                **self._payment_payload("pm-fabricated-reference"),
                "paymentProof": {
                    "fileName": "fake.pdf",
                    "mimeType": "application/pdf",
                    "sizeBytes": 1,
                    "uploadedAt": "2025-06-15T10:30:00+00:00",
                    "attachmentReference": "../../outside",
                },
            },
            headers=self.auth_headers,
        )
        self.assertEqual(fabricated.status_code, 422)
        self.assertEqual(
            fabricated.json()["detail"]["proofError"]["code"], "proof_invalid"
        )
        self.assertEqual(self._payment_rows(), [])

        response = self._post_proof(
            self._payment_payload("pm-reference-safety"),
            content=b"safe-content",
            filename="../../outside.pdf",
        )
        self.assertEqual(response.status_code, 201)
        payment = self._payment_from_response(response)
        proof = payment["paymentProof"]
        reference = proof["attachmentReference"]
        self.assertRegex(reference, r"^pm-reference-safety/[a-f0-9]{32}$")
        self.assertEqual(proof["fileName"], "outside.pdf")
        self.assertNotIn("outside.pdf", reference)
        self.assertNotIn("..", reference)
        self.assertNotIn("\\", reference)
        stored_path = self.attachment_root / reference
        self.assertEqual(stored_path.relative_to(self.attachment_root), Path(reference))
        self.assertTrue(stored_path.is_file())

        with self.assertRaises(AttachmentSecurityError) as raised:
            self.attachment_service.validate_reference(
                "../pm-reference-safety/" + reference.rsplit("/", 1)[1],
                payment_id="pm-reference-safety",
            )
        self.assertEqual(raised.exception.category, "traversal_reference")

    def test_write_failure_retains_payment_and_cleans_temporary_file(self):
        failure = AttachmentWriteError(
            "safe write failure",
            category="write_failed",
            stage="write",
            retryable=True,
        )
        original_cleanup = self.attachment_service.cleanup
        with patch.object(
            self.attachment_service, "promote", side_effect=failure
        ), patch.object(
            self.attachment_service, "cleanup", wraps=original_cleanup
        ) as cleanup:
            response = self._post_proof(
                self._payment_payload("pm-write-failure"),
                content=b"write-failure",
            )

        payment, _ = self._assert_proof_failure(
            response,
            payment_id="pm-write-failure",
            stage="write",
            code="proof_storage_failed",
        )
        self.assertIsNone(payment["paymentProof"])
        self.assertGreaterEqual(cleanup.call_count, 1)
        self.assertFalse(any(path.is_file() for path in self.attachment_root.rglob("*")))
        self._assert_single_payment_activity("pm-write-failure")

    def test_readback_failure_retains_payment_and_cleans_promoted_file(self):
        failure = AttachmentReadbackError(
            "safe readback failure",
            category="readback_failed",
            stage="readback",
            retryable=True,
        )
        original_cleanup = self.attachment_service.cleanup
        with patch.object(
            self.attachment_service, "validate_readback", side_effect=failure
        ), patch.object(
            self.attachment_service, "cleanup", wraps=original_cleanup
        ) as cleanup:
            response = self._post_proof(
                self._payment_payload("pm-readback-failure"),
                content=b"readback-failure",
            )

        payment, _ = self._assert_proof_failure(
            response,
            payment_id="pm-readback-failure",
            stage="readback",
            code="proof_unavailable",
        )
        self.assertIsNone(payment["paymentProof"])
        self.assertGreaterEqual(cleanup.call_count, 1)
        self.assertFalse(any(path.is_file() for path in self.attachment_root.rglob("*")))
        self._assert_single_payment_activity("pm-readback-failure")

    def test_metadata_enrichment_failure_after_attachment_creation_retains_payment_and_cleans_orphan(self):
        original_cleanup = self.attachment_service.cleanup

        with patch.object(
            payment_service.payment_repository,
            "update_proof",
            side_effect=RuntimeError("injected SQLite metadata failure"),
        ), patch.object(
            self.attachment_service, "cleanup", wraps=original_cleanup
        ) as cleanup:
            response = self._post_proof(
                self._payment_payload("pm-enrichment-failure"),
                content=b"enrichment-failure",
            )

        payment, _ = self._assert_proof_failure(
            response,
            payment_id="pm-enrichment-failure",
            stage="metadata_enrichment",
            code="proof_storage_failed",
        )
        self.assertIsNone(payment["paymentProof"])
        self.assertGreaterEqual(cleanup.call_count, 1)
        self.assertFalse(any(path.is_file() for path in self.attachment_root.rglob("*")))
        self._assert_single_payment_activity("pm-enrichment-failure")

    def test_failed_replacement_retains_prior_proof_and_does_not_create_activity_or_history(self):
        initial = self._post_proof(
            self._payment_payload("pm-replacement-failure"),
            content=b"prior-proof",
            filename="prior.pdf",
        )
        self.assertEqual(initial.status_code, 201)
        prior_payment = self._payment_from_response(initial)
        prior_proof = prior_payment["paymentProof"]
        prior_path = self.attachment_root / prior_proof["attachmentReference"]
        original_cleanup = self.attachment_service.cleanup

        with patch.object(
            payment_service.payment_repository,
            "update_proof",
            side_effect=RuntimeError("injected replacement enrichment failure"),
        ), patch.object(
            self.attachment_service, "cleanup", wraps=original_cleanup
        ) as cleanup:
            response = self._post_proof(
                self._payment_payload("pm-replacement-failure"),
                content=b"replacement-proof",
                filename="replacement.pdf",
            )

        payment, _ = self._assert_proof_failure(
            response,
            payment_id="pm-replacement-failure",
            stage="metadata_enrichment",
            code="proof_storage_failed",
            prior_proof=prior_proof,
        )
        self.assertEqual(payment["paymentProof"], prior_proof)
        self.assertTrue(prior_path.is_file())
        self.assertGreaterEqual(cleanup.call_count, 1)
        payment_rows = self._payment_rows()
        self.assertEqual(len(payment_rows), 1)
        self.assertEqual(payment_rows[0]["paymentProof"], prior_proof)
        self._assert_single_payment_activity("pm-replacement-failure")
        self.assertEqual(
            [path for path in (self.attachment_root / "pm-replacement-failure").iterdir() if path.is_file()],
            [prior_path],
        )

    def test_successful_replacement_enriches_before_cleanup_and_keeps_one_current_proof(self):
        initial = self._post_proof(
            self._payment_payload("pm-replacement-success"),
            content=b"prior-proof",
            filename="prior.pdf",
        )
        prior_payment = self._payment_from_response(initial)
        prior_proof = prior_payment["paymentProof"]
        prior_path = self.attachment_root / prior_proof["attachmentReference"]
        observed_prior_during_enrichment = []
        original_update = payment_service.payment_repository.update_proof

        def observe_enrichment(payment_id, metadata):
            observed_prior_during_enrichment.append(prior_path.is_file())
            return original_update(payment_id, metadata)

        response = None
        with patch.object(
            payment_service.payment_repository,
            "update_proof",
            side_effect=observe_enrichment,
        ):
            response = self._post_proof(
                self._payment_payload("pm-replacement-success"),
                content=b"replacement-proof",
                filename="replacement.pdf",
            )

        self.assertEqual(response.status_code, 201)
        replacement = self._payment_from_response(response)
        new_proof = replacement["paymentProof"]
        self.assertEqual(replacement["id"], "pm-replacement-success")
        self.assertEqual(replacement["invoiceId"], "invoice-integration")
        self.assertNotEqual(new_proof["attachmentReference"], prior_proof["attachmentReference"])
        self.assertEqual(observed_prior_during_enrichment, [True])
        self.assertFalse(prior_path.exists())
        new_path = self.attachment_root / new_proof["attachmentReference"]
        self.assertTrue(new_path.is_file())
        self.assertEqual(len(self._payment_rows()), 1)
        self.assertEqual(self._payment_rows()[0]["paymentProof"], new_proof)
        fetched = self.client.get("/api/payments/pm-replacement-success", headers=self.auth_headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["paymentProof"], new_proof)
        self._assert_single_payment_activity("pm-replacement-success")

    def test_cleanup_failure_keeps_new_proof_and_logs_only_safe_diagnostic(self):
        initial = self._post_proof(
            self._payment_payload("pm-cleanup-failure"),
            content=b"prior-proof",
            filename="prior.pdf",
        )
        prior_payment = self._payment_from_response(initial)
        prior_reference = prior_payment["paymentProof"]["attachmentReference"]
        prior_path = self.attachment_root / prior_reference

        with self.assertLogs(payment_service.logger, level="WARNING") as logs:
            with patch.object(
                self.attachment_service,
                "cleanup_reference",
                return_value=CleanupResult(False, "unlink_failed"),
            ) as cleanup:
                response = self._post_proof(
                    self._payment_payload("pm-cleanup-failure"),
                    content=b"replacement-proof",
                    filename="replacement.pdf",
                )

        self.assertEqual(response.status_code, 201)
        replacement = self._payment_from_response(response)
        new_proof = replacement["paymentProof"]
        self.assertNotEqual(new_proof["attachmentReference"], prior_reference)
        self.assertTrue(prior_path.is_file())
        self.assertTrue(
            (self.attachment_root / new_proof["attachmentReference"]).is_file()
        )
        cleanup.assert_called_once_with(prior_reference, payment_id="pm-cleanup-failure")
        self.assertTrue(any("unlink_failed" in message for message in logs.output))
        self.assertTrue(all(str(self.attachment_root) not in message for message in logs.output))
        self.assertTrue(all("SFT_Billing.xlsx" not in message for message in logs.output))
        self.assertEqual(len(self._payment_rows()), 1)
        self.assertEqual(self._payment_rows()[0]["paymentProof"], new_proof)
        self._assert_single_payment_activity("pm-cleanup-failure")


if __name__ == "__main__":
    unittest.main()
