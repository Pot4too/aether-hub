#!/usr/bin/env python3
"""Firmware-mimicking MQTT publisher, for testing the ingest pipeline without hardware.

Publishes to sensors/<node_id>/data using the forward-compatible payload shape:
    {"interval_ms": <int>, "readings": [{"temperature_c": <float>}, ...]}

Two modes:
  - default (fast): sends batches back-to-back for quick smoke-testing.
  - --realistic: sleeps interval_ms between simulated reads and connects/
    disconnects per batch like the real firmware, to validate the
    back-timestamp math and ingest's reconnect handling.
"""

from __future__ import annotations

import argparse
import json
import random
import time

import paho.mqtt.client as mqtt

TOPIC_TEMPLATE = "sensors/{node_id}/data"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--node-id", default="sim-01")
    parser.add_argument("--interval-ms", type=int, default=1000)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--count", type=int, default=1, help="number of batches to publish")
    parser.add_argument(
        "--realistic",
        action="store_true",
        help="sleep interval_ms between reads and reconnect per batch, like the real firmware",
    )
    return parser.parse_args()


def make_walker(start: float = 21.0):
    value = start

    def step() -> float:
        nonlocal value
        value += random.uniform(-0.3, 0.3)
        return round(value, 2)

    return step


def publish_batch(client: mqtt.Client, node_id: str, interval_ms: int, readings: list[dict]) -> None:
    topic = TOPIC_TEMPLATE.format(node_id=node_id)
    payload = json.dumps({"interval_ms": interval_ms, "readings": readings})
    info = client.publish(topic, payload, qos=1)
    info.wait_for_publish()
    print(f"published batch: node={node_id} count={len(readings)} interval_ms={interval_ms}")


def main() -> None:
    args = parse_args()
    walker = make_walker()

    for batch_num in range(args.count):
        readings = [{"temperature_c": walker()} for _ in range(args.batch_size)]

        if args.realistic:
            # Mimic real firmware: sleep between reads before this batch was "collected",
            # then connect, publish, and disconnect for this cycle only.
            if batch_num > 0:
                time.sleep(args.interval_ms * args.batch_size / 1000)
            client = mqtt.Client(client_id=f"{args.node_id}-sim-{batch_num}")
            client.connect(args.host, args.port)
            client.loop_start()
            publish_batch(client, args.node_id, args.interval_ms, readings)
            client.loop_stop()
            client.disconnect()
        else:
            if batch_num == 0:
                client = mqtt.Client(client_id=f"{args.node_id}-sim")
                client.connect(args.host, args.port)
                client.loop_start()
            publish_batch(client, args.node_id, args.interval_ms, readings)

    if not args.realistic:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
