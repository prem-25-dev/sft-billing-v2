import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import payment_proof_service
from app.services.payment_proof_service import (
    AttachmentEnrichmentError,
    AttachmentReadbackError,
    AttachmentSecurityError,
    AttachmentServiceError,
    AttachmentUpload,
    AttachmentWriteError,
    PaymentProofAttachmentService,
)


class PaymentProofAttachmentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "managed-proof-root"
        self.service = PaymentProofAttachmentService(self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    @staticmethod
    def _upload(content=b"proof-bytes", file_name="receipt.pdf"):
        return AttachmentUpload(
            file_name=file_name,
            mime_type="application/pdf",
            content=io.BytesIO(content),
            size_bytes=len(content),
        )

    def test_save_generates_payment_scoped_reference_and_uses_filename_as_metadata_only(self):
        metadata = self.service.save(
            "pm_safe_1",
            self._upload(file_name="C:\\browser\\..\\receipt.pdf"),
        )

        self.assertTrue(metadata.attachment_reference.startswith("pm_safe_1/"))
        self.assertEqual(metadata.file_name, "receipt.pdf")
        self.assertEqual(metadata.size_bytes, len(b"proof-bytes"))
        self.assertNotIn(str(self.root), metadata.attachment_reference)
        self.assertNotIn("receipt.pdf", metadata.attachment_reference)
        self.assertEqual(self.service.read(metadata.attachment_reference, payment_id="pm_safe_1"), b"proof-bytes")
        self.assertTrue((self.root / metadata.attachment_reference).is_file())

    def test_reference_validation_rejects_traversal_absolute_and_cross_payment_values(self):
        metadata = self.service.save("pm_safe_1", self._upload())
        token = metadata.attachment_reference.split("/", 1)[1]
        invalid_references = (
            "../pm_safe_1/" + token,
            "/pm_safe_1/" + token,
            "pm_safe_1/../" + token,
            "pm_safe_1/.//" + token,
            "pm_safe_1\\" + token,
            "pm_other/" + token,
            "pm_safe_1/not-a-generated-token",
        )

        for reference in invalid_references:
            with self.subTest(reference=reference):
                with self.assertRaises(AttachmentSecurityError):
                    self.service.validate_reference(reference, payment_id="pm_safe_1")

    def test_unsafe_payment_identity_is_rejected_before_any_file_is_written(self):
        with self.assertRaises(AttachmentSecurityError):
            self.service.stage_upload("../pm_escape", self._upload())
        self.assertFalse(self.root.exists() and any(self.root.iterdir()))

    def test_symlinked_managed_file_is_rejected_for_read(self):
        payment_dir = self.root / "pm_symlink"
        payment_dir.mkdir(parents=True)
        outside_file = Path(self.temp_dir.name) / "outside.bin"
        outside_file.write_bytes(b"outside")
        linked_file = payment_dir / ("a" * 32)
        try:
            os.symlink(outside_file, linked_file)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable in this environment")

        with self.assertRaises(AttachmentSecurityError):
            self.service.read("pm_symlink/" + ("a" * 32), payment_id="pm_symlink")
        self.assertEqual(outside_file.read_bytes(), b"outside")

    def test_readback_mismatch_is_reported_and_cleanup_removes_new_file(self):
        staged = self.service.stage_upload("pm_readback", self._upload())
        staged.promote()
        stored_path = self.root / staged.reference
        stored_path.write_bytes(b"tampered")

        with self.assertRaises(AttachmentReadbackError) as raised:
            staged.validate_readback()
        self.assertEqual(raised.exception.category, "content_mismatch")
        self.assertTrue(staged.cleanup().success)
        self.assertFalse(stored_path.exists())

    def test_write_failure_has_safe_category_and_does_not_leak_path(self):
        with patch(
            "app.services.payment_proof_service.tempfile.mkstemp",
            side_effect=OSError("do not expose this path"),
        ):
            with self.assertRaises(AttachmentWriteError) as raised:
                self.service.save("pm_write", self._upload())

        self.assertEqual(raised.exception.stage, "write")
        self.assertEqual(raised.exception.category, "write_failed")
        self.assertNotIn(str(self.root), str(raised.exception))

    def test_failed_replacement_keeps_prior_file_and_cleans_new_file(self):
        prior = self.service.save("pm_replace", self._upload(b"prior"))
        prior_path = self.root / prior.attachment_reference

        def fail_enrichment(_metadata):
            self.assertEqual(self.service.read(prior.attachment_reference, payment_id="pm_replace"), b"prior")
            raise RuntimeError("workbook enrichment failure")

        with self.assertRaises(AttachmentEnrichmentError) as raised:
            self.service.replace(
                "pm_replace",
                self._upload(b"new"),
                prior_reference=prior.attachment_reference,
                metadata_enricher=fail_enrichment,
            )

        self.assertEqual(raised.exception.stage, "metadata_enrichment")
        self.assertEqual(raised.exception.category, "metadata_enrichment_failed")
        self.assertTrue(prior_path.is_file())
        self.assertEqual(self.service.read(prior.attachment_reference, payment_id="pm_replace"), b"prior")
        self.assertEqual(
            [path for path in (self.root / "pm_replace").iterdir() if not path.name.startswith(".")],
            [prior_path],
        )

    def test_successful_replacement_enriches_before_cleaning_prior_file(self):
        prior = self.service.save("pm_replace_order", self._upload(b"prior"))
        prior_path = self.root / prior.attachment_reference
        observed = []

        def enrich(metadata):
            observed.append(prior_path.is_file())
            self.assertEqual(
                self.service.read(prior.attachment_reference, payment_id="pm_replace_order"),
                b"prior",
            )
            self.assertTrue(metadata["attachmentReference"].startswith("pm_replace_order/"))

        result = self.service.replace(
            "pm_replace_order",
            self._upload(b"new"),
            prior_reference=prior.attachment_reference,
            metadata_enricher=enrich,
        )

        self.assertEqual(observed, [True])
        self.assertTrue(result.prior_cleanup.success)
        self.assertFalse(prior_path.exists())
        self.assertEqual(
            self.service.read(result.metadata.attachment_reference, payment_id="pm_replace_order"),
            b"new",
        )

    def test_cleanup_failure_returns_only_safe_diagnostic_category(self):
        metadata = self.service.save("pm_cleanup", self._upload())
        stored_path = self.root / metadata.attachment_reference

        with patch.object(Path, "unlink", side_effect=PermissionError("server path must stay private")):
            result = self.service.cleanup_reference(metadata.attachment_reference, payment_id="pm_cleanup")

        self.assertFalse(result.success)
        self.assertEqual(result.diagnostic_category, "unlink_failed")
        self.assertNotIn(str(stored_path), repr(result))
        self.assertTrue(stored_path.exists())

    def test_declared_size_mismatch_is_rejected_without_final_file(self):
        with self.assertRaises(AttachmentServiceError) as raised:
            self.service.stage_upload(
                "pm_size",
                AttachmentUpload(
                    file_name="receipt.pdf",
                    mime_type="application/pdf",
                    content=b"actual",
                    size_bytes=999,
                ),
            )

        self.assertEqual(raised.exception.category, "size_mismatch")
        self.assertFalse((self.root / "pm_size").exists())
    def test_configured_root_precedes_backend_data_fallback(self):
        with patch.dict(
            os.environ,
            {
                "SFT_BILLING_ATTACHMENT_ROOT": "configured-proof-root",
                "SFT_BILLING_PAYMENT_PROOF_ROOT": "",
                "PAYMENT_PROOF_ATTACHMENT_ROOT": "",
                "PAYMENT_PROOF_ROOT": "",
            },
            clear=False,
        ):
            resolved = payment_proof_service.resolve_attachment_root()

        self.assertEqual(resolved, payment_proof_service.BASE_DIR / "configured-proof-root")

        with patch.dict(
            os.environ,
            {
                "SFT_BILLING_ATTACHMENT_ROOT": "",
                "SFT_BILLING_PAYMENT_PROOF_ROOT": "",
                "PAYMENT_PROOF_ATTACHMENT_ROOT": "",
                "PAYMENT_PROOF_ROOT": "",
            },
            clear=False,
        ):
            fallback = payment_proof_service.resolve_attachment_root()

        self.assertEqual(
            fallback,
            payment_proof_service.DATA_DIR / payment_proof_service.DEFAULT_ATTACHMENT_DIRECTORY,
        )


if __name__ == "__main__":
    unittest.main()
