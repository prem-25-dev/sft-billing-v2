import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.orm import sessionmaker

from app.database.models import BusinessProfileRecord
from app.database.session import (
    create_database_engine,
    get_db_session,
    initialize_activity_database,
    initialize_business_profile_database,
    shutdown_database,
)
from app.repositories.business_profile_repository import BusinessProfileRepository
from app.routes.business_profile import router
from app.services import business_service
from app.services.auth_service import create_user


class BusinessProfilePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "business-profile.db"
        self.engine = create_database_engine(
            f"sqlite:///{database_path.as_posix()}"
        )
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.repository = BusinessProfileRepository(
            self.session_factory,
            self.engine,
        )
        self.repository_patch = patch(
            "app.services.business_service.business_profile_repository",
            self.repository,
        )
        self.repository_patch.start()

    def tearDown(self):
        self.repository_patch.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def test_get_without_saved_profile_returns_defaults_without_creating_a_row(self):
        with (
            patch(
                "app.excel.workbook.load_workbook_safely",
                side_effect=AssertionError("Business Profile must not read Excel"),
            ),
            patch(
                "app.excel.workbook.save_workbook",
                side_effect=AssertionError("Business Profile must not write Excel"),
            ),
        ):
            profile = business_service.get_business_profile()

        self.assertEqual(profile["name"], "Your Company")
        self.assertEqual(profile["email"], "billing@example.com")
        self.assertEqual(profile["address"], "")
        self.assertEqual(
            profile["defaultGst"],
            {"cgstRate": 0.09, "sgstRate": 0.09},
        )
        self.assertIsNone(self.repository.get_current())

    def test_profile_fields_and_asset_references_round_trip(self):
        expected = {
            "name": "Example Company",
            "logoUrl": "assets/company-logo.png",
            "address": "Main Street",
            "email": "accounts@example.com",
            "phone": "12345",
            "gstin": "29AAAAA0000A1Z5",
            "pan": "AAAAA0000A",
            "bank": {
                "accountHolder": "Example Company",
                "bankName": "Example Bank",
                "branch": "Main",
                "accountNumber": "123456",
                "ifsc": "EXAM0000123",
            },
            "declaration": "Declaration text",
            "authorizedSignatory": "Authorized Signatory",
            "defaultGst": {"cgstRate": 0.075, "sgstRate": 0.075},
        }

        with (
            patch(
                "app.excel.workbook.load_workbook_safely",
                side_effect=AssertionError("Business Profile must not read Excel"),
            ),
            patch(
                "app.excel.workbook.save_workbook",
                side_effect=AssertionError("Business Profile must not write Excel"),
            ),
        ):
            persisted = business_service.update_business_profile(expected)
            retrieved = business_service.get_business_profile()

        self.assertEqual(persisted, expected)
        self.assertEqual(retrieved, expected)
        self.assertEqual(self.repository.get_current()["logoUrl"], expected["logoUrl"])
        self.assertEqual(self.repository.get_current()["authorizedSignatory"], expected["authorizedSignatory"])

    def test_partial_updates_keep_existing_values_and_ignore_null_values(self):
        first = business_service.update_business_profile(
            {
                "name": "Before",
                "email": "accounts@example.com",
                "logoUrl": "assets/logo.png",
                "bank": {
                    "accountHolder": "Account",
                    "bankName": "Bank",
                    "branch": "Branch",
                    "accountNumber": "456",
                    "ifsc": "BANK0000001",
                },
                "defaultGst": {"cgstRate": 0.09, "sgstRate": 0.09},
            }
        )

        updated = business_service.update_business_profile(
            {"name": "After", "logoUrl": None, "phone": None}
        )

        self.assertEqual(first["name"], "Before")
        self.assertEqual(updated["name"], "After")
        self.assertEqual(updated["logoUrl"], "assets/logo.png")
        self.assertEqual(updated["phone"], first["phone"])
        self.assertEqual(updated["bank"], first["bank"])
        self.assertEqual(updated["defaultGst"], first["defaultGst"])
        with self.session_factory() as session:
            self.assertEqual(
                len(session.scalars(select(BusinessProfileRecord)).all()),
                1,
            )

    def test_blank_stored_strings_remain_blank(self):
        profile = business_service.update_business_profile(
            {"name": "", "address": "", "email": ""}
        )

        self.assertEqual(profile["name"], "")
        self.assertEqual(profile["address"], "")
        self.assertEqual(profile["email"], "")
        self.assertEqual(business_service.get_business_profile(), profile)

    def test_http_contract_uses_sqlite_without_importing_excel_values(self):
        import uuid
        unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        app = FastAPI()
        app.include_router(router)
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

        with (
            patch(
                "app.excel.workbook.load_workbook_safely",
                side_effect=AssertionError("Business Profile must not read Excel"),
            ),
            patch(
                "app.excel.workbook.save_workbook",
                side_effect=AssertionError("Business Profile must not write Excel"),
            ),
        ):
            initial_response = client.get("/api/business-profile", headers=auth_headers)
            self.assertEqual(initial_response.status_code, 200)
            self.assertEqual(initial_response.json()["name"], "Your Company")

            update_response = client.put(
                "/api/business-profile",
                json={
                    "name": "Settings Company",
                    "defaultGst": {"cgstRate": 0.05, "sgstRate": 0.05},
                },
                headers=auth_headers,
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(update_response.json()["name"], "Settings Company")
            self.assertEqual(
                update_response.json()["defaultGst"],
                {"cgstRate": 0.05, "sgstRate": 0.05},
            )
            self.assertEqual(
                client.get("/api/business-profile", headers=auth_headers).json(),
                update_response.json(),
            )

    def test_business_profile_migration_adds_only_its_table(self):
        initialize_activity_database(self.engine)
        tables_before = set(inspect(self.engine).get_table_names())

        initialize_business_profile_database(self.engine)
        tables_after = set(inspect(self.engine).get_table_names())

        self.assertEqual(tables_after - tables_before, {"business_profile"})
        self.assertNotIn("products", tables_after)
        self.assertEqual(
            {column["name"] for column in inspect(self.engine).get_columns("business_profile")},
            {
                "id",
                "name",
                "logoUrl",
                "address",
                "email",
                "phone",
                "gstin",
                "pan",
                "bank_accountHolder",
                "bank_bankName",
                "bank_branch",
                "bank_accountNumber",
                "bank_ifsc",
                "declaration",
                "authorizedSignatory",
                "defaultGst_cgstRate",
                "defaultGst_sgstRate",
            },
        )


if __name__ == "__main__":
    unittest.main()
