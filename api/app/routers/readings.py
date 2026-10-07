import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_db
from app.routers.nodes import _row_to_reading
from app.schemas import ReadingsPage

router = APIRouter()

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


@router.get("/nodes/{node_id}/readings", response_model=ReadingsPage)
def get_readings(
    node_id: str,
    start: str | None = Query(None, description="ISO 8601 lower bound on reading_ts, inclusive"),
    end: str | None = Query(None, description="ISO 8601 upper bound on reading_ts, inclusive"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    node_row = conn.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node_row is None:
        raise HTTPException(status_code=404, detail=f"unknown node_id: {node_id}")

    conditions = ["node_id = ?"]
    params: list = [node_id]
    if start is not None:
        conditions.append("reading_ts >= ?")
        params.append(start)
    if end is not None:
        conditions.append("reading_ts <= ?")
        params.append(end)
    where_clause = " AND ".join(conditions)

    rows = conn.execute(
        f"SELECT id, reading_ts, received_ts, timestamp_source, data FROM readings "
        f"WHERE {where_clause} ORDER BY reading_ts ASC, id ASC LIMIT ? OFFSET ?",
        (*params, limit + 1, offset),
    ).fetchall()

    has_more = len(rows) > limit
    items = [_row_to_reading(row) for row in rows[:limit]]

    return ReadingsPage(items=items, limit=limit, offset=offset, has_more=has_more)
