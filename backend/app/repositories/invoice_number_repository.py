"""SQLite persistence for permanently consumed invoice numbers."""

from __future__ import annotations

from threading import Lock
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import InvoiceNumberReservation
from app.database.session import (
    SessionLocal,
    engine,
    initialize_numbering_database,
)


def _record(reservation: InvoiceNumberReservation) -> dict[str, Any]:
    return {
        "number": reservation.number,
        "financialYear": reservation.financial_year,
        "sequence": reservation.sequence,
        "reservedFor": reservation.reserved_for,
        "reservedAt": reservation.reserved_at,
    }


class InvoiceNumberRepository:
    """Store reservations without applying numbering or financial-year rules."""

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
                initialize_numbering_database(self._database_engine)
                self._initialized = True

    def get_by_number(self, number: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            reservation = session.get(InvoiceNumberReservation, number)
            return _record(reservation) if reservation is not None else None

    def get_by_owner(self, reserved_for: str) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            reservation = session.scalar(
                select(InvoiceNumberReservation).where(
                    InvoiceNumberReservation.reserved_for == reserved_for
                )
            )
            return _record(reservation) if reservation is not None else None

    def get_by_year_sequence(
        self, financial_year: str, sequence: int
    ) -> dict[str, Any] | None:
        self._ensure_schema()
        with self._session_factory() as session:
            reservation = session.scalar(
                select(InvoiceNumberReservation).where(
                    InvoiceNumberReservation.financial_year == financial_year,
                    InvoiceNumberReservation.sequence == sequence,
                )
            )
            return _record(reservation) if reservation is not None else None

    def highest_sequence(self, financial_year: str, session: Session | None = None) -> int:
        self._ensure_schema()
        if session is not None:
            highest = session.scalar(
                select(func.max(InvoiceNumberReservation.sequence)).where(
                    InvoiceNumberReservation.financial_year == financial_year
                )
            )
            return highest or 0
        with self._session_factory() as new_session:
            highest = new_session.scalar(
                select(func.max(InvoiceNumberReservation.sequence)).where(
                    InvoiceNumberReservation.financial_year == financial_year
                )
            )
            return highest or 0

    def create(self, values: dict[str, Any], session: Session | None = None) -> dict[str, Any]:
        self._ensure_schema()
        reservation = InvoiceNumberReservation(
            number=values["number"],
            financial_year=values["financialYear"],
            sequence=values["sequence"],
            reserved_for=values.get("reservedFor"),
            reserved_at=values["reservedAt"],
        )
        if session is not None:
            session.add(reservation)
            session.flush()
            return _record(reservation)
        with self._session_factory.begin() as new_session:
            new_session.add(reservation)
            new_session.flush()
            return _record(reservation)

    def is_reserved(self, number: str) -> bool:
        return self.get_by_number(number) is not None

    def release_reservation(self, reserved_for: str, session: Session | None = None) -> bool:
        """Release a reservation by setting its reserved_for to NULL.

        Returns True if a reservation was found and released, False otherwise.
        """
        self._ensure_schema()
        if session is not None:
            reservation = session.scalar(
                select(InvoiceNumberReservation).where(
                    InvoiceNumberReservation.reserved_for == reserved_for
                )
            )
            if reservation is not None:
                reservation.reserved_for = None
                session.flush()
                return True
            return False
        with self._session_factory.begin() as new_session:
            reservation = new_session.scalar(
                select(InvoiceNumberReservation).where(
                    InvoiceNumberReservation.reserved_for == reserved_for
                )
            )
            if reservation is not None:
                reservation.reserved_for = None
                new_session.flush()
                return True
            return False


invoice_number_repository = InvoiceNumberRepository()
