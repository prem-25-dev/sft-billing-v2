"""SQLite data access for notifications."""

from __future__ import annotations

from threading import Lock
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Notification
from app.database.session import SessionLocal, engine, initialize_database


def _record(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "type": notification.type,
        "category": notification.category,
        "title": notification.title,
        "message": notification.message,
        "referenceId": notification.reference_id,
        "referenceType": notification.reference_type,
        "read": notification.read,
        "occurredAt": notification.occurred_at,
        "readAt": notification.read_at,
    }


class NotificationRepository:
    """Persist notification rows."""

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
                from app.database.session import initialize_database
                initialize_database(self._database_engine)
                self._initialized = True

    @staticmethod
    def _query():
        return select(Notification).order_by(Notification.occurred_at.desc(), Notification.id.desc())

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_schema()
        notification = Notification(
            id=values["id"],
            type=values["type"],
            category=values["category"],
            title=values["title"],
            message=values["message"],
            reference_id=values.get("referenceId"),
            reference_type=values.get("referenceType"),
            read=values.get("read", False),
            occurred_at=values["occurredAt"],
            read_at=values.get("readAt"),
        )
        with self._session_factory.begin() as session:
            session.add(notification)
            session.flush()
            return _record(notification)

    def get_by_id(self, notification_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            notification = session.get(Notification, notification_id)
            return _record(notification) if notification is not None else None

    def list_all(self, limit: int | None = None) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            query = select(Notification).order_by(Notification.occurred_at.desc(), Notification.id.desc())
            if limit is not None:
                query = query.limit(limit)
            return [_record(row) for row in session.scalars(query).all()]

    def list_unread(self, category: str | None = None) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            query = select(Notification).where(Notification.read == False).order_by(Notification.occurred_at.desc())
            if category:
                query = query.where(Notification.category == category)
            return [_record(row) for row in session.scalars(query).all()]

    def count_unread(self, category: str | None = None) -> int:
        self._ensure_schema()
        with self._session_factory() as session:
            query = select(Notification.id).where(Notification.read == False)
            if category:
                query = query.where(Notification.category == category)
            return len(session.scalars(query).all())

    def mark_read(self, notification_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        from app.utils.validators import now_iso
        with self._session_factory.begin() as session:
            notification = session.get(Notification, notification_id)
            if notification is None:
                return None
            notification.read = True
            notification.read_at = now_iso()
            session.flush()
            return _record(notification)

    def mark_all_read(self, category: str | None = None) -> int:
        self._ensure_schema()
        from app.utils.validators import now_iso
        with self._session_factory.begin() as session:
            query = select(Notification).where(Notification.read == False)
            if category:
                query = query.where(Notification.category == category)
            count = 0
            for notification in session.scalars(query).all():
                notification.read = True
                notification.read_at = now_iso()
                count += 1
            return count


notification_repository = NotificationRepository()