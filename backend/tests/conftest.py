"""Make the suite runnable on a fresh clone.

Several API tests exercise the real auth dependency against the default
development database, so that database must exist and be migrated.
"""
import sqlite3


def pytest_sessionstart(session):
    from app.database.session import DEFAULT_DATABASE_PATH, engine, initialize_database

    path = DEFAULT_DATABASE_PATH
    ready = False
    if path.exists():
        with sqlite3.connect(str(path)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ready = "users" in tables
        if not ready and not tables:
            path.unlink()  # empty leftovers from an earlier run
    if not ready:
        path.parent.mkdir(parents=True, exist_ok=True)
        initialize_database(engine)
