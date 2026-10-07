import json
import logging
from dataclasses import dataclass

logger = logging.getLogger("ingest.validate")

TOPIC_PREFIX = "sensors"
TOPIC_SUFFIX = "data"


@dataclass
class ParsedMessage:
    node_id: str
    interval_ms: int | None
    readings: list[dict]


def parse_topic(topic: str) -> str | None:
    """Extract node_id from a `sensors/<node_id>/data` topic, or None if malformed."""
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != TOPIC_PREFIX or parts[2] != TOPIC_SUFFIX:
        return None
    node_id = parts[1]
    if not node_id:
        return None
    return node_id


def parse_message(topic: str, payload: bytes) -> ParsedMessage | None:
    """Parse and validate one MQTT message. Returns None (and logs one WARNING)
    on any failure — never raises, so the caller's MQTT callback stays alive.
    """
    node_id = parse_topic(topic)
    if node_id is None:
        logger.warning("dropping message: malformed topic %r", topic)
        return None

    try:
        body = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning("dropping message: invalid JSON on topic %r", topic)
        return None

    if not isinstance(body, dict):
        logger.warning("dropping message: payload is not a JSON object (node=%s)", node_id)
        return None

    readings = body.get("readings")
    if not isinstance(readings, list) or len(readings) == 0:
        logger.warning("dropping message: 'readings' is not a non-empty list (node=%s)", node_id)
        return None

    if not all(isinstance(r, dict) for r in readings):
        logger.warning("dropping message: 'readings' contains non-object entries (node=%s)", node_id)
        return None

    interval_ms = body.get("interval_ms")
    if interval_ms is not None:
        if not isinstance(interval_ms, int) or isinstance(interval_ms, bool) or interval_ms <= 0:
            logger.warning("dropping message: invalid 'interval_ms' (node=%s)", node_id)
            return None

    return ParsedMessage(node_id=node_id, interval_ms=interval_ms, readings=readings)
