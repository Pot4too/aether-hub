import json
import logging
import sqlite3
from datetime import datetime, timezone

from app.validate import ParsedMessage

logger = logging.getLogger("ingest.ingest")

_UPSERT_NODE = """
INSERT INTO nodes (node_id, first_seen, last_seen)
VALUES (?, ?, ?)
ON CONFLICT(node_id) DO UPDATE SET last_seen = excluded.last_seen
"""

_INSERT_READING = """
INSERT INTO readings (node_id, reading_ts, received_ts, timestamp_source, batch_seq, data)
VALUES (?, ?, ?, ?, ?, ?)
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _back_timestamps(received_ts: datetime, interval_ms: int | None, count: int) -> tuple[list[str], str]:
    """Compute reading_ts for each reading in a batch.

    With a declared interval: reading_ts[i] = received_ts - (N - 1 - i) * interval_ms,
    treating received_ts as a stand-in for "time the last reading was taken" (does not
    account for WiFi/MQTT connect latency before the message arrived).

    Without one (old firmware payload): every reading gets received_ts directly.
    """
    if interval_ms is None:
        return [received_ts.isoformat()] * count, "receipt_only"

    from datetime import timedelta

    timestamps = [
        (received_ts - timedelta(milliseconds=(count - 1 - i) * interval_ms)).isoformat()
        for i in range(count)
    ]
    return timestamps, "device_interval"


def process_message(conn: sqlite3.Connection, msg: ParsedMessage) -> None:
    received_ts = datetime.now(timezone.utc)
    received_ts_iso = received_ts.isoformat()
    reading_timestamps, timestamp_source = _back_timestamps(received_ts, msg.interval_ms, len(msg.readings))

    rows = [
        (msg.node_id, reading_timestamps[i], received_ts_iso, timestamp_source, i, json.dumps(msg.readings[i]))
        for i in range(len(msg.readings))
    ]

    with conn:
        conn.execute(_UPSERT_NODE, (msg.node_id, received_ts_iso, received_ts_iso))
        conn.executemany(_INSERT_READING, rows)

    logger.info(
        "ingested batch: node=%s count=%d interval_ms=%s",
        msg.node_id,
        len(msg.readings),
        msg.interval_ms,
    )
