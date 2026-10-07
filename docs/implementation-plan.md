# Aether Hub — Pi-side backend (MQTT broker + ingest + query API)

## Context

`aether-hub-local` is currently an empty repo (confirmed: zero commits, only two reference docs — `aether-node.md` describing the existing ESP32-C6 firmware, and `suggested_strucure.md` describing the broader bachelor's-thesis plan). The firmware batch-publishes JSON sensor readings over MQTT but only connects to WiFi/MQTT per publish cycle, and currently sends no batch metadata (interval, count) — just a flat readings array.

The goal is to build the "hub" side of the system: something that lives on a Raspberry Pi 4B (8GB RAM, 32GB SD card, expandable via USB), receives data from potentially many independent sensor nodes (each node monitoring one thing, e.g. temperature — but a node's reading can carry multiple fields, e.g. a future BME280 node with temp+humidity+pressure), stores it, and exposes it for a future website/mobile app. The repo needs to be "ready to download and run" via Docker Compose.

Key constraints driving the design:
- **SD card longevity + limited RAM** → SQLite over Postgres, no ORM, bounded Docker log rotation.
- **Portability + thesis research need** (studying the 802.11/mac80211 association state machine) → the Pi runs its own WiFi AP (hostapd+dnsmasq) rather than joining an existing network. This must run at the **host OS level**, not in Docker, since AP mode needs direct `wlan0`/nl80211 access.
- **No RTC on the ESP32 nodes** → the hub must back-calculate each reading's timestamp from receipt time + declared interval, which in turn means the Pi's own wall clock accuracy matters. The user isn't yet sure whether the Pi will have an uplink (e.g. Ethernet) for NTP while running its own AP — so this is designed as a documented, best-effort limitation rather than assumed reliable. (Note: Ethernet uplink + WiFi-radio-as-AP is a standard combination on Pi 4B, since they're separate physical interfaces — worth trying that combo first before assuming full offline operation.)

## Decisions locked in with the user

1. Pi runs its own AP (hostapd + dnsmasq, host-level).
2. Database: SQLite (WAL mode).
3. Stack: Python — FastAPI for the query API, paho-mqtt for the ingest subscriber.
4. No dashboard in this repo — API-only; a future website/mobile app consumes it.
5. Time sync is uncertain/best-effort — document as a limitation, recommend Ethernet-uplink-while-AP as the easy fix if achievable.

## Repo layout

```
aether-hub-local/
├── README.md
├── aether-node.md                       # existing, unchanged
├── suggested_strucure.md                # existing, unchanged
├── .gitignore
├── .env.example
├── docker-compose.yml
│
├── shared/aether_shared/
│   ├── __init__.py
│   ├── schema.sql                        # single source of truth for DDL
│   └── db.py                             # get_connection(), init_db()
│
├── mosquitto/config/mosquitto.conf
│
├── ingest/
│   ├── Dockerfile
│   ├── requirements.txt                  # paho-mqtt
│   └── app/{__init__,main,config,validate,ingest}.py
│
├── api/
│   ├── Dockerfile
│   ├── requirements.txt                  # fastapi, uvicorn[standard]
│   └── app/
│       ├── {__init__,main,config,deps,schemas}.py
│       └── routers/{__init__,health,nodes,readings}.py
│
├── scripts/
│   ├── simulate_node.py                  # firmware-mimicking MQTT publisher, for testing without hardware
│   └── setup-ap.sh                       # host-level hostapd+dnsmasq bring-up (not run by compose)
│
├── docs/
│   ├── mqtt-protocol.md
│   └── network-setup.md
│
└── data/                                  # gitignored, created at runtime
    ├── sqlite/                            # aether.db (+ -wal/-shm)
    └── mosquitto/{data,log}/
```

**Sharing the DB schema without duplication:** each service's Docker build uses the **repo root as build context** with `dockerfile:` pointing into the subfolder, so `ingest/Dockerfile` and `api/Dockerfile` can both `COPY shared/aether_shared ./aether_shared` at build time. One schema file, no duplication, no symlinks.

## MQTT protocol (docs/mqtt-protocol.md)

- **Topic:** `sensors/<node_id>/data` (one topic per node — matches "one node = one purpose"; multiple fields live inside the payload). Ingest subscribes to `sensors/+/data`.
- **Current firmware payload** (must stay parseable): `{"readings":[{"temperature_c":21.43}, ...]}`.
- **Forward-compatible payload** (target for firmware to adopt later):
  ```json
  {"interval_ms": 60000, "readings": [{"temperature_c": 21.43}, {"temperature_c": 21.5}]}
  ```
  No separate count field — `len(readings)` is the count.
- **Back-timestamp logic:** given `N = len(readings)`, `received_ts` = ingest's receipt wall-clock time:
  ```
  reading_ts[i] = received_ts - (N - 1 - i) * interval_ms
  ```
  This treats `received_ts` as a stand-in for "time the last reading was taken" — it does **not** account for WiFi-connect + MQTT-connect + publish latency before the message arrives, which is unknown/variable. Document this the same way the firmware doc documents its own known limitations.
- If `interval_ms` is absent (old firmware payload), assign all readings `received_ts` directly and mark `timestamp_source='receipt_only'` (vs `'device_interval'` when the calc was applied), so API consumers can tell precision levels apart.
- Document the Pi wall-clock dependency explicitly: back-timestamping (and `received_ts` itself) is only as accurate as the Pi's system clock; if the Pi has no NTP path while running as its own AP, note Ethernet-uplink-while-AP as the recommended fix and manual `timedatectl set-time` before a fully-offline deployment as the fallback.
- No de-dup handling for redelivered MQTT messages — flagged as a known gap, not addressed now.

## SQLite schema (shared/aether_shared/schema.sql)

```sql
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
```

`data` as JSON text (not columns-per-sensor) is what makes the schema semi-modular. `shared/aether_shared/db.py` provides `init_db(db_path)` (runs `schema.sql`, idempotent via `IF NOT EXISTS`) and `get_connection(db_path, read_only=False)` — for read-only connections use `PRAGMA query_only = ON` rather than a `:ro` bind mount, since WAL mode needs write access to `-wal`/`-shm` files even for readers (a real gotcha the API's volume mount must avoid).

## Ingest service (ingest/app/)

- `config.py`: `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_FILTER` (default `sensors/+/data`), optional `MQTT_USERNAME`/`MQTT_PASSWORD`, `DB_PATH`, `LOG_LEVEL`.
- `validate.py`: parses topic against `sensors/<node_id>/data`; requires `readings` to be a non-empty list of objects; any failure logs one bounded WARNING and drops the message (never raises out of the MQTT callback).
- `ingest.py`, per valid message, in one transaction: upsert the node (`ON CONFLICT(node_id) DO UPDATE SET last_seen=...`), compute `received_ts`, back-calculate `reading_ts` per node/`interval_ms` presence, `executemany` insert all reading rows with `batch_seq` = array index, commit once per batch. One INFO log line per batch (`node=... count=... interval_ms=...`), never per-reading.
- `main.py`: paho-mqtt client with `reconnect_delay_set`, re-subscribes `on_connect`, `client.loop_forever()`. `init_db()` at startup is fail-fast (let the container restart-policy surface schema problems loudly); per-message DB errors are caught/logged, message dropped, process stays alive.

## API service (api/app/)

FastAPI, sync handlers (Starlette threadpools blocking `sqlite3` calls — no async driver needed):

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `SELECT 1`; 200 or 503 |
| GET | `/nodes` | list nodes: `node_id, first_seen, last_seen, label, node_type` |
| GET | `/nodes/{node_id}` | node detail + most recent reading; 404 if unknown |
| GET | `/nodes/{node_id}/readings` | time-range (`start`,`end`) + paginated (`limit` default 100/max 1000, `offset`) readings |

`readings` response: `{"items":[{"id","reading_ts","received_ts","timestamp_source","data":{...}}], "limit","offset","has_more"}`. No hand-maintained API reference — rely on FastAPI's `/docs` and `/redoc`. CORS via `CORSMiddleware`, `CORS_ALLOW_ORIGINS` env (default `*`, noted as something to lock down before any public exposure). API never writes to the DB — single-writer discipline stays with `ingest` (flag for later: a future "edit node label" feature should go through ingest or a small dedicated admin path, not be bolted onto the API ad hoc).

## docker-compose.yml

Three services — `mosquitto` (`eclipse-mosquitto:2`, config+persistence volumes, port 1883 published), `ingest` (built from repo root, depends on mosquitto, `DB_PATH=/data/aether.db`, sqlite data volume), `api` (built from repo root, depends on ingest, same sqlite volume **not** read-only, port 8000 published). All three: `restart: unless-stopped`, `logging: {driver: local, options: {max-size: "5m", max-file: "3"}}` (~45MB total ceiling to protect the SD card). Data directory path configurable via `.env`'s `AETHER_DATA_DIR` (default `./data`) so it can later point at a mounted USB drive without touching compose. `.gitignore` excludes `data/`, `.env`, `__pycache__/`, `*.db*`.

Base images: `python:3.12-slim-bookworm` (glibc) for `ingest`/`api` — not Alpine, since musl has spottier prebuilt-wheel coverage for `pydantic-core`/`uvloop` on `linux/arm64` and risks a slow from-source compile on the Pi.

## Host-level AP setup (docs/network-setup.md + scripts/setup-ap.sh)

Documents, for Raspberry Pi OS Lite 64-bit: confirming NetworkManager (Bookworm) vs dhcpcd (Bullseye) networking stack first since the script must branch on it; installing `hostapd`+`dnsmasq`; static `192.168.4.1/24` on `wlan0`; `dnsmasq` DHCP range; `hostapd.conf` basics (`hw_mode=g` since ESP32-C6 is 2.4GHz-only, WPA2-PSK, required `country_code`); enabling both services via systemd; verifying with `iw dev wlan0 info` and DHCP leases; a note that the secondary USB WiFi adapter used for monitor-mode capture (thesis side, out of this repo's scope) must stay unmanaged so it doesn't fight this AP setup; and the NTP note — try Ethernet-uplink-while-AP first (separate physical interfaces, no conflict), fall back to manual clock set if genuinely fully offline. `scripts/setup-ap.sh` automates the config-file writing + service enabling, with SSID/passphrase/channel/country as variables at the top; it's run manually once during Pi provisioning, never invoked by `docker compose`.

## Testing without hardware — scripts/simulate_node.py

A paho-mqtt CLI publisher mimicking the firmware: `--host`, `--port`, `--node-id` (default `sim-01`), `--interval-ms`, `--batch-size`, `--count`, a simple temperature random-walk generator, publishing the enhanced `{"interval_ms":..., "readings":[...]}` shape to `sensors/<node_id>/data`. Default fast mode sends batches back-to-back for quick smoke-testing; a `--realistic` mode sleeps `interval_ms` between simulated reads and connects/disconnects per batch like the real firmware, useful for validating the back-timestamp math and ingest's reconnect handling.

## Build order

1. Scaffold directories, `.gitignore`, `.env.example`.
2. `shared/aether_shared/schema.sql` + `db.py`.
3. `mosquitto/config/mosquitto.conf` (listener 1883, persistence on, log to stdout, `allow_anonymous true` for initial bring-up); bring up just `mosquitto` via compose, sanity-check with `mosquitto_pub`/`sub`.
4. `scripts/simulate_node.py` (test publisher, built before ingest exists).
5. `ingest/` service + Dockerfile; add to compose; verify rows land in `data/sqlite/aether.db` via the `sqlite3` CLI, using the simulator.
6. `docs/mqtt-protocol.md`, finalized once ingest behavior is confirmed.
7. `api/` service + Dockerfile; add to compose; verify `/docs`, `/health`, `/nodes`, `/nodes/{id}/readings` against simulator-produced data.
8. `docs/network-setup.md` + `scripts/setup-ap.sh` (independent track — the whole Docker pipeline is testable on a dev machine without any AP).
9. Deploy to the Pi: apply AP setup, `docker compose up -d`, point one real ESP32's `secrets.h` at the Pi's AP IP, confirm real readings and sanity-check back-calculated timestamps against manual observation.
10. `README.md` quickstart (`cp .env.example .env`, `docker compose up -d`, simulator usage, `/docs` link).

## Verification

- `docker compose up --build` brings up all three services cleanly on a dev machine (no Pi/AP needed for this step).
- `python scripts/simulate_node.py --node-id sim-01 --batch-size 5` publishes a batch; `ingest` logs one INFO line for it.
- `sqlite3 data/sqlite/aether.db "select * from readings order by id desc limit 5;"` shows the inserted rows with plausible back-calculated `reading_ts` values.
- `curl localhost:8000/health`, `curl localhost:8000/nodes`, `curl localhost:8000/nodes/sim-01/readings` return expected JSON; `localhost:8000/docs` renders Swagger UI.
- On the actual Pi (once AP is set up per `docs/network-setup.md`): a real ESP32 node publishing to the Pi's AP-side IP produces rows visible through the same API endpoints.
