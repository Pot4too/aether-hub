import logging
import signal

import paho.mqtt.client as mqtt
from aether_shared.db import get_connection, init_db

from app.config import config
from app.ingest import process_message
from app.validate import parse_message

logging.basicConfig(
    level=config.LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("ingest.main")


def on_connect(client: mqtt.Client, userdata, flags, rc):
    if rc != 0:
        logger.warning("MQTT connect failed with rc=%s", rc)
        return
    logger.info("connected to MQTT broker, subscribing to %s", config.MQTT_TOPIC_FILTER)
    client.subscribe(config.MQTT_TOPIC_FILTER)


def on_disconnect(client: mqtt.Client, userdata, rc):
    logger.warning("disconnected from MQTT broker (rc=%s), will auto-reconnect", rc)


def make_on_message(conn):
    def on_message(client: mqtt.Client, userdata, message: mqtt.MQTTMessage):
        msg = parse_message(message.topic, message.payload)
        if msg is None:
            return
        try:
            process_message(conn, msg)
        except Exception:
            logger.exception("failed to process message for node on topic %r", message.topic)

    return on_message


def main() -> None:
    logger.info("initializing database at %s", config.DB_PATH)
    init_db(config.DB_PATH)

    conn = get_connection(config.DB_PATH)

    client = mqtt.Client()
    if config.MQTT_USERNAME:
        client.username_pw_set(config.MQTT_USERNAME, config.MQTT_PASSWORD)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = make_on_message(conn)
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    logger.info("connecting to MQTT broker at %s:%s", config.MQTT_HOST, config.MQTT_PORT)
    client.connect(config.MQTT_HOST, config.MQTT_PORT)

    # `docker stop` sends SIGTERM. Python as PID 1 ignores it by default, which
    # means a 10s wait and a SIGKILL. Handle it so shutdown is prompt and clean.
    def shutdown(signum, frame):
        logger.info("received signal %s, shutting down", signum)
        client.disconnect()  # makes loop_forever() return

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    client.loop_forever()
    conn.close()
    logger.info("stopped cleanly")


if __name__ == "__main__":
    main()
