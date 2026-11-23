import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.database.models import Client, Invoice, InvoiceItem
from app.database.session import create_database_engine, shutdown_database
from app.repositories.product_repository import ProductRepository
from app.routes.products import router as products_router
from app.services import product_service
from app.utils.errors import ConflictError, ValidationFailedError


class ProductPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "products.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self.repository = ProductRepository(self.session_factory, self.engine)
        self.repository_patch = patch(
            "app.services.product_service.product_repository", self.repository
        )
        self.repository_patch.start()

    def tearDown(self):
        self.repository_patch.stop()
        shutdown_database(self.engine)
        self.temp_dir.cleanup()

    @staticmethod
    def _product(**overrides):
        values = {
            "code": "ITEM-1",
            "name": "Sample item",
            "type": "product",
            "hsnCode": "1234",
            "unit": "pcs",
            "defaultUnitPrice": "12.34",
            "defaultGstRate": "0.18",
        }
        values.update(overrides)
        return values

    def test_create_read_search_filter_update_and_paise_storage(self):
        created = product_service.create_product(
            self._product(
                weight="1.250",
                weightUnit="kg",
                purchaseCost="8.75",
                lowStockThreshold="2.5",
            )
        )
        self.assertEqual(created["defaultUnitPrice"], 12.34)
        self.assertEqual(created["purchaseCost"], 8.75)
        self.assertEqual(created["weight"], 1.25)
        self.assertEqual(created["stockOnHand"], None)
        self.assertEqual(product_service.get_product(created["id"])["code"], "ITEM-1")
        self.assertEqual(
            [row["id"] for row in product_service.list_products(search="item")],
            [created["id"]],
        )
        self.assertEqual(
            len(product_service.list_products(is_active=True, product_type="product")),
            1,
        )
        updated = product_service.update_product(
            created["id"], {"name": "Updated item", "defaultUnitPrice": "15.99"}
        )
        self.assertEqual(updated["name"], "Updated item")
        self.assertEqual(updated["defaultUnitPrice"], 15.99)

        with self.engine.connect() as connection:
            stored = connection.execute(
                text(
                    "SELECT defaultUnitPrice, purchaseCost, weightMilli, "
                    "lowStockThresholdMilli FROM products WHERE id = :id"
                ),
                {"id": created["id"]},
            ).one()
        self.assertEqual(tuple(stored), (1599, 875, 1250, 2500))

    def test_duplicate_codes_conflict_on_create_and_update(self):
        first = product_service.create_product(self._product())
        second = product_service.create_product(
            self._product(code="ITEM-2", name="Second")
        )
        with self.assertRaises(ConflictError):
            product_service.create_product(self._product(name="Duplicate"))
        with self.assertRaises(ConflictError):
            product_service.update_product(second["id"], {"code": first["code"]})

    def test_weight_and_threshold_validation(self):
        with self.assertRaises(ValidationFailedError):
            product_service.create_product(self._product(weight="1"))
        with self.assertRaises(ValidationFailedError):
            product_service.create_product(
                self._product(weight="-1", weightUnit="kg")
            )
        with self.assertRaises(ValidationFailedError):
            product_service.create_product(
                self._product(weight="1.0001", weightUnit="kg")
            )
        with self.assertRaises(ValidationFailedError):
            product_service.create_product(
                self._product(
                    type="service",
                    lowStockThreshold="2",
                )
            )

    def test_service_cannot_receive_inventory_movement(self):
        service = product_service.create_product(
            self._product(code="SVC-1", type="service")
        )
        with self.assertRaises(ConflictError):
            product_service.record_inventory_movement(
                service["id"],
                {
                    "type": "opening",
                    "quantity": 3,
                    "idempotencyKey": "service-opening",
                },
            )
        self.assertIsNone(product_service.get_product(service["id"])["stockOnHand"])

    def test_opening_receipt_issue_adjustment_and_history(self):
        product = product_service.create_product(self._product())
        product_id = product["id"]
        opening = product_service.record_inventory_movement(
            product_id,
            {
                "type": "opening",
                "quantity": "10",
                "idempotencyKey": "opening-1",
            },
        )
        self.assertEqual(opening["resultingBalance"], 10)
        receipt = product_service.record_inventory_movement(
            product_id,
            {
                "type": "receipt",
                "quantity": "2.250",
                "idempotencyKey": "receipt-1",
            },
        )
        self.assertEqual(receipt["resultingBalance"], 12.25)
        issue = product_service.record_inventory_movement(
            product_id,
            {
                "type": "issue",
                "quantity": "1.125",
                "idempotencyKey": "issue-1",
            },
        )
        self.assertEqual(issue["quantityChange"], -1.125)
        adjustment = product_service.record_inventory_movement(
            product_id,
            {
                "type": "adjustment",
                "quantity": "-0.125",
                "reason": "Count correction",
                "idempotencyKey": "adjustment-1",
            },
        )
        self.assertEqual(adjustment["resultingBalance"], 11)
        self.assertEqual(
            product_service.get_product(product_id)["stockOnHand"], 11
        )
        history = product_service.list_inventory_movements(product_id)
        self.assertEqual([row["type"] for row in history], [
            "adjustment",
            "issue",
            "receipt",
            "opening",
        ])

    def test_idempotency_and_failed_movement_leave_stock_and_history_unchanged(self):
        product = product_service.create_product(self._product())
        product_id = product["id"]
        payload = {
            "type": "opening",
            "quantity": "4",
            "idempotencyKey": "same-key",
        }
        first = product_service.record_inventory_movement(product_id, payload)
        self.assertEqual(product_service.record_inventory_movement(product_id, payload), first)
        with self.assertRaises(ConflictError):
            product_service.record_inventory_movement(
                product_id,
                {
                    "type": "opening",
                    "quantity": "5",
                    "idempotencyKey": "same-key",
                },
            )
        with self.assertRaises(ConflictError):
            product_service.record_inventory_movement(
                product_id,
                {
                    "type": "issue",
                    "quantity": "5",
                    "idempotencyKey": "too-large",
                },
            )
        self.assertEqual(product_service.get_product(product_id)["stockOnHand"], 4)
        self.assertEqual(len(product_service.list_inventory_movements(product_id)), 1)

    def test_concurrent_receipts_are_serialized(self):
        product = product_service.create_product(self._product())
        product_id = product["id"]
        product_service.record_inventory_movement(
            product_id,
            {"type": "opening", "quantity": "1", "idempotencyKey": "opening"},
        )

        def receive(key: str):
            return product_service.record_inventory_movement(
                product_id,
                {
                    "type": "receipt",
                    "quantity": "0.5",
                    "idempotencyKey": key,
                },
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(receive, ("receipt-a", "receipt-b")))
        self.assertEqual(
            {result["resultingBalance"] for result in results},
            {1.5, 2.0},
        )
        self.assertEqual(product_service.get_product(product_id)["stockOnHand"], 2)


class ProductApiTests(unittest.TestCase):
    def setUp(self):
        import uuid
        self.unique_username = f"testuser_{uuid.uuid4().hex[:8]}"

        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "products-api.db"
        self.engine = create_database_engine(f"sqlite:///{database_path.as_posix()}")
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.repository = ProductRepository(self.session_factory, self.engine)
        self.repository_patch = patch(
            "app.services.product_service.product_repository", self.repository
        )
        self.repository_patch.start()
        app = FastAPI()
        app.include_router(products_router)
        from app.routes.auth import router as auth_router
        app.include_router(auth_router)
        self.client = TestClient(app)

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

    def test_api_product_crud_and_validation_responses(self):
        payload = ProductPersistenceTests._product()
        created = self.client.post("/api/products", json=payload, headers=self.auth_headers)
        self.assertEqual(created.status_code, 201)
        product_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/products", headers=self.auth_headers).status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}", headers=self.auth_headers).json()["code"], "ITEM-1"
        )
        self.assertEqual(
            self.client.patch(
                f"/api/products/{product_id}/status", json={"isActive": False}, headers=self.auth_headers
            ).json()["isActive"],
            False,
        )
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}/stock", headers=self.auth_headers).json()["stockOnHand"],
            None,
        )
        invalid = self.client.post(
            "/api/products", json=ProductPersistenceTests._product(defaultGstRate=2), headers=self.auth_headers
        )
        self.assertEqual(invalid.status_code, 422)

    def test_api_inventory_movements_update_stock_and_expose_history(self):
        created = self.client.post(
            "/api/products", json=ProductPersistenceTests._product(), headers=self.auth_headers
        )
        product_id = created.json()["id"]
        movement = self.client.post(
            f"/api/products/{product_id}/movements",
            json={
                "type": "opening",
                "quantity": "3.125",
                "idempotencyKey": "api-opening",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(movement.status_code, 201)
        self.assertEqual(movement.json()["resultingBalance"], 3.125)
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}/stock", headers=self.auth_headers).json()[
                "stockOnHand"
            ],
            3.125,
        )
        self.assertEqual(
            len(self.client.get(f"/api/products/{product_id}/movements", headers=self.auth_headers).json()),
            1,
        )
        invalid_adjustment = self.client.post(
            f"/api/products/{product_id}/movements",
            json={
                "type": "adjustment",
                "quantity": "1",
                "idempotencyKey": "api-adjustment",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(invalid_adjustment.status_code, 422)

    def test_api_deletes_unreferenced_product_with_delete_method(self):
        created = self.client.post(
            "/api/products", json=ProductPersistenceTests._product(), headers=self.auth_headers
        )
        self.assertEqual(created.status_code, 201)
        product_id = created.json()["id"]

        deleted = self.client.delete(f"/api/products/{product_id}", headers=self.auth_headers)

        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/products/{product_id}", headers=self.auth_headers).status_code, 404)

    def test_api_protects_product_referenced_by_invoice_item(self):
        created = self.client.post(
            "/api/products",
            json=ProductPersistenceTests._product(code="PROTECTED-ITEM"),
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, 201)
        product_id = created.json()["id"]
        with self.session_factory.begin() as session:
            session.add(
                Client(
                    id="client-product-test",
                    name="Test client",
                    billing_address="Test address",
                    gstin="29AAAAA0000A1Z5",
                )
            )
            session.flush()
            session.add(
                Invoice(
                    id="invoice-protected-product",
                    number="900/2026-27",
                    client_id="client-product-test",
                    issue_date="2026-10-25",
                    due_date="2026-11-09",
                    cgst_rate=0.09,
                    sgst_rate=0.09,
                    discount=0,
                    round_off=0,
                    is_draft=False,
                )
            )
            session.flush()
            session.add(
                InvoiceItem(
                    id="item-protected-product",
                    invoice_id="invoice-protected-product",
                    product_id=product_id,
                    description="Historical item",
                    hsn_code="1234",
                    quantity=1,
                    unit_price=1000,
                )
            )

        deleted = self.client.delete(f"/api/products/{product_id}", headers=self.auth_headers)

        self.assertEqual(deleted.status_code, 409)
        self.assertIn("historical invoice items", deleted.json()["detail"])
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}", headers=self.auth_headers).status_code,
            200,
        )

    def test_api_protects_product_with_inventory_movements(self):
        created = self.client.post(
            "/api/products",
            json=ProductPersistenceTests._product(code="PROTECTED-MOVEMENT"),
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, 201)
        product_id = created.json()["id"]
        movement = self.client.post(
            f"/api/products/{product_id}/movements",
            json={
                "type": "opening",
                "quantity": 1,
                "idempotencyKey": "protected-opening",
            },
            headers=self.auth_headers,
        )
        self.assertEqual(movement.status_code, 201)

        deleted = self.client.delete(f"/api/products/{product_id}", headers=self.auth_headers)

        self.assertEqual(deleted.status_code, 409)
        self.assertIn("inventory movements", deleted.json()["detail"])
        self.assertEqual(
            self.client.get(f"/api/products/{product_id}", headers=self.auth_headers).status_code,
            200,
        )
