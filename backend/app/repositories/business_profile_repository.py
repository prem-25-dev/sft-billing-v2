"""SQLite persistence for the singleton Business Profile."""

from __future__ import annotations

from threading import Lock
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import BusinessProfileRecord
from app.database.session import (
    SessionLocal,
    engine,
    initialize_business_profile_database,
)

_PROFILE_FIELDS = {
    "name": "name",
    "logoUrl": "logo_url",
    "address": "address",
    "email": "email",
    "phone": "phone",
    "gstin": "gstin",
    "pan": "pan",
    "bank_accountHolder": "bank_account_holder",
    "bank_bankName": "bank_bank_name",
    "bank_branch": "bank_branch",
    "bank_accountNumber": "bank_account_number",
    "bank_ifsc": "bank_ifsc",
    "declaration": "declaration",
    "authorizedSignatory": "authorized_signatory",
    "defaultGst_cgstRate": "default_gst_cgst_rate",
    "defaultGst_sgstRate": "default_gst_sgst_rate",
}


def _profile_values(profile: BusinessProfileRecord) -> dict[str, Any]:
    return {
        field: getattr(profile, model_field)
        for field, model_field in _PROFILE_FIELDS.items()
    }


class BusinessProfileRepository:
    """Read and atomically replace the one active Business Profile row."""

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
                initialize_business_profile_database(self._database_engine)
                self._initialized = True

    def get_current(self) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            profile = session.get(BusinessProfileRecord, 1)
            return _profile_values(profile) if profile is not None else None

    def save_current(self, values: dict[str, Any]) -> dict[str, Any]:
        """Create or update the singleton in one SQLite upsert transaction."""
        self._ensure_schema()
        model_values = {
            model_field: values.get(field)
            for field, model_field in _PROFILE_FIELDS.items()
        }
        statement = insert(BusinessProfileRecord).values(id=1, **model_values)
        table = BusinessProfileRecord.__table__
        statement = statement.on_conflict_do_update(
            index_elements=[BusinessProfileRecord.id],
            set_={
                column: statement.excluded[column.name]
                for column in table.columns
                if column.name != "id"
            },
        )
        with self._session_factory.begin() as session:
            session.execute(statement)
            profile = session.get(BusinessProfileRecord, 1)
            if profile is None:
                raise RuntimeError("Business Profile upsert did not persist its row.")
            return _profile_values(profile)


business_profile_repository = BusinessProfileRepository()
