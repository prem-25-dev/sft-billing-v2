"""SQLite data access for activity/audit events."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from threading import Lock
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Activity
from app.database.session import SessionLocal, engine, initialize_activity_database


def _to_paise(value: Any) -> int | None:
    if value is None:
        return None
    return int(
        (Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def _from_paise(value: int | None) -> float | None:
    return None if value is None else float(Decimal(value) / 100)


def _record(activity: Activity) -> dict[str, Any]:
    return {
        "id": activity.id,
        "type": activity.type,
        "occurredAt": activity.occurred_at,
        "summary": activity.summary,
        "clientId": activity.client_id,
        "invoiceId": activity.invoice_id,
        "paymentId": activity.payment_id,
        "amount": _from_paise(activity.amount),
    }


class ActivityRepository:
    """Persist activity rows without interpreting event types or summaries."""

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
                initialize_activity_database(self._database_engine)
                self._initialized = True

    @staticmethod
    def _query():
        return select(Activity).order_by(Activity.occurred_at.desc(), Activity.id.desc())

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_schema()
        activity = Activity(
            id=values["id"],
            type=values["type"],
            occurred_at=values["occurredAt"],
            summary=values["summary"],
            client_id=values.get("clientId"),
            invoice_id=values.get("invoiceId"),
            payment_id=values.get("paymentId"),
            amount=_to_paise(values.get("amount")),
        )
        with self._session_factory.begin() as session:
            session.add(activity)
            session.flush()
            return _record(activity)

    def get_by_id(self, activity_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            activity = session.get(Activity, activity_id)
            return _record(activity) if activity is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            return [_record(row) for row in session.scalars(self._query()).all()]

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        if limit < 0:
            raise ValueError("limit must be non-negative")
        self._ensure_schema()
        with self._session_factory() as session:
            query = self._query().limit(limit)
            return [_record(row) for row in session.scalars(query).all()]

    def list_by_client(self, client_id: str) -> list[dict[str, Any]]:
        return self._list_by(Activity.client_id == client_id)

    def list_by_invoice(self, invoice_id: str) -> list[dict[str, Any]]:
        return self._list_by(Activity.invoice_id == invoice_id)

    def list_by_payment(self, payment_id: str) -> list[dict[str, Any]]:
        return self._list_by(Activity.payment_id == payment_id)

    def _list_by(self, criterion) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            query = self._query().where(criterion)
            return [_record(row) for row in session.scalars(query).all()]


activity_repository = ActivityRepository()
