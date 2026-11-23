"""SQLite persistence for products and inventory movements."""

from __future__ import annotations

from decimal import Decimal
from threading import Lock
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import InventoryMovement, Invoice, Product
from app.database.session import (
    SessionLocal,
    engine,
    initialize_products_database,
)
from app.utils.errors import ConflictError, NotFoundError
from app.utils.validators import new_id, now_iso


def _quantity_from_milli(value: int | None) -> Decimal | None:
    return Decimal(value) / 1000 if value is not None else None


def _product_record(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "code": product.code,
        "name": product.name,
        "type": product.product_type,
        "hsnCode": product.hsn_code,
        "unit": product.unit,
        "defaultUnitPrice": Decimal(product.default_unit_price) / 100,
        "defaultGstRate": product.default_gst_rate,
        "weight": _quantity_from_milli(product.weight_milli),
        "weightUnit": product.weight_unit,
        "purchaseCost": (
            Decimal(product.purchase_cost) / 100
            if product.purchase_cost is not None
            else None
        ),
        "lowStockThreshold": _quantity_from_milli(
            product.low_stock_threshold_milli
        ),
        "stockOnHand": _quantity_from_milli(product.stock_on_hand_milli),
        "isActive": product.is_active,
        "createdAt": product.created_at,
        "updatedAt": product.updated_at,
    }


def _movement_record(movement: InventoryMovement) -> dict[str, Any]:
    return {
        "id": movement.id,
        "productId": movement.product_id,
        "type": movement.movement_type,
        "quantityChange": _quantity_from_milli(movement.quantity_change_milli),
        "resultingBalance": _quantity_from_milli(
            movement.resulting_balance_milli
        ),
        "occurredAt": movement.occurred_at,
        "idempotencyKey": movement.idempotency_key,
        "invoiceId": movement.invoice_id,
        "reference": movement.reference,
        "reason": movement.reason,
        "notes": movement.notes,
    }


class ProductRepository:
    """Data access; writes commit atomically and inventory uses a SQLite write lock."""

    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        database_engine: Engine = engine,
    ) -> None:
        self._session_factory = session_factory
        self._database_engine = database_engine
        self._initialized = False
        self._initialization_lock = Lock()

    def _ensure_schema(self) -> None:
        if self._initialized:
            return
        with self._initialization_lock:
            if not self._initialized:
                initialize_products_database(self._database_engine)
                self._initialized = True

    def code_exists(self, code: str, excluding_id: str | None = None) -> bool:
        self._ensure_schema()
        statement = select(Product.id).where(Product.code == code)
        if excluding_id is not None:
            statement = statement.where(Product.id != excluding_id)
        with self._session_factory() as session:
            return session.scalar(statement.limit(1)) is not None

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_schema()
        now = now_iso()
        product = Product(
            id=values.get("id") or new_id("pr"),
            code=values["code"],
            name=values["name"],
            product_type=values["type"],
            hsn_code=values["hsnCode"],
            unit=values["unit"],
            default_unit_price=values["defaultUnitPricePaise"],
            default_gst_rate=values["defaultGstRate"],
            weight_milli=values.get("weightMilli"),
            weight_unit=values.get("weightUnit"),
            purchase_cost=values.get("purchaseCostPaise"),
            low_stock_threshold_milli=values.get("lowStockThresholdMilli"),
            is_active=values.get("isActive", True),
            created_at=now,
            updated_at=now,
        )
        try:
            with self._session_factory.begin() as session:
                session.add(product)
                session.flush()
                result = _product_record(product)
        except IntegrityError as exc:
            raise ConflictError("A product with this code already exists.") from exc
        return result

    def get_by_id(self, product_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            product = session.get(Product, product_id)
            return _product_record(product) if product is not None else None

    def list_products(
        self,
        search: str | None = None,
        is_active: bool | None = None,
        product_type: str | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        statement = select(Product)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                Product.name.ilike(pattern)
                | Product.code.ilike(pattern)
                | Product.hsn_code.ilike(pattern)
            )
        if is_active is not None:
            statement = statement.where(Product.is_active == is_active)
        if product_type is not None:
            statement = statement.where(Product.product_type == product_type)
        statement = statement.order_by(Product.name, Product.code)
        with self._session_factory() as session:
            return [
                _product_record(product)
                for product in session.scalars(statement).all()
            ]

    def update(
        self, product_id: str, values: dict[str, Any]
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            product = session.get(Product, product_id)
            if product is None:
                return None
            if values.get("type") == "service" and product.product_type != "service":
                has_movements = session.scalar(
                    select(InventoryMovement.id)
                    .where(InventoryMovement.product_id == product_id)
                    .limit(1)
                )
                if product.stock_on_hand_milli is not None or has_movements is not None:
                    raise ConflictError(
                        "A product with inventory history cannot be changed to a service."
                    )

            mapped = {
                "code": "code",
                "name": "name",
                "type": "product_type",
                "hsnCode": "hsn_code",
                "unit": "unit",
                "defaultUnitPricePaise": "default_unit_price",
                "defaultGstRate": "default_gst_rate",
                "weightMilli": "weight_milli",
                "weightUnit": "weight_unit",
                "purchaseCostPaise": "purchase_cost",
                "lowStockThresholdMilli": "low_stock_threshold_milli",
                "isActive": "is_active",
            }
            for key, attribute in mapped.items():
                if key in values:
                    setattr(product, attribute, values[key])
            product.updated_at = now_iso()
            try:
                session.flush()
            except IntegrityError as exc:
                raise ConflictError(
                    "A product with this code already exists."
                ) from exc
            return _product_record(product)

    def set_active(self, product_id: str, is_active: bool) -> dict[str, Any] | None:
        return self.update(product_id, {"isActive": is_active})

    def record_movement(
        self,
        *,
        product_id: str,
        movement_type: str,
        quantity_change_milli: int,
        idempotency_key: str,
        invoice_id: str | None = None,
        reference: str | None = None,
        reason: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_schema()
        with self._database_engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                with Session(
                    bind=connection,
                    autoflush=False,
                    expire_on_commit=False,
                ) as session:
                    existing = session.scalar(
                        select(InventoryMovement).where(
                            InventoryMovement.idempotency_key == idempotency_key
                        )
                    )
                    if existing is not None:
                        expected = (
                            existing.product_id,
                            existing.movement_type,
                            existing.quantity_change_milli,
                            existing.invoice_id,
                            existing.reference,
                            existing.reason,
                            existing.notes,
                        )
                        received = (
                            product_id,
                            movement_type,
                            quantity_change_milli,
                            invoice_id,
                            reference,
                            reason,
                            notes,
                        )
                        if expected != received:
                            raise ConflictError(
                                "This idempotency key was already used for a different movement."
                            )
                        result = _movement_record(existing)
                        connection.rollback()
                        return result

                    product = session.get(Product, product_id)
                    if product is None:
                        raise NotFoundError(f"Product {product_id} not found.")
                    if product.product_type == "service":
                        raise ConflictError(
                            "Inventory movements are not available for services."
                        )
                    if invoice_id is not None and session.get(Invoice, invoice_id) is None:
                        raise NotFoundError(f"Invoice {invoice_id} not found.")

                    current = product.stock_on_hand_milli
                    if movement_type == "opening":
                        if current is not None:
                            raise ConflictError(
                                "Opening stock has already been recorded."
                            )
                        balance = quantity_change_milli
                    else:
                        if current is None:
                            raise ConflictError(
                                "Record opening stock before other inventory movements."
                            )
                        balance = current + quantity_change_milli
                        if balance < 0:
                            raise ConflictError(
                                "The movement would make stock on hand negative."
                            )

                    if movement_type == "adjustment" and not (reason or "").strip():
                        raise ValueError("Stock adjustments require a reason.")

                    product.stock_on_hand_milli = balance
                    product.updated_at = now_iso()
                    movement = InventoryMovement(
                        id=new_id("im"),
                        product_id=product_id,
                        movement_type=movement_type,
                        quantity_change_milli=quantity_change_milli,
                        resulting_balance_milli=balance,
                        occurred_at=now_iso(),
                        idempotency_key=idempotency_key,
                        invoice_id=invoice_id,
                        reference=reference,
                        reason=reason,
                        notes=notes,
                    )
                    session.add(movement)
                    session.flush()
                    result = _movement_record(movement)
                    session.commit()
                    connection.commit()
                    return result
            except IntegrityError as exc:
                connection.rollback()
                raise ConflictError(
                    "The movement conflicts with existing inventory history."
                ) from exc
            except Exception:
                connection.rollback()
                raise

    def list_movements(
        self, product_id: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            if session.get(Product, product_id) is None:
                raise NotFoundError(f"Product {product_id} not found.")
            statement = (
                select(InventoryMovement)
                .where(InventoryMovement.product_id == product_id)
                .order_by(
                    InventoryMovement.occurred_at.desc(),
                    InventoryMovement.id.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
            return [
                _movement_record(movement)
                for movement in session.scalars(statement).all()
            ]

    def delete(self, product_id: str) -> None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            product = session.get(Product, product_id)
            if product is None:
                raise NotFoundError(f"Product {product_id} not found.")
            # Check for inventory movements (FK RESTRICT)
            has_movements = session.scalar(
                select(InventoryMovement.id)
                .where(InventoryMovement.product_id == product_id)
                .limit(1)
            )
            if has_movements is not None:
                raise ConflictError(
                    "Cannot delete product with inventory movements. Deactivate instead."
                )
            # Check for invoice items referencing this product (historical billing data)
            from app.database.models import InvoiceItem
            has_invoice_items = session.scalar(
                select(InvoiceItem.id)
                .where(InvoiceItem.product_id == product_id)
                .limit(1)
            )
            if has_invoice_items is not None:
                raise ConflictError(
                    "Cannot delete product referenced by historical invoice items. Deactivate instead."
                )
            session.delete(product)
            session.flush()


product_repository = ProductRepository()
