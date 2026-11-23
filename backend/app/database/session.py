"""SQLite engine, sessions, initialization, and FastAPI dependency."""

from __future__ import annotations

import os
import sqlite3
import weakref
import sys
from collections.abc import Generator
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, UniqueConstraint, create_engine, event, inspect, make_url, text
from sqlalchemy.orm import Session, sessionmaker

from app.database import models as _models  # noqa: F401
from app.database.models import Client, Invoice, InvoiceItem

DATABASE_URL_ENV = "SFT_BILLING_DATABASE_URL"
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "sft_billing.db"
_PROCESS_MIGRATION_LOCK = RLock()


def _get_resource_base_path() -> Path:
    """Get the base path for bundled resources, works in both development and PyInstaller frozen mode."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # Running in PyInstaller bundle
        base = Path(sys._MEIPASS)
        # PyInstaller places data files under a prefix based on pathex.
        # Check for the common "Software/backend" prefix used by our spec.
        prefixed = base / "Software" / "backend"
        if prefixed.exists():
            return prefixed
        return base
    # Development mode: go up from backend/app/database/ to backend/
    return Path(__file__).resolve().parents[2]


def _get_alembic_config_path() -> Path:
    """Get the path to alembic.ini, works in both development and PyInstaller frozen mode."""
    base = _get_resource_base_path()
    return base / "alembic.ini"


def _get_migrations_path() -> Path:
    """Get the migrations directory path, works in both development and PyInstaller frozen mode."""
    base = _get_resource_base_path()
    return base / "migrations"


def _create_alembic_config() -> "Config":
    """Create an Alembic Config with the correct paths for both dev and frozen modes."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    import tempfile

    migrations_path = _get_migrations_path()

    # Write debug info to a file
    debug_file = Path(tempfile.gettempdir()) / "alembic_debug.log"
    with open(debug_file, "a") as f:
        f.write(f"[info] Migrations path: {migrations_path}\n")
        f.write(f"[info] Migrations path exists: {migrations_path.exists()}\n")

        if migrations_path.exists():
            for entry in migrations_path.iterdir():
                f.write(f"[info]   {entry.name}\n")

        versions_path = migrations_path / "versions"
        f.write(f"[info] Versions path: {versions_path}\n")
        f.write(f"[info] Versions path exists: {versions_path.exists()}\n")
        if versions_path.exists():
            for entry in versions_path.iterdir():
                f.write(f"[info]   {entry.name}\n")

    alembic_config = Config()
    alembic_config.set_main_option(
        "script_location",
        str(migrations_path).replace("\\", "/").replace("%", "%%"),
    )
    alembic_config.set_main_option("sqlalchemy.url", "sqlite://")
    alembic_config.set_main_option("path_separator", "os")
    alembic_config.set_main_option(
        "prepend_sys_path",
        str(migrations_path.parent).replace("\\", "/").replace("%", "%%"),
    )

    # Verify script directory can be loaded
    script = ScriptDirectory.from_config(alembic_config)
    with open(debug_file, "a") as f:
        f.write(f"[info] Script directory heads: {script.get_heads()}\n")
        for rev in script.walk_revisions():
            f.write(f"[info]   Revision: {rev.revision}\n")

    return alembic_config


DATABASE_URL_ENV = "SFT_BILLING_DATABASE_URL"
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "sft_billing.db"
_PROCESS_MIGRATION_LOCK = RLock()


def _default_database_url() -> str:
    configured_url = os.environ.get(DATABASE_URL_ENV)
    if configured_url:
        return configured_url
    return f"sqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"


def create_database_engine(database_url: str | None = None) -> Engine:
    """Create a SQLite engine with local-app-safe connection defaults."""
    url = database_url or _default_database_url()
    connect_args = {"timeout": 30, "check_same_thread": False} if url.startswith("sqlite:") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

    if url.startswith("sqlite:"):
        @event.listens_for(engine, "connect")
        def _configure_sqlite_connection(dbapi_connection, _) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA synchronous=FULL")
            cursor.close()

    return engine


def validate_production_database() -> None:
    """Require a pre-existing, non-empty LocalAppData database in frozen builds."""
    if not getattr(sys, "frozen", False):
        return

    configured_url = os.environ.get(DATABASE_URL_ENV)
    if not configured_url:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must point to the persistent production database."
        )

    database_url = make_url(configured_url)
    if database_url.get_backend_name() != "sqlite" or not database_url.database:
        raise RuntimeError("The production database must use a file-backed SQLite URL.")

    database_path = Path(database_url.database).expanduser().resolve()
    if not database_path.is_file():
        # Fresh install: the first-run setup creates the database (empty, or restored
        # from a data file copied from another PC).
        return

    try:
        with closing(
            sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
        ) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    except sqlite3.DatabaseError as error:
        raise RuntimeError(
            f"Production database at {database_path} is not a readable SQLite database."
        ) from error

    if tables and "clients" not in tables:
        raise RuntimeError(
            f"Production database at {database_path} has no client schema. "
            "It will not be initialized as an empty database."
        )


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """Yield a request-scoped session and always release its connection."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Engines already confirmed to be at the latest migration. Every repository
# calls its initializer per request; re-running the migration probe holds one
# pooled connection while opening another, which deadlocks the pool when
# requests arrive in parallel. Once an engine is at head it cannot regress, so
# the probe only needs to succeed once per engine.
_AT_HEAD_ENGINES: "weakref.WeakSet[Engine]" = weakref.WeakSet()


def _upgrade_database(target_engine: Engine, revision: str) -> None:
    if target_engine in _AT_HEAD_ENGINES:
        return

    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext

    database_path = None
    database_existed = False
    if target_engine.dialect.name == "sqlite" and target_engine.url.database not in (
        None,
        "",
        ":memory:",
    ):
        database_path = Path(target_engine.url.database).expanduser()
        database_existed = database_path.is_file()
        database_path.parent.mkdir(parents=True, exist_ok=True)

    # Fast path: check current migration version without full alembic config
    if database_existed and database_path is not None:
        try:
            with target_engine.connect() as conn:
                # Check if alembic_version table exists and get current head
                result = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
                if result:
                    current_version = result[0]
                    # If we're already at head, skip the full upgrade process
                    alembic_config = _create_alembic_config()
                    script = ScriptDirectory.from_config(alembic_config)
                    target_heads = set(script.get_heads())
                    if current_version in target_heads:
                        _log_info(f"[info] Database already at latest migration ({current_version}), skipping upgrade")
                        _AT_HEAD_ENGINES.add(target_engine)
                        return
        except Exception as e:
            # If fast path fails (e.g., table doesn't exist), fall through to full upgrade
            _log_info(f"[info] Fast path check failed, proceeding with full upgrade: {e}")

    # Create alembic config programmatically to avoid issues with bundled env.py
    alembic_config = _create_alembic_config()
    _log_info(f"[info] Using migrations directory: {_get_migrations_path()}")
    _log_info(f"[info] Target revision: {revision}")

    with _migration_lock(target_engine):
        with target_engine.connect() as connection:
            if target_engine.dialect.name == "sqlite" and target_engine.url.database not in (
                None,
                "",
                ":memory:",
            ):
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")

            if (
                database_existed
                and database_path is not None
                and _migration_is_pending(connection, alembic_config)
            ):
                _log_info("[info] Pending migration detected, creating backup...")
                _backup_database_before_migration(connection, database_path)

            _recover_unversioned_partial_schema(connection, alembic_config)
            if revision != "head" and _has_applied_revision(
                connection, alembic_config, revision
            ):
                _log_info(f"[info] Revision {revision} already applied, skipping")
                return

            _log_info(f"[info] Running migration to revision: {revision}")
            try:
                alembic_config.attributes["connection"] = connection
                command.upgrade(alembic_config, revision)
                current_heads = MigrationContext.configure(connection).get_current_heads()
                if not current_heads:
                    raise RuntimeError("Migration completed but alembic_version is empty")
                _log_info(f"[info] Migration completed successfully: {current_heads}")
            except Exception as e:
                _log_info(f"[error] Migration failed: {e}")
                raise


def _migration_is_pending(connection, alembic_config) -> bool:
    current_heads = set(MigrationContext.configure(connection).get_current_heads())
    # Create a fresh config to get the correct target heads
    alembic_config = _create_alembic_config()
    target_heads = set(ScriptDirectory.from_config(alembic_config).get_heads())
    return current_heads != target_heads


# Maximum number of migration backups to retain per database
MAX_MIGRATION_BACKUPS = 10


def _log_info(message: str) -> None:
    """Log info message to stderr (captured by Tauri)."""
    print(message, file=sys.stderr, flush=True)


def _backup_database_before_migration(connection, database_path: Path) -> Path:
    """Create a verified backup of the database before migration.

    Uses SQLite's backup API which handles WAL mode correctly by copying
    pages directly from the source database (including any uncheckpointed WAL frames).
    Verifies backup integrity before returning.

    Also enforces a retention policy to prevent unbounded disk growth.
    """
    backup_directory = database_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)

    # Set restrictive permissions on backup directory (Windows: inherit from parent)
    try:
        if os.name != "nt":
            os.chmod(backup_directory, 0o700)
    except OSError:
        pass  # Non-fatal

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_directory / (
        f"{database_path.stem}.before-migration-{timestamp}{database_path.suffix}"
    )

    # Ensure WAL is checkpointed for a consistent backup
    # The SQLite backup API handles this, but explicit checkpoint reduces backup size
    try:
        connection.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        # Non-fatal - backup API will still work
        pass

    destination = sqlite3.connect(str(backup_path))
    try:
        # SQLite backup API copies page-by-page, handling WAL correctly
        connection.connection.driver_connection.backup(destination)

        # Verify backup integrity
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError(
                f"Pre-migration backup failed integrity_check: {backup_path}"
            )

        # Verify backup has the same schema version
        backup_version = destination.execute(
            "SELECT version_num FROM alembic_version LIMIT 1"
        ).fetchone()
        source_version = connection.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ).fetchone()
        if backup_version != source_version:
            raise RuntimeError(
                f"Backup migration version mismatch: source={source_version}, backup={backup_version}"
            )

    finally:
        destination.close()

    # Set restrictive permissions on backup file
    try:
        if os.name != "nt":
            os.chmod(backup_path, 0o600)
    except OSError:
        pass  # Non-fatal

    # Enforce retention policy
    _prune_old_backups(backup_directory, database_path.stem)

    _log_info(f"[info] Created verified pre-migration backup: {backup_path}")
    return backup_path


def _prune_old_backups(backup_directory: Path, db_stem: str) -> None:
    """Remove old migration backups beyond the retention limit.

    Keeps the most recent MAX_MIGRATION_BACKUPS files matching the pattern.
    Never deletes the only backup if retention would leave zero.
    """
    try:
        pattern = f"{db_stem}.before-migration-*"
        backups = sorted(backup_directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        if len(backups) > MAX_MIGRATION_BACKUPS:
            for old_backup in backups[MAX_MIGRATION_BACKUPS:]:
                try:
                    old_backup.unlink()
                    _log_info(f"[info] Pruned old migration backup: {old_backup}")
                except OSError:
                    pass  # Non-fatal
    except Exception:
        pass  # Non-fatal - retention is best effort


@contextmanager
def _migration_lock(target_engine: Engine):
    """Serialize migration checks and upgrades across threads and processes."""
    with _PROCESS_MIGRATION_LOCK:
        database = target_engine.url.database
        if (
            target_engine.dialect.name != "sqlite"
            or database in (None, "", ":memory:")
        ):
            yield
            return

        lock_path = Path(database).expanduser().resolve().with_suffix(
            Path(database).suffix + ".migration.lock"
        )
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _recover_unversioned_partial_schema(connection, alembic_config) -> None:
    """Adopt only the known, additive partial schema left by interrupted upgrades."""
    from alembic import command

    if MigrationContext.configure(connection).get_current_heads():
        return

    inspector = inspect(connection)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    if not tables:
        return

    allowed_tables = {"clients", "invoices", "invoice_items"}
    if not tables.issubset(allowed_tables) or "clients" not in tables:
        raise RuntimeError(
            "Cannot safely recover an unversioned SQLite schema with unexpected "
            f"tables: {', '.join(sorted(tables - allowed_tables)) or 'missing clients'}."
        )

    _validate_existing_table(connection, Client)
    client_columns = {
        column["name"]: column for column in inspector.get_columns("clients")
    }
    nullable_contact_fields = ("email", "phone", "pan")
    contact_nullability = {
        client_columns[field]["nullable"] for field in nullable_contact_fields
    }
    if len(contact_nullability) != 1:
        raise RuntimeError(
            "Cannot safely recover Client contacts with mixed nullability."
        )
    contacts_are_nullable = contact_nullability.pop()

    if "invoice_items" in tables and "invoices" not in tables:
        raise RuntimeError(
            "Cannot safely recover invoice_items without its invoices table."
        )
    if "invoices" in tables:
        _validate_existing_table(connection, Invoice)
        if "invoice_items" in tables:
            _validate_existing_table(connection, InvoiceItem)

    # Create a fresh alembic config for correct paths
    alembic_config = _create_alembic_config()
    alembic_config.attributes["connection"] = connection
    if not _has_applied_revision(connection, alembic_config, "0001_sqlite"):
        command.stamp(alembic_config, "0001_sqlite")

    if "invoices" in tables:
        if "invoice_items" not in tables:
            InvoiceItem.__table__.create(connection, checkfirst=True)
        if not _has_applied_revision(connection, alembic_config, "0002_invoice_core"):
            command.stamp(alembic_config, "0002_invoice_core")

    client_revision_applied = _has_applied_revision(
        connection, alembic_config, "0007_nullable_client_contact_fields"
    )
    if contacts_are_nullable and not client_revision_applied:
        command.stamp(alembic_config, "0007_nullable_client_contact_fields")
    elif not contacts_are_nullable and client_revision_applied:
        raise RuntimeError(
            "SQLite marks the nullable Client migration as applied, but email, "
            "phone, and PAN are still NOT NULL."
        )

    if not contacts_are_nullable:
        alembic_config.attributes["connection"] = connection
        command.upgrade(alembic_config, "0007_nullable_client_contact_fields")


def _validate_existing_table(connection, model) -> None:
    inspector = inspect(connection)
    table_name = model.__tablename__
    expected_columns = {column.name: column for column in model.__table__.columns}
    actual_columns = {
        column["name"]: column for column in inspector.get_columns(table_name)
    }
    if actual_columns.keys() != expected_columns.keys():
        raise RuntimeError(
            f"Cannot safely recover {table_name}: its columns do not match the "
            "known migration schema."
        )

    for name, expected in expected_columns.items():
        actual = actual_columns[name]
        if actual["type"]._type_affinity is not expected.type._type_affinity:
            raise RuntimeError(
                f"Cannot safely recover {table_name}: column {name} has an "
                "unexpected SQL type."
            )
        if name in {"email", "phone", "pan"} and table_name == "clients":
            continue
        if actual["nullable"] != expected.nullable:
            raise RuntimeError(
                f"Cannot safely recover {table_name}: column {name} has "
                "unexpected nullability."
            )

    expected_primary_key = {
        column.name for column in model.__table__.primary_key.columns
    }
    actual_primary_key = set(inspector.get_pk_constraint(table_name)["constrained_columns"])
    if actual_primary_key != expected_primary_key:
        raise RuntimeError(
            f"Cannot safely recover {table_name}: its primary key differs from "
            "the known migration schema."
        )

    expected_unique_constraints = {
        frozenset(constraint.columns.keys())
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    actual_unique_constraints = {
        frozenset(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
        if constraint.get("column_names")
    }
    if actual_unique_constraints != expected_unique_constraints:
        raise RuntimeError(
            f"Cannot safely recover {table_name}: its unique constraints differ "
            "from the known migration schema."
        )

    expected_foreign_keys = {
        (tuple(constraint.column_keys), element.column.table.name, (element.column.name,))
        for constraint in model.__table__.foreign_key_constraints
        for element in constraint.elements
    }
    actual_foreign_keys = {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            f"Cannot safely recover {table_name}: its foreign keys differ from "
            "the known migration schema."
        )


def _has_applied_revision(connection, alembic_config, target_revision: str) -> bool:
    current_heads = MigrationContext.configure(connection).get_current_heads()
    if not current_heads:
        return False

    # Create a fresh config to ensure correct paths
    alembic_config = _create_alembic_config()
    script = ScriptDirectory.from_config(alembic_config)
    for current_head in current_heads:
        pending = [current_head]
        visited: set[str] = set()
        found = False
        while pending:
            current_revision = pending.pop()
            if current_revision == target_revision:
                found = True
                break
            if current_revision in visited:
                continue
            visited.add(current_revision)
            revision = script.get_revision(current_revision)
            if revision is None:
                break
            down_revision = revision.down_revision
            if isinstance(down_revision, tuple):
                pending.extend(down_revision)
            elif down_revision is not None:
                pending.append(down_revision)
        if found:
            return True
    return False


def initialize_client_database(target_engine: Engine = engine) -> None:
    """Apply schema through the nullable Client contact-field revision."""
    _upgrade_database(target_engine, "0007_nullable_client_contact_fields")


def initialize_invoice_database(target_engine: Engine = engine) -> None:
    """Apply Client and Invoice/InvoiceItem schema revisions to the supplied engine."""
    _upgrade_database(target_engine, "0002_invoice_core")


def initialize_numbering_database(target_engine: Engine = engine) -> None:
    """Apply Client, Invoice, and invoice-number reservation revisions."""
    _upgrade_database(target_engine, "0003_invoice_number_reservations")


def initialize_payment_database(target_engine: Engine = engine) -> None:
    """Apply migrations through SQLite Payment persistence."""
    _upgrade_database(target_engine, "0004_payments")


def initialize_activity_database(target_engine: Engine = engine) -> None:
    """Apply migrations through SQLite Activity persistence."""
    _upgrade_database(target_engine, "0005_activities")


def initialize_business_profile_database(target_engine: Engine = engine) -> None:
    """Apply migrations through SQLite Business Profile persistence."""
    _upgrade_database(target_engine, "0006_business_profile")


def initialize_products_database(target_engine: Engine = engine) -> None:
    """Apply migrations through the Products and Inventory schema."""
    _upgrade_database(target_engine, "0009_products")


def initialize_notifications_database(target_engine: Engine = engine) -> None:
    """Apply migrations through the Notifications schema."""
    _upgrade_database(target_engine, "0010_notifications")


def initialize_database(target_engine: Engine = engine) -> None:
    """Apply all available Alembic migrations to the explicitly supplied engine."""
    _upgrade_database(target_engine, "head")


def shutdown_database(target_engine: Engine = engine) -> None:
    """Dispose pooled connections; request sessions should be closed first."""
    target_engine.dispose()
