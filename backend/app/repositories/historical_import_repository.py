"""Session-scoped persistence operations for an approved historical import."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.database.models import Client, Invoice, InvoiceItem, InvoiceNumberReservation


def _model_values(
    model: type,
    record: dict[str, Any],
    money_fields: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for attribute in inspect(model).column_attrs:
        column = attribute.columns[0]
        source_field = column.name
        if source_field not in record:
            continue
        value = record[source_field]
        if source_field in money_fields:
            value = int(
                (Decimal(str(value)) * 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        values[attribute.key] = value
    return values


class HistoricalImportRepository:
    """Persist preview candidates through a caller-owned SQLAlchemy transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def find_existing_conflicts(
        self, records: dict[str, tuple[dict[str, Any], ...]]
    ) -> tuple[dict[str, str], ...]:
        conflicts: list[dict[str, str]] = []
        clients = records["clients"]
        invoices = records["invoices"]
        items = records["invoiceItems"]
        reservations = records["reservations"]

        self._collect_conflicts(
            conflicts, "clients", "id", Client.id, (row["id"] for row in clients)
        )
        self._collect_conflicts(
            conflicts, "invoices", "id", Invoice.id, (row["id"] for row in invoices)
        )
        self._collect_conflicts(
            conflicts,
            "invoices",
            "number",
            Invoice.number,
            (row["number"] for row in invoices),
        )
        self._collect_conflicts(
            conflicts,
            "invoiceItems",
            "id",
            InvoiceItem.id,
            (row["id"] for row in items),
        )
        self._collect_conflicts(
            conflicts,
            "reservations",
            "number",
            InvoiceNumberReservation.number,
            (row["number"] for row in reservations),
        )

        year_sequences = {
            (row["financialYear"], row["sequence"]) for row in reservations
        }
        existing_year_sequences = set(
            self._session.execute(
                select(
                    InvoiceNumberReservation.financial_year,
                    InvoiceNumberReservation.sequence,
                ).where(
                    InvoiceNumberReservation.financial_year.in_(
                        {year for year, _ in year_sequences}
                    )
                )
            ).tuples()
        )
        for financial_year, sequence in sorted(year_sequences):
            if (financial_year, sequence) in existing_year_sequences:
                conflicts.append(
                    {
                        "entity": "reservations",
                        "key": f"{financial_year}/{sequence}",
                    }
                )

        owners = {row["reservedFor"] for row in reservations}
        owners.discard(None)
        if owners:
            existing_owners = set(
                self._session.scalars(
                    select(InvoiceNumberReservation.reserved_for).where(
                        InvoiceNumberReservation.reserved_for.in_(owners)
                    )
                )
            )
            conflicts.extend(
                {"entity": "reservations", "key": f"reservedFor={owner}"}
                for owner in sorted(existing_owners)
            )
        return tuple(conflicts)

    def assert_import_schema_ready(self) -> None:
        connection = self._session.connection()
        inspector = inspect(connection)
        models = (Client, Invoice, InvoiceItem, InvoiceNumberReservation)
        required_columns = {
            model.__tablename__: {column.name for column in model.__table__.columns}
            for model in models
        }
        missing_tables = required_columns.keys() - set(inspector.get_table_names())
        if missing_tables:
            raise RuntimeError(
                "SQLite schema is not migrated for historical import; missing "
                f"tables: {', '.join(sorted(missing_tables))}."
            )

        missing_model_columns: list[str] = []
        for table, expected_columns in required_columns.items():
            available_columns = {
                column["name"] for column in inspector.get_columns(table)
            }
            missing_model_columns.extend(
                f"{table}.{column}"
                for column in sorted(expected_columns - available_columns)
            )
        if missing_model_columns:
            raise RuntimeError(
                "SQLite schema does not match the current import models; missing "
                f"columns: {', '.join(missing_model_columns)}."
            )

        client_columns = {
            column["name"]: column for column in inspector.get_columns("clients")
        }
        nullable_contact_fields = {"email", "phone", "pan"}
        non_nullable_fields = {
            field
            for field in nullable_contact_fields
            if not client_columns[field]["nullable"]
        }
        if non_nullable_fields:
            raise RuntimeError(
                "SQLite schema must apply the nullable client-field migration "
                f"before import: {', '.join(sorted(non_nullable_fields))}."
            )

        required_unique_keys = {
            "invoices": {
                frozenset({"number"}),
                frozenset({"id", "clientId"}),
            },
            "invoice_number_reservations": {
                frozenset({"financialYear", "sequence"}),
                frozenset({"reservedFor"}),
            },
        }
        for table, expected_keys in required_unique_keys.items():
            actual_keys = {
                frozenset(constraint["column_names"])
                for constraint in inspector.get_unique_constraints(table)
                if constraint.get("column_names")
            }
            actual_keys.update(
                frozenset(index["column_names"])
                for index in inspector.get_indexes(table)
                if index.get("unique") and index.get("column_names")
            )
            missing_keys = expected_keys - actual_keys
            if missing_keys:
                raise RuntimeError(
                    f"SQLite schema is missing unique constraints on {table}: "
                    f"{sorted(tuple(sorted(key)) for key in missing_keys)!r}."
                )

        required_foreign_keys = {
            "invoices": {(("clientId",), "clients", ("id",))},
            "invoice_items": {(("invoiceId",), "invoices", ("id",))},
        }
        for table, expected_keys in required_foreign_keys.items():
            actual_keys = {
                (
                    tuple(foreign_key.get("constrained_columns") or ()),
                    foreign_key.get("referred_table"),
                    tuple(foreign_key.get("referred_columns") or ()),
                )
                for foreign_key in inspector.get_foreign_keys(table)
            }
            if not expected_keys.issubset(actual_keys):
                raise RuntimeError(
                    f"SQLite schema is missing required foreign keys on {table}."
                )

    def add_clients(self, records: tuple[dict[str, Any], ...]) -> None:
        self._session.add_all(
            Client(**_model_values(Client, record)) for record in records
        )
        self._session.flush()

    def add_invoices(self, records: tuple[dict[str, Any], ...]) -> None:
        money_fields = frozenset({"discount", "roundOff"})
        self._session.add_all(
            Invoice(**_model_values(Invoice, record, money_fields))
            for record in records
        )
        self._session.flush()

    def add_invoice_items(self, records: tuple[dict[str, Any], ...]) -> None:
        money_fields = frozenset({"unitPrice"})
        self._session.add_all(
            InvoiceItem(**_model_values(InvoiceItem, record, money_fields))
            for record in records
        )
        self._session.flush()

    def add_reservations(self, records: tuple[dict[str, Any], ...]) -> None:
        self._session.add_all(
            InvoiceNumberReservation(**_model_values(InvoiceNumberReservation, record))
            for record in records
        )
        self._session.flush()

    def assert_foreign_key_integrity(self) -> None:
        connection = self._session.connection()
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 1:
            raise RuntimeError("SQLite foreign-key enforcement is not enabled.")
        violations = connection.execute(text("PRAGMA foreign_key_check")).all()
        if violations:
            raise RuntimeError(
                f"SQLite foreign-key integrity check failed: {violations!r}."
            )

    def _collect_conflicts(
        self,
        conflicts: list[dict[str, str]],
        entity: str,
        field: str,
        column,
        keys,
    ) -> None:
        key_values = set(keys)
        if not key_values:
            return
        existing = set(
            self._session.scalars(select(column).where(column.in_(key_values)))
        )
        conflicts.extend(
            {"entity": entity, "key": f"{field}={key}"}
            for key in sorted(existing)
        )
