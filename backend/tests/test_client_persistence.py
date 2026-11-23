import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database.models import Invoice
from app.database.session import create_database_engine, shutdown_database
from app.excel.constants import SHEET_CLIENTS
from app.repositories.client_repository import ClientRepository
from app.routes.clients import router as clients_router
from app.services import invoice_service


class ClientRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "clients.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.repository = ClientRepository(self.session_factory, self.engine)

    def tearDown(self):
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    @staticmethod
    def _client(client_id: str = "client-1", name: str = "Client") -> dict:
        return {
            "id": client_id,
            "name": name,
            "contactName": "Contact",
            "email": "billing@example.com",
            "phone": "9876543210",
            "billingAddress": "Billing address",
            "gstin": "29AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "notes": None,
        }

    def test_create_retrieve_list_and_update(self):
        created = self.repository.create(self._client())
        self.assertEqual(created, self._client())
        self.assertEqual(self.repository.get_by_id("client-1"), created)
        self.assertEqual(self.repository.list_all(), [created])
        self.assertTrue(self.repository.exists_by_id("client-1"))
        self.assertFalse(self.repository.exists_by_id("missing"))

        updated = self.repository.update(
            "client-1",
            {"name": "Updated", "email": "new@example.com", "notes": "Preferred"},
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated["name"], "Updated")
        self.assertEqual(updated["email"], "new@example.com")
        self.assertEqual(updated["notes"], "Preferred")
        self.assertEqual(updated["phone"], "9876543210")

    def test_missing_record_operations(self):
        self.assertIsNone(self.repository.get_by_id("missing"))
        self.assertIsNone(self.repository.update("missing", {"name": "Changed"}))
        self.assertFalse(self.repository.delete("missing"))

    def test_read_only_existence_check_does_not_initialize_database(self):
        database_path = Path(self.temp_dir.name) / "not-created.db"
        engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        repository = ClientRepository(
            sessionmaker(bind=engine),
            engine,
        )
        try:
            self.assertFalse(repository.exists_by_id_if_initialized("missing"))
            self.assertFalse(database_path.exists())
        finally:
            shutdown_database(engine)

    def test_duplicate_id_is_rejected_and_original_row_is_preserved(self):
        self.repository.create(self._client())

        with self.assertRaises(IntegrityError):
            self.repository.create(self._client(name="Duplicate"))

        self.assertEqual(self.repository.get_by_id("client-1")["name"], "Client")
        self.assertEqual(len(self.repository.list_all()), 1)

    def test_failed_create_rolls_back(self):
        invalid_record = self._client()
        invalid_record["name"] = None

        with self.assertRaises(IntegrityError):
            self.repository.create(invalid_record)

        self.assertEqual(self.repository.list_all(), [])

    def test_delete_removes_only_the_selected_record(self):
        self.repository.create(self._client())
        self.repository.create(self._client("client-2", "Second"))

        self.assertTrue(self.repository.delete("client-1"))
        self.assertIsNone(self.repository.get_by_id("client-1"))
        self.assertEqual([row["id"] for row in self.repository.list_all()], ["client-2"])


class ClientApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        import uuid
        self.unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "api-clients.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.repository = ClientRepository(session_factory, self.engine)
        app = FastAPI()
        app.include_router(clients_router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        self.client = TestClient(app)
        self.repository_patch = patch(
            "app.services.client_service.client_repository", self.repository
        )
        self.repository_patch.start()

        # Set up authentication
        from app.services.auth_service import create_user
        from app.database.session import get_db_session

        # Create a test user
        db_gen = get_db_session()
        db = next(db_gen)
        try:
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

    def tearDown(self):
        self.repository_patch.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def test_existing_client_endpoints_preserve_contract_without_excel_access(self):
        create_payload = {
            "id": "client-explicit-id",
            "name": "  Example Co  ",
            "contactName": "  Pat  ",
            "email": " billing@example.com ",
            "phone": " 9876543210 ",
            "billingAddress": " Main Street ",
            "gstin": "29aaaaa0000a1z5",
            "pan": "aaaaa0000a",
            "notes": "  Preferred  ",
        }
        with (
            patch(
                "app.excel.workbook.load_workbook_safely",
                side_effect=AssertionError("Client CRUD must not read Excel"),
            ),
            patch(
                "app.excel.workbook.save_workbook",
                side_effect=AssertionError("Client CRUD must not write Excel"),
            ),
        ):
            created_response = self.client.post("/api/clients", json=create_payload, headers=self.auth_headers)
            self.assertEqual(created_response.status_code, 201)
            expected = {
                "id": "client-explicit-id",
                "name": "Example Co",
                "contactName": "Pat",
                "email": "billing@example.com",
                "phone": "9876543210",
                "billingAddress": "Main Street",
                "gstin": "29AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "notes": "Preferred",
            }
            self.assertEqual(created_response.json(), expected)
            self.assertEqual(self.client.get("/api/clients", headers=self.auth_headers).json(), [expected])
            self.assertEqual(
                self.client.get("/api/clients/client-explicit-id", headers=self.auth_headers).json(), expected
            )

            update_response = self.client.put(
                "/api/clients/client-explicit-id",
                json={"name": "Updated Co", "gstin": "29bbbbb1111b1z5"},
                headers=self.auth_headers,
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(update_response.json()["name"], "Updated Co")
            self.assertEqual(update_response.json()["gstin"], "29BBBBB1111B1Z5")

            invalid_response = self.client.post(
                "/api/clients", json={"name": "", "email": "not-an-email"}, headers=self.auth_headers
            )
            self.assertEqual(invalid_response.status_code, 422)
            self.assertEqual(invalid_response.json()["detail"]["message"], "Validation failed")

            self.assertEqual(
                self.client.get("/api/clients/not-present", headers=self.auth_headers).status_code, 404
            )
            self.assertEqual(
                self.client.put(
                    "/api/clients/not-present", json={"name": "Missing"}, headers=self.auth_headers
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.delete("/api/clients/not-present", headers=self.auth_headers).status_code, 404
            )
            self.assertEqual(
                self.client.delete("/api/clients/client-explicit-id", headers=self.auth_headers).json(),
                {"deleted": True, "id": "client-explicit-id"},
            )

    def test_client_with_invoice_is_preserved_and_delete_returns_conflict(self):
        created = self.client.post(
            "/api/clients",
            json={
                "id": "client-with-invoice",
                "name": "Protected Client",
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, 201)

        Invoice.__table__.create(self.engine)
        with self.repository._session_factory.begin() as session:
            session.add(
                Invoice(
                    id="protected-invoice",
                    number="001/2026-27",
                    client_id="client-with-invoice",
                    issue_date="2026-01-01",
                    due_date="2026-01-15",
                    cgst_rate=0.09,
                    sgst_rate=0.09,
                    discount=0,
                    round_off=0,
                    is_draft=True,
                )
            )

        response = self.client.delete("/api/clients/client-with-invoice", headers=self.auth_headers)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"],
            "This client has linked invoices or payments and cannot be deleted.",
        )
        self.assertEqual(
            self.client.get("/api/clients/client-with-invoice", headers=self.auth_headers).status_code,
            200,
        )
        with self.repository._session_factory() as session:
            self.assertIsNotNone(session.get(Invoice, "protected-invoice"))

    def test_generated_client_id_keeps_existing_prefix(self):
        with patch("app.services.client_service.new_id", return_value="cl_generated"):
            response = self.client.post(
                "/api/clients",
                json={
                    "name": "Client",
                    "email": "client@example.com",
                    "phone": "9876543210",
                    "billingAddress": "Address",
                    "gstin": "29AAAAA0000A1Z5",
                    "pan": "AAAAA0000A",
                },
                headers=self.auth_headers,
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["id"], "cl_generated")

    def test_create_client_with_blank_optional_contacts_stores_null(self):
        response = self.client.post(
            "/api/clients",
            json={
                "id": "client-blank-contacts",
                "name": "Historical Client",
                "email": " ",
                "phone": "9876543210",
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": None,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["email"])
        # Phone with all digits is required, so it should be stored
        self.assertEqual(response.json()["phone"], "9876543210")
        self.assertIsNone(response.json()["pan"])
        self.assertEqual(
            self.repository.get_by_id("client-blank-contacts"),
            response.json(),
        )

    def test_update_client_can_clear_optional_contacts(self):
        create_response = self.client.post(
            "/api/clients",
            json={
                "id": "client-to-clear",
                "name": "Client",
                "email": "client@example.com",
                "phone": "9876543210",
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(create_response.status_code, 201)

        response = self.client.put(
            "/api/clients/client-to-clear",
            json={"email": " ", "phone": None, "pan": ""},
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["email"])
        # Phone is required and cannot be cleared to None when provided
        self.assertEqual(response.json()["phone"], "9876543210")
        self.assertIsNone(response.json()["pan"])

    def test_invalid_supplied_email_is_rejected(self):
        response = self.client.post(
            "/api/clients",
            json={
                "name": "Client",
                "email": "not-an-email",
                "phone": None,
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": None,
            },
            headers=self.auth_headers,
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("email", response.json()["detail"]["errors"])

    def test_invoice_client_lookup_accepts_sqlite_clients(self):
        self.repository.create(
            {
                "id": "sqlite-client",
                "name": "SQLite Client",
                "contactName": None,
                "email": "sqlite@example.com",
                "phone": "9876543210",
                "billingAddress": "Address",
                "gstin": "29AAAAA0000A1Z5",
                "pan": "AAAAA0000A",
                "notes": None,
            }
        )
        with patch.object(invoice_service, "client_repository", self.repository):
            self.assertTrue(invoice_service._client_exists("sqlite-client"))

    def test_invoice_client_lookup_does_not_import_excel_only_clients(self):
        with patch(
            "app.services.invoice_service.client_repository.exists_by_id",
            return_value=False,
        ) as exists:
            self.assertFalse(invoice_service._client_exists("excel-client"))
        exists.assert_called_once_with("excel-client")


if __name__ == "__main__":
    unittest.main()
