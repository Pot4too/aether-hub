PRAGMA journal_mode = WAL;
PRAGMA synchronous  = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nodes (
    node_id    TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    label      TEXT,
    node_type  TEXT
);

CREATE TABLE IF NOT EXISTS readings (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id           TEXT NOT NULL REFERENCES nodes(node_id),
    reading_ts        TEXT NOT NULL,
    received_ts       TEXT NOT NULL,
    timestamp_source  TEXT NOT NULL DEFAULT 'receipt_only',
    batch_seq         INTEGER,
    data              TEXT NOT NULL          -- JSON blob, e.g. {"temperature_c":21.43}
);

CREATE INDEX IF NOT EXISTS idx_readings_node_ts     ON readings(node_id, reading_ts);
CREATE INDEX IF NOT EXISTS idx_readings_received_ts ON readings(received_ts);
