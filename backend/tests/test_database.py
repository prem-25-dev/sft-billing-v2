import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.database.session import (
    create_database_engine,
    initialize_business_profile_database,
    initialize_client_database,
    initialize_database,
    initialize_invoice_database,
    initialize_products_database,
    shutdown_database,
    validate_production_database,
)


class ClientDatabaseMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "nested" / "clients.db"
        self.engine = create_database_engine(f"sqlite:///{self.database_path.as_posix()}")

    def tearDown(self):
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    def test_client_migration_creates_current_schema_and_is_idempotent(self):
        initialize_client_database(self.engine)
        initialize_client_database(self.engine)

        self.assertTrue(self.database_path.exists())
        inspector = inspect(self.engine)
        self.assertEqual(
            set(inspector.get_table_names()),
            {"alembic_version", "clients"},
        )
        self.assertEqual(
            [column["name"] for column in inspector.get_columns("clients")],
            [
                "id", "name", "contactName", "email", "phone", "billingAddress",
                "gstin", "pan", "notes",
            ],
        )
        self.assertTrue(
            all(
                column["nullable"]
                for column in inspector.get_columns("clients")
                if column["name"] in {"email", "phone", "pan"}
            )
        )
        self.assertFalse(
            any(
                column["nullable"]
                for column in inspector.get_columns("clients")
                if column["name"] in {"name", "billingAddress", "gstin"}
            )
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar(),
                "0007_nullable_client_contact_fields",
            )

    def test_nullable_client_migration_preserves_rows_and_foreign_keys(self):
        from app.database.session import (
            initialize_business_profile_database,
            initialize_invoice_database,
        )

        initialize_business_profile_database(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO clients "
                    "(id, name, contactName, email, phone, billingAddress, gstin, pan, notes) "
                    "VALUES ('client-1', 'Client', NULL, 'client@example.com', "
                    "'123', 'Address', 'GSTIN', 'PAN', NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO invoices "
                    "(id, number, clientId, issueDate, dueDate, cgstRate, sgstRate, "
                    "discount, roundOff, isDraft) "
                    "VALUES ('invoice-1', '001/2026-27', 'client-1', "
                    "'2026-04-01', '2026-04-30', 0, 0, 0, 0, 1)"
                )
            )

        initialize_client_database(self.engine)
        initialize_invoice_database(self.engine)

        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT email FROM clients WHERE id = 'client-1'")
                ).scalar(),
                "client@example.com",
            )
            self.assertEqual(
                connection.execute(
                    text("SELECT clientId FROM invoices WHERE id = 'invoice-1'")
                ).scalar(),
                "client-1",
            )
            self.assertEqual(
                connection.execute(text("PRAGMA foreign_key_check")).all(),
                [],
            )

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO clients "
                    "(id, name, email, phone, billingAddress, gstin, pan) "
                    "VALUES ('client-2', 'Blank contacts', NULL, NULL, "
                    "'Address', 'GSTIN', NULL)"
                )
            )

    def test_full_migration_merges_client_and_domain_revisions(self):
        initialize_database(self.engine)
        initialize_products_database(self.engine)

        inspector = inspect(self.engine)
        self.assertIn("business_profile", inspector.get_table_names())
        self.assertIn("products", inspector.get_table_names())
        self.assertIn("inventory_movements", inspector.get_table_names())
        product_columns = {
            column["name"]: column for column in inspector.get_columns("products")
        }
        self.assertEqual(
            set(product_columns),
            {
                "id",
                "code",
                "name",
                "type",
                "hsnCode",
                "unit",
                "defaultUnitPrice",
                "defaultGstRate",
                "weightMilli",
                "weightUnit",
                "purchaseCost",
                "lowStockThresholdMilli",
                "stockOnHandMilli",
                "isActive",
                "createdAt",
                "updatedAt",
            },
        )
        self.assertFalse(product_columns["defaultUnitPrice"]["nullable"])
        self.assertIn(
            frozenset({"code"}),
            {
                frozenset(constraint["column_names"])
                for constraint in inspector.get_unique_constraints("products")
            },
        )
        self.assertEqual(
            {
                constraint["name"]
                for constraint in inspector.get_check_constraints("products")
            },
            {
                "ck_products_type",
                "ck_products_defaultUnitPrice",
                "ck_products_defaultGstRate",
                "ck_products_weightMilli",
                "ck_products_weight_pair",
                "ck_products_weightUnit",
                "ck_products_purchaseCost",
                "ck_products_lowStockThresholdMilli",
                "ck_products_stockOnHandMilli",
                "ck_products_service_no_stock_threshold",
                "ck_products_service_no_stock",
            },
        )
        movement_columns = {
            column["name"] for column in inspector.get_columns("inventory_movements")
        }
        self.assertEqual(
            movement_columns,
            {
                "id",
                "productId",
                "type",
                "quantityChangeMilli",
                "resultingBalanceMilli",
                "occurredAt",
                "idempotencyKey",
                "invoiceId",
                "reference",
                "reason",
                "notes",
            },
        )
        self.assertEqual(
            len(inspector.get_foreign_keys("inventory_movements")),
            2,
        )
        with self.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar(),
                "0013_user_mobile",
            )
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)

    def test_pending_migration_creates_a_verified_backup_and_preserves_rows(self):
        initialize_business_profile_database(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO clients "
                    "(id, name, email, phone, billingAddress, gstin, pan) "
                    "VALUES ('preserved-client', 'Preserved client', "
                    "'preserved@example.com', '555', 'Address', 'GSTIN', 'PAN')"
                )
            )

        initialize_database(self.engine)

        backup_paths = list(
            (self.database_path.parent / "backups").glob(
                "clients.before-migration-*.db"
            )
        )
        self.assertEqual(len(backup_paths), 1)
        with closing(sqlite3.connect(str(backup_paths[0]))) as backup:
            self.assertEqual(
                backup.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                backup.execute(
                    "SELECT name FROM clients WHERE id = 'preserved-client'"
                ).fetchone()[0],
                "Preserved client",
            )
            self.assertEqual(
                backup.execute("SELECT version_num FROM alembic_version").fetchone()[0],
                "0006_business_profile",
            )

    def test_client_then_invoice_initialization_remains_domain_scoped(self):
        from app.database.session import initialize_invoice_database

        initialize_client_database(self.engine)
        initialize_invoice_database(self.engine)

        self.assertEqual(
            set(inspect(self.engine).get_table_names()),
            {"alembic_version", "clients", "invoices", "invoice_items"},
        )
        with self.engine.connect() as connection:
            current_revisions = set(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
        self.assertEqual(
            current_revisions,
            {"0007_nullable_client_contact_fields", "0002_invoice_core"},
        )

    def test_foreign_key_enforcement_is_enabled_for_sqlite_connections(self):
        initialize_client_database(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)

    def test_client_write_transaction_commits_and_rolls_back(self):
        initialize_client_database(self.engine)
        session_factory = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

        with session_factory.begin() as session:
            session.execute(
                text(
                    "INSERT INTO clients "
                    "(id, name, email, phone, billingAddress, gstin, pan) "
                    "VALUES ('client-committed', 'Committed', 'a@example.com', "
                    "'123', 'Address', 'GSTIN', 'PAN')"
                )
            )

        with self.assertRaises(RuntimeError):
            with session_factory.begin() as session:
                session.execute(
                    text(
                        "INSERT INTO clients "
                        "(id, name, email, phone, billingAddress, gstin, pan) "
                        "VALUES ('client-rolled-back', 'Rolled back', 'b@example.com', "
                        "'123', 'Address', 'GSTIN', 'PAN')"
                    )
                )
                raise RuntimeError("force rollback")

        with self.engine.connect() as connection:
            client_ids = set(
                connection.execute(text("SELECT id FROM clients")).scalars()
            )
        self.assertEqual(client_ids, {"client-committed"})

    def test_unversioned_partial_schema_is_recovered_without_losing_rows(self):
        initialize_invoice_database(self.engine)
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO clients "
                    "(id, name, contactName, email, phone, billingAddress, gstin, pan, notes) "
                    "VALUES ('preserved-client', 'Existing Client', NULL, "
                    "'existing@example.com', '555', 'Address', "
                    "'33AAACM5230H1Z1', 'ABCDE1234F', NULL)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO invoices "
                    "(id, number, clientId, issueDate, dueDate, cgstRate, sgstRate, "
                    "discount, roundOff, isDraft) VALUES "
                    "('preserved-invoice', '001/2026-27', 'preserved-client', "
                    "'2026-04-01', '2026-04-30', 0.09, 0.09, 0, 0, 1)"
                )
            )
            connection.execute(text("DELETE FROM alembic_version"))
            connection.execute(text("DROP TABLE invoice_items"))

        initialize_client_database(self.engine)
        initialize_invoice_database(self.engine)

        with self.engine.connect() as connection:
            client = connection.execute(
                text(
                    "SELECT id, name, email, phone, pan FROM clients "
                    "WHERE id = 'preserved-client'"
                )
            ).one()
            invoice = connection.execute(
                text(
                    "SELECT id, number, clientId FROM invoices "
                    "WHERE id = 'preserved-invoice'"
                )
            ).one()
            revisions = set(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )

        self.assertEqual(
            tuple(client),
            (
                "preserved-client",
                "Existing Client",
                "existing@example.com",
                "555",
                "ABCDE1234F",
            ),
        )
        self.assertEqual(
            tuple(invoice),
            ("preserved-invoice", "001/2026-27", "preserved-client"),
        )
        self.assertEqual(revisions, {"0002_invoice_core", "0007_nullable_client_contact_fields"})
        self.assertIn("invoice_items", inspect(self.engine).get_table_names())
        self.assertTrue(
            all(
                column["nullable"]
                for column in inspect(self.engine).get_columns("clients")
                if column["name"] in {"email", "phone", "pan"}
            )
        )

    def test_concurrent_process_initialization_is_serialized_and_repeatable(self):
        database_path = Path(self.temp_dir.name) / "concurrent.db"
        database_url = f"sqlite:///{database_path.as_posix()}"
        backend_directory = Path(__file__).resolve().parents[1]
        initializer_code = """
import sys
from app.database.session import (
    create_database_engine,
    initialize_activity_database,
    initialize_business_profile_database,
    initialize_client_database,
    initialize_invoice_database,
    initialize_payment_database,
)
engine = create_database_engine(sys.argv[1])
initialize_client_database(engine)
initialize_invoice_database(engine)
initialize_payment_database(engine)
initialize_activity_database(engine)
initialize_business_profile_database(engine)
"""
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", initializer_code, database_url],
                cwd=backend_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        results = [process.communicate(timeout=60) for process in processes]
        for process, (stdout, stderr) in zip(processes, results):
            self.assertEqual(
                process.returncode,
                0,
                f"Initializer process failed.\nstdout:\n{stdout}\nstderr:\n{stderr}",
            )

        concurrent_engine = create_database_engine(database_url)
        try:
            initialize_database(concurrent_engine)
            self.assertEqual(
                set(inspect(concurrent_engine).get_table_names()),
                {
                    "alembic_version",
                    "clients",
                    "invoices",
                    "invoice_items",
                    "invoice_number_reservations",
                    "payments",
                    "activities",
                    "business_profile",
                    "products",
                    "inventory_movements",
                    "notifications",
                    "users",
                    "sessions",
                    "password_reset_tokens",
                    "recovery_attempts",
                },
            )
            with concurrent_engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar(),
                    "0013_user_mobile",
                )
                self.assertEqual(
                    connection.exec_driver_sql("PRAGMA foreign_key_check").all(),
                    [],
                )
        finally:
            shutdown_database(concurrent_engine)


class ProductionDatabaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.local_appdata = Path(self.temp_dir.name)
        self.database_path = self.local_appdata / "SFT Billing" / "sft_billing.db"
        self.database_path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _validate_frozen_database(self):
        with (
            patch.object(sys, "frozen", True, create=True),
            patch.dict(
                os.environ,
                {
                    "LOCALAPPDATA": str(self.local_appdata),
                    "SFT_BILLING_DATABASE_URL": (
                        f"sqlite:///{self.database_path.as_posix()}"
                    ),
                },
                clear=True,
            ),
        ):
            validate_production_database()

    def test_missing_production_database_is_allowed_on_a_fresh_install(self):
        # First run on a new PC: setup creates the database, validation must not block it.
        self._validate_frozen_database()
        self.assertFalse(self.database_path.exists())

    def test_empty_database_file_is_allowed_and_will_be_initialised(self):
        database = sqlite3.connect(str(self.database_path))
        database.close()
        self._validate_frozen_database()

    def test_unrelated_database_without_client_schema_is_rejected(self):
        database = sqlite3.connect(str(self.database_path))
        try:
            database.execute("CREATE TABLE other (id TEXT PRIMARY KEY)")
        finally:
            database.close()

        with self.assertRaisesRegex(RuntimeError, "no client schema"):
            self._validate_frozen_database()

    def test_existing_database_with_client_schema_is_accepted(self):
        database = sqlite3.connect(str(self.database_path))
        try:
            database.execute(
                "CREATE TABLE clients (id TEXT PRIMARY KEY, name TEXT NOT NULL)"
            )
        finally:
            database.close()

        self._validate_frozen_database()
