"""Shared SQLite helpers for the ingest and api services.

Both services import this module (copied into their Docker image at build
time from the repo-root build context) so the schema and connection
semantics live in exactly one place.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def init_db(db_path: str) -> None:
    """Create the schema if it doesn't exist yet. Idempotent."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(_SCHEMA_PATH.read_text())
        conn.commit()
    finally:
        conn.close()


def get_connection(db_path: str, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection to the shared SQLite DB.

    WAL mode requires write access to the -wal/-shm files even for readers,
    so read-only callers use `PRAGMA query_only = ON` rather than a `:ro`
    bind mount or URI, which would break WAL checkpointing.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    if read_only:
        conn.execute("PRAGMA query_only = ON")
    return conn
