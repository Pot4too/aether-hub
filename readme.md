# Aether Hub — Pi-side backend

MQTT broker + ingest + query API for a Raspberry Pi 4B that receives
batched sensor readings from independent ESP32-based nodes
([aether-node.md](to_move/aether-node.md)), stores them in SQLite, and exposes
them over HTTP for a future website/mobile app.

Each node monitors one thing (e.g. "kitchen temperature") but its payload
can carry multiple fields (e.g. a future BME280 node publishing
temperature + humidity + pressure together). The system is designed to
run standalone on a Pi that hosts its own WiFi access point, with no
dependency on an existing network or internet uplink.

See [implementation-plan.md](docs/implementation-plan.md) for the full design
rationale behind these choices, and
[suggested_strucure.md](suggested_strucure.md) for the broader
bachelor's-thesis context this project sits inside.

## How data flows through the system

```
 ESP32 node                    Raspberry Pi
┌───────────┐   WiFi (AP)     ┌──────────────────────────────────────────────┐
│ read sensor│ ───────────────▶│  mosquitto   │        │                     │
│ batch N    │  MQTT publish   │  (broker)    │        │                     │
│ readings   │  QoS 0/1        │  1883        │        │                     │
└───────────┘                 └──────┬───────┘        │                     │
                                      │ subscribes to  │                     │
                                      │ sensors/+/data │                     │
                                      ▼                │                     │
                               ┌──────────────┐        │                     │
                               │   ingest     │        │                     │
                               │ - validates  │        │                     │
                               │ - back-calcs │        │                     │
                               │   timestamps │        │                     │
                               │ - writes DB  │        │                     │
                               └──────┬───────┘        │                     │
                                      │ single writer   │                     │
                                      ▼                │                     │
                               ┌──────────────┐         │                    │
                               │  SQLite (WAL)│◀────────┘ read-only          │
                               │ aether.db    │           connection         │
                               └──────┬───────┘                              │
                                      │                                      │
                                      ▼                                      │
                               ┌──────────────┐    HTTP     ┌─────────────┐  │
                               │     api      │◀────────────│  future     │  │
                               │  (FastAPI)   │─────────────▶│  website/   │  │
                               │  8000        │   JSON       │  mobile app │  │
                               └──────────────┘              └─────────────┘  │
                                                                              │
                              (all three run in Docker Compose; the AP itself└
                               runs at the host OS level — see below)
```

Nodes never talk to the API and the API never writes to the database —
`ingest` is the single writer, which keeps the SQLite concurrency story
simple (one writer, many readers, WAL mode).

## Repo layout and what each part does

```
aether-hub-local/
├── docker-compose.yml        # wires the 3 services together
├── .env.example               # copy to .env to configure ports/paths
├── mosquitto/config/          # broker config (listener, persistence, logging)
├── shared/aether_shared/      # schema.sql + db.py — the one shared source of DB truth
├── ingest/                     # MQTT subscriber -> SQLite writer
├── api/                        # FastAPI read-only query service
├── scripts/
│   ├── simulate_node.py       # fake sensor node, for testing without hardware
│   ├── start.sh / stop.sh     # start/stop the docker compose stack
│   ├── wifi-setup.sh          # host-level WiFi AP + uplink bring-up (run manually on the Pi)
│   └── wifi.conf.example      # copy to wifi.conf (gitignored) and edit
├── docs/
│   ├── mqtt-protocol.md       # topic/payload spec, back-timestamp math, in depth
│   ├── wifi-setup.md          # Pi AP + uplink setup, NTP, legacy hostapd, adapter notes
│   ├── startup-and-shutdown.md
│   └── implementation-plan.md # original design rationale
└── data/                       # gitignored; created at runtime (SQLite + mosquitto files)
```

### `mosquitto/` — the MQTT broker

Plain `eclipse-mosquitto:2` with anonymous access allowed (this is a
closed network the Pi itself controls via its own AP, not exposed to the
internet). Listens on `1883`, persists its own state under
`data/mosquitto/`, logs to stdout so `docker compose logs mosquitto`
shows activity. This is the only component nodes talk to directly.

### `shared/aether_shared/` — the single source of DB truth

Both `ingest` and `api` need to agree on the database schema and
connection semantics, so that logic lives in exactly one place here
instead of being duplicated:

- **`schema.sql`** — the `nodes` and `readings` tables (see [Database
  schema](#database-schema) below). Applied via `CREATE TABLE IF NOT
  EXISTS`, so re-running it is always safe.
- **`db.py`** — `init_db(path)` (runs the schema once at startup) and
  `get_connection(path, read_only=...)`. The read-only path is the one
  subtle bit: WAL mode needs write access to the `-wal`/`-shm` sidecar
  files even for readers, so `api` doesn't mount the DB as a read-only
  volume — instead it opens a normal read-write connection and sets
  `PRAGMA query_only = ON`, which blocks writes at the SQLite level while
  still letting WAL do its thing.

Each service's Dockerfile copies this folder in at build time (build
context is the repo root), so there's one schema file, no symlinks, no
copy-paste drift.

### `ingest/` — MQTT subscriber → SQLite writer

The only thing in this system allowed to write to the database. Flow per
incoming message ([ingest/app/main.py](ingest/app/main.py)):

1. **`validate.py`** parses the topic against `sensors/<node_id>/data` and
   checks the payload has a non-empty `readings` array of objects. Any
   failure logs one bounded `WARNING` and drops the message — it never
   raises out of the MQTT callback, so one bad message can't take the
   whole subscriber down.
2. **`ingest.py`** takes a validated message and, in a single transaction:
   upserts the `nodes` row (`last_seen` bumped), computes `received_ts`
   (the wall-clock time the message arrived), back-calculates each
   reading's `reading_ts` from `interval_ms` if the node declared one (see
   [MQTT protocol](#mqtt-protocol) below), and inserts all rows in the
   batch with `executemany`. One `INFO` log line per batch, not per
   reading, to keep logs from flooding the SD card.
3. **`main.py`** wires up `paho-mqtt` with auto-reconnect
   (`reconnect_delay_set`), re-subscribing on every reconnect, and calls
   `init_db()` once at startup — that call is fail-fast (a broken schema
   should crash the container loudly, not silently limp along), while
   per-message DB errors are caught, logged, and dropped so the process
   itself stays alive.

### `api/` — read-only query service

FastAPI app ([api/app/main.py](api/app/main.py)) with three routers,
each a thin, synchronous read over the shared connection helper
(`sqlite3` calls block, but Starlette runs sync handlers in a
threadpool, so no async DB driver is needed):

| Router | Endpoint | What it returns |
|---|---|---|
| `health.py` | `GET /health` | `200 {"status":"ok"}`, or `503` if `SELECT 1` fails |
| `nodes.py` | `GET /nodes` | every known node: `node_id, first_seen, last_seen, label, node_type` |
| `nodes.py` | `GET /nodes/{node_id}` | one node's detail + its most recent reading; `404` if unknown |
| `readings.py` | `GET /nodes/{node_id}/readings` | paginated readings, optionally filtered by `start`/`end` on `reading_ts` |

`readings` responses look like:

```json
{
  "items": [
    {"id": 42, "reading_ts": "...", "received_ts": "...", "timestamp_source": "device_interval", "data": {"temperature_c": 21.43}}
  ],
  "limit": 100,
  "offset": 0,
  "has_more": false
}
```

There's no hand-maintained API reference doc — FastAPI generates
interactive docs at `/docs` (Swagger UI) and `/redoc` automatically from
the route definitions and Pydantic schemas in
[api/app/schemas.py](api/app/schemas.py). CORS is controlled by the
`CORS_ALLOW_ORIGINS` env var (default `*` — see
[Known limitations](#known-limitations)).

### `scripts/` — tools that aren't part of the running system

- **`simulate_node.py`** — a `paho-mqtt` CLI publisher that mimics the
  firmware closely enough to exercise the whole pipeline without any ESP32
  hardware. See [Testing without hardware](#testing-without-hardware).
- **`wifi-setup.sh`** — creates the NetworkManager profiles for the Pi's own
  access point (onboard WiFi) and the prioritised uplinks (USB adapter),
  driven by `scripts/wifi.conf`. Run manually with `sudo` during Pi
  provisioning; deliberately **not** wired into `docker compose`, because AP
  mode needs direct `wlan0`/nl80211 access at the host OS level that a
  container doesn't have.
- **`start.sh` / `stop.sh`** — bring the compose stack up (creating the data
  directories first) and stop it cleanly.

### `docs/` — the detailed reference material

- **`mqtt-protocol.md`** — full topic/payload spec, the back-timestamp
  formula, `timestamp_source` semantics, and the wall-clock/NTP caveats.
- **`wifi-setup.md`** — scripted and manual (`nmcli`) AP + uplink setup,
  the laptop-ICS wired backup, NTP/clock accuracy, the legacy
  `hostapd`+`dnsmasq` flow for older OS versions, and notes on the
  unsupported AIC8800D80 USB adapter.
- **`startup-and-shutdown.md`** — starting and stopping the stack.
- **`implementation-plan.md`** — the original design rationale.

## Setup

### 1. Dev machine (no Pi, no AP, no hardware needed)

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps        # all three services should show "Up"
docker compose logs -f   # watch mosquitto / ingest / api start up
```

This is enough to develop and test the whole ingest → SQLite → API
pipeline end to end using the simulator below.

### 2. Try it with a simulated node

```bash
pip install paho-mqtt
python scripts/simulate_node.py --host localhost --node-id sim-01 --batch-size 5
```

Watch it land:

```bash
docker compose logs ingest         # one INFO line per batch ingested
sqlite3 data/sqlite/aether.db "select * from readings order by id desc limit 5;"
curl localhost:8000/nodes
curl localhost:8000/nodes/sim-01/readings
```

Use `--realistic` to sleep `interval_ms` between simulated reads and
reconnect per batch like the real firmware does — this is the mode to use
when you want to sanity-check the back-timestamp math or ingest's
reconnect handling under realistic conditions, rather than a fast
smoke-test burst.

### 3. Browse the API

Open [http://localhost:8000/docs](http://localhost:8000/docs) for
interactive Swagger docs — every endpoint, its parameters, and example
responses, generated straight from the code.

### 4. Deploying to a real Raspberry Pi

1. Flash Raspberry Pi OS Lite 64-bit, boot it, SSH in.
2. Set up the AP and uplink: read [docs/wifi-setup.md](docs/wifi-setup.md),
   `cp scripts/wifi.conf.example scripts/wifi.conf`, fill in the SSIDs and
   passwords, then run `sudo scripts/wifi-setup.sh apply`. This is a
   one-time, host-level step — it is not part of `docker compose` and does
   not run in a container.
3. Install Docker + Docker Compose on the Pi.
4. Clone this repo onto the Pi, `cp .env.example .env`, adjust
   `AETHER_DATA_DIR` if you want data on a mounted USB drive instead of
   the SD card, then `docker compose up -d`.
5. Point a real node's `secrets.h` (see
   [aether-node.md](to_move/aether-node.md#includesecretsh--gitignored-per-device-secrets))
   at the Pi's AP IP (default `192.168.77.1` from `wifi.conf.example`).
6. Confirm real readings arrive: `docker compose logs ingest`, then query
   `/nodes` and `/nodes/{node_id}/readings` and sanity-check the
   back-calculated timestamps against when you know the node actually
   took those readings.

## MQTT protocol

Nodes publish to `sensors/<node_id>/data`; `ingest` subscribes to
`sensors/+/data`. Forward-compatible payload shape:

```json
{"interval_ms": 60000, "readings": [{"temperature_c": 21.43}, {"temperature_c": 21.5}]}
```

`ingest` back-calculates each reading's timestamp from its own receipt
time and the declared `interval_ms` (`reading_ts[i] = received_ts - (N -
1 - i) * interval_ms`), since the nodes have no RTC. If `interval_ms` is
absent (current firmware), every reading in the batch gets `received_ts`
directly and is marked `timestamp_source: "receipt_only"` instead of
`"device_interval"`, so API consumers can tell the two precision levels
apart. Full details, including the WiFi/MQTT-connect latency this doesn't
account for and the Pi's own clock-accuracy dependency, are in
[docs/mqtt-protocol.md](docs/mqtt-protocol.md).

## Database schema

```sql
nodes(node_id PK, first_seen, last_seen, label, node_type)
readings(id PK, node_id FK, reading_ts, received_ts, timestamp_source, batch_seq, data JSON)
```

`data` is stored as a JSON blob rather than one column per sensor field,
which is what lets one schema handle both a single-temperature node today
and a temp+humidity+pressure node later without a migration. Indexed on
`(node_id, reading_ts)` for the `/readings` time-range queries and on
`received_ts` for anything that needs ingest-order.

## Configuration reference (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `AETHER_DATA_DIR` | `./data` | Host path for SQLite + mosquitto persistence — repoint at a mounted USB drive without touching `docker-compose.yml` |
| `MQTT_HOST` / `MQTT_PORT` | `mosquitto` / `1883` | Broker address `ingest` connects to (internal Docker network name) |
| `MQTT_TOPIC_FILTER` | `sensors/+/data` | Subscription filter |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | unset | Only needed if you turn off `allow_anonymous` in `mosquitto.conf` |
| `CORS_ALLOW_ORIGINS` | `*` | Comma-separated allowed origins for the API — lock down before public exposure |
| `LOG_LEVEL` | `INFO` | Applies to both `ingest` and `api` |

All three services log via Docker's `local` driver capped at `5m ×3`
files (~45MB ceiling total) to protect the SD card from unbounded log
growth.

## Known limitations

- **No de-duplication** for redelivered MQTT messages (e.g. a QoS 1
  redelivery after a reconnect) — a redelivered batch is ingested again as
  new rows.
- **Back-timestamping doesn't account for connect latency** — the time
  between a node's last sensor read and its MQTT message actually arriving
  (WiFi connect + MQTT connect + publish) is unknown and variable per
  cycle; see [docs/mqtt-protocol.md](docs/mqtt-protocol.md) for the exact
  formula and its assumptions.
- **Pi wall-clock accuracy isn't guaranteed** — if the Pi is running its
  own AP with no other uplink, it has no path to NTP. Ethernet-uplink-
  while-AP is the recommended fix (separate physical interfaces, no
  conflict); manual `timedatectl set-time` is the offline fallback. See
  [docs/wifi-setup.md](docs/wifi-setup.md#ntp--wall-clock-accuracy).
- **`CORS_ALLOW_ORIGINS` defaults to `*`** — fine for local dev, should be
  narrowed before the API is reachable from anywhere untrusted.
- **No "edit node label" feature yet** — the API is read-only by design
  (`ingest` is the sole writer); a future admin feature for renaming/
  labeling nodes should go through `ingest` or a small dedicated admin
  path rather than being bolted onto the query API.
