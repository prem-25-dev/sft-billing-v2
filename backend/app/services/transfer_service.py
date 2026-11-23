"""Copy data between PCs: export a selected slice of the database to a single
``.sftpack`` file, and restore one on a fresh install.

A pack is a zip containing ``manifest.json`` and ``data.db`` (a SQLite copy with
only the selected sections). User accounts, sessions and reset tokens are never
exported: the new PC always creates its own user.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.database.session import _create_alembic_config, engine, SessionLocal

PACK_FORMAT = "sft-billing-pack"
PACK_VERSION = 1

# Sections the user can choose. "master" is implied by "transactions".
SECTIONS: dict[str, list[str]] = {
    "master": ["clients", "products"],
    "business": ["business_profile"],
    "transactions": [
        "invoices",
        "invoice_items",
        "invoice_number_reservations",
        "payments",
        "activities",
        "inventory_movements",
    ],
}
# Never copied to another PC.
ACCOUNT_TABLES = ["sessions", "password_reset_tokens", "recovery_attempts", "users", "notifications"]
ALL_DATA_TABLES = [t for tables in SECTIONS.values() for t in tables]


class TransferError(Exception):
    """A pack could not be created or restored; the message is safe to show."""


def _db_path() -> Path:
    database = engine.url.database
    if not database or database == ":memory:":
        raise TransferError("The database is not file-backed.")
    return Path(database)


def current_revision() -> str:
    return ScriptDirectory.from_config(_create_alembic_config()).get_current_head()


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def summary() -> dict[str, int]:
    """Row counts for each selectable section, shown on the Copy data screen."""
    with SessionLocal() as session:
        def n(table: str) -> int:
            return session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()

        return {
            "clients": n("clients"),
            "products": n("products"),
            "invoices": n("invoices"),
            "payments": n("payments"),
        }


def export_pack(include_master: bool, include_business: bool, include_transactions: bool) -> tuple[bytes, str]:
    """Return (pack_bytes, suggested_filename)."""
    if include_transactions:
        include_master = True  # invoices reference clients and products
    chosen: list[str] = []
    if include_master:
        chosen += SECTIONS["master"]
    if include_business:
        chosen += SECTIONS["business"]
    if include_transactions:
        chosen += SECTIONS["transactions"]
    if not chosen:
        raise TransferError("Choose at least one thing to copy.")

    with tempfile.TemporaryDirectory() as tmp:
        copy_path = Path(tmp) / "data.db"
        source = sqlite3.connect(str(_db_path()), timeout=30)
        try:
            dest = sqlite3.connect(str(copy_path))
            try:
                source.backup(dest)
                dest.execute("PRAGMA foreign_keys=OFF")
                for table in ACCOUNT_TABLES + [t for t in ALL_DATA_TABLES if t not in chosen]:
                    dest.execute(f'DELETE FROM "{table}"')
                dest.commit()
                counts = {t: _count(dest, t) for t in chosen}
                dest.execute("VACUUM")
            finally:
                dest.close()
        finally:
            source.close()

        manifest = {
            "format": PACK_FORMAT,
            "version": PACK_VERSION,
            "schema": current_revision(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "includes": {
                "master": include_master,
                "business": include_business,
                "transactions": include_transactions,
            },
            "counts": counts,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as pack:
            pack.writestr("manifest.json", json.dumps(manifest, indent=2))
            pack.write(copy_path, "data.db")

    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return buffer.getvalue(), f"SFT-Billing-Data-{stamp}.sftpack"


def read_manifest(pack_bytes: bytes) -> dict:
    try:
        with zipfile.ZipFile(io.BytesIO(pack_bytes)) as pack:
            manifest = json.loads(pack.read("manifest.json"))
            if "data.db" not in pack.namelist():
                raise KeyError("data.db")
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise TransferError("This is not a valid SFT Billing data file.") from None
    if manifest.get("format") != PACK_FORMAT:
        raise TransferError("This is not a valid SFT Billing data file.")
    if manifest.get("schema") != current_revision():
        raise TransferError(
            "This data file was made by a different version of SFT Billing. "
            "Install the same version on both PCs and export again."
        )
    return manifest


def restore_pack(pack_bytes: bytes) -> dict:
    """Load a pack into this PC's (still user-less) database."""
    manifest = read_manifest(pack_bytes)
    included = [
        table
        for section, tables in SECTIONS.items()
        if manifest["includes"].get(section)
        for table in tables
    ]
    with tempfile.TemporaryDirectory() as tmp:
        pack_db = Path(tmp) / "data.db"
        with zipfile.ZipFile(io.BytesIO(pack_bytes)) as pack:
            pack_db.write_bytes(pack.read("data.db"))

        conn = sqlite3.connect(str(_db_path()), timeout=30)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("ATTACH DATABASE ? AS pack", (str(pack_db),))
            conn.execute("BEGIN")
            for table in included:
                conn.execute(f'DELETE FROM main."{table}"')
                conn.execute(f'INSERT INTO main."{table}" SELECT * FROM pack."{table}"')
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                conn.rollback()
                raise TransferError("The data file is inconsistent and was not loaded.")
            conn.commit()
        finally:
            conn.close()
    return manifest
