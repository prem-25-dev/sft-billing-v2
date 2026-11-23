"""SQLite persistence for Client records."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Client
from app.database.session import SessionLocal, engine, initialize_client_database
from app.utils.errors import ConflictError

_API_TO_MODEL_FIELDS = {
    "id": "id",
    "name": "name",
    "contactName": "contact_name",
    "email": "email",
    "phone": "phone",
    "billingAddress": "billing_address",
    "gstin": "gstin",
    "pan": "pan",
    "notes": "notes",
}


def _client_record(client: Client) -> dict[str, Any]:
    return {
        "id": client.id,
        "name": client.name,
        "contactName": client.contact_name,
        "email": client.email,
        "phone": client.phone,
        "billingAddress": client.billing_address,
        "gstin": client.gstin,
        "pan": client.pan,
        "notes": client.notes,
    }


class ClientRepository:
    """Data access for Clients; transactions are committed per write operation."""

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
                initialize_client_database(self._database_engine)
                self._initialized = True

    @staticmethod
    def _model_values(values: dict[str, Any]) -> dict[str, Any]:
        return {
            model_field: values[api_field]
            for api_field, model_field in _API_TO_MODEL_FIELDS.items()
            if api_field in values
        }

    def create(self, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            client = Client(**self._model_values(values))
            session.add(client)
            session.flush()
            return _client_record(client)

    def get_by_id(self, client_id: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            client = session.get(Client, client_id)
            return _client_record(client) if client is not None else None

    def list_all(self) -> list[dict[str, Any]]:
        self._ensure_schema()
        with self._session_factory() as session:
            clients = session.scalars(select(Client)).all()
            return [_client_record(client) for client in clients]

    def update(self, client_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory.begin() as session:
            client = session.get(Client, client_id)
            if client is None:
                return None
            for field, value in self._model_values(values).items():
                setattr(client, field, value)
            session.flush()
            return _client_record(client)

    def delete(self, client_id: str) -> bool:
        self._ensure_schema()
        try:
            with self._session_factory.begin() as session:
                client = session.get(Client, client_id)
                if client is None:
                    return False
                session.delete(client)
                session.flush()
                return True
        except IntegrityError as exc:
            raise ConflictError(
                "This client has linked invoices or payments and cannot be deleted."
            ) from exc

    def exists_by_id(self, client_id: str) -> bool:
        self._ensure_schema()
        return self._query_exists(client_id)

    def exists_by_id_if_initialized(self, client_id: str) -> bool:
        if not self._initialized:
            if self._database_engine.dialect.name == "sqlite":
                database_path = self._database_engine.url.database
                if database_path in (None, "", ":memory:"):
                    return False
                if not Path(database_path).expanduser().is_file():
                    return False
            if not inspect(self._database_engine).has_table("clients"):
                return False
            self._initialized = True
        return self._query_exists(client_id)

    def _query_exists(self, client_id: str) -> bool:
        with self._session_factory() as session:
            return session.scalar(
                select(Client.id).where(Client.id == client_id).limit(1)
            ) is not None


client_repository = ClientRepository()
