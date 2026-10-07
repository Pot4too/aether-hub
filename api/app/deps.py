import sqlite3
from collections.abc import Iterator

from aether_shared.db import get_connection

from app.config import config


def get_db() -> Iterator[sqlite3.Connection]:
    conn = get_connection(config.DB_PATH, read_only=True)
    try:
        yield conn
    finally:
        conn.close()
