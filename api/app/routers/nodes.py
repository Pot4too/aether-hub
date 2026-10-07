import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_db
from app.schemas import NodeDetailOut, NodeOut, ReadingOut

router = APIRouter()


def _row_to_reading(row: sqlite3.Row) -> ReadingOut:
    return ReadingOut(
        id=row["id"],
        reading_ts=row["reading_ts"],
        received_ts=row["received_ts"],
        timestamp_source=row["timestamp_source"],
        data=json.loads(row["data"]),
    )


@router.get("/nodes", response_model=list[NodeOut])
def list_nodes(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        "SELECT node_id, first_seen, last_seen, label, node_type FROM nodes ORDER BY node_id"
    ).fetchall()
    return [NodeOut(**dict(row)) for row in rows]


@router.get("/nodes/{node_id}", response_model=NodeDetailOut)
def get_node(node_id: str, conn: sqlite3.Connection = Depends(get_db)):
    node_row = conn.execute(
        "SELECT node_id, first_seen, last_seen, label, node_type FROM nodes WHERE node_id = ?",
        (node_id,),
    ).fetchone()
    if node_row is None:
        raise HTTPException(status_code=404, detail=f"unknown node_id: {node_id}")

    reading_row = conn.execute(
        "SELECT id, reading_ts, received_ts, timestamp_source, data FROM readings "
        "WHERE node_id = ? ORDER BY reading_ts DESC, id DESC LIMIT 1",
        (node_id,),
    ).fetchone()

    return NodeDetailOut(
        **dict(node_row),
        latest_reading=_row_to_reading(reading_row) if reading_row is not None else None,
    )
