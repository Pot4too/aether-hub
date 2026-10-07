# MQTT protocol

## Topics

`sensors/<node_id>/data` — one topic per node. A node monitors one thing
(e.g. "the kitchen temperature sensor") but its payload can carry multiple
fields (e.g. a future BME280 node publishing temperature, humidity, and
pressure together). `ingest` subscribes to `sensors/+/data`.

## Payload

Current firmware ([aether-node.md](../to_move/aether-node.md)) publishes, with no
batch metadata:

```json
{"readings": [{"temperature_c": 21.43}, {"temperature_c": 21.5}]}
```

The forward-compatible shape (target for firmware to adopt) adds
`interval_ms` — the delay between reads in the batch:

```json
{"interval_ms": 60000, "readings": [{"temperature_c": 21.43}, {"temperature_c": 21.5}]}
```

There is no separate count field — `len(readings)` is the count.

## Back-timestamp logic

The ESP32 nodes have no RTC, so `ingest` derives each reading's timestamp
from its own receipt time. Given `N = len(readings)` and `received_ts` =
ingest's wall-clock time when the MQTT message arrives:

```
reading_ts[i] = received_ts - (N - 1 - i) * interval_ms
```

This treats `received_ts` as a stand-in for "the time the last reading in
the batch was taken." **It does not account for the WiFi-connect +
MQTT-connect + publish latency** between the last read and the message
arriving at the broker — that latency is unknown and variable per cycle.
For sub-second precision needs, this is a known limitation, not a bug.

If `interval_ms` is absent (old firmware payload), every reading in the
batch is assigned `received_ts` directly, and `timestamp_source` is set to
`receipt_only` instead of `device_interval`, so API consumers can tell the
two precision levels apart.

## Wall-clock dependency

Back-timestamping — and `received_ts` itself — is only as accurate as the
Pi's own system clock. Because the Pi may run its own WiFi access point
(see [wifi-setup.md](wifi-setup.md)) rather than joining an existing
network, its path to NTP is not guaranteed:

- If the Pi has a wired Ethernet uplink while running WiFi as an AP (a
  standard combination, since they're separate physical interfaces), NTP
  should work normally — this is the recommended setup.
- If the Pi is genuinely offline, its clock will drift from real time with
  no correction. Set it manually once via `timedatectl set-time` before a
  fully-offline deployment, and expect timestamps to accumulate drift
  afterward.

## Known gaps

- No de-duplication for redelivered MQTT messages (e.g. after a QoS 1
  reconnect). A redelivered batch is ingested again as new rows. Flagged
  as a known gap, not addressed in this version.
