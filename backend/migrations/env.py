from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.database import models as _models  # noqa: F401
from app.database.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
MIGRATION_DATABASE_URL_ENV = "SFT_BILLING_MIGRATION_DATABASE_URL"


def _database_url() -> str:
    return os.environ.get(MIGRATION_DATABASE_URL_ENV) or config.get_main_option(
        "sqlalchemy.url"
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_with_connection(connection) -> None:
    sqlite_foreign_keys_enabled = connection.dialect.name == "sqlite" and (
        connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    )
    if sqlite_foreign_keys_enabled:
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar() != 0:
            raise RuntimeError("Could not disable SQLite foreign keys during migration.")

    try:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()

        if sqlite_foreign_keys_enabled:
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
            if violations:
                raise RuntimeError(
                    f"SQLite foreign-key violations after migration: {violations!r}."
                )
    except Exception:
        connection.rollback()
        raise
    finally:
        if sqlite_foreign_keys_enabled:
            connection.commit()
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        _run_with_connection(supplied_connection)
        return

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url().replace("%", "%%")
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if connectable.dialect.name == "sqlite":
        @event.listens_for(connectable, "connect")
        def _enable_sqlite_foreign_keys(dbapi_connection, _) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    with connectable.connect() as connection:
        _run_with_connection(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
