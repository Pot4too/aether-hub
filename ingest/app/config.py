import os


class Config:
    MQTT_HOST: str = os.environ.get("MQTT_HOST", "mosquitto")
    MQTT_PORT: int = int(os.environ.get("MQTT_PORT", "1883"))
    MQTT_TOPIC_FILTER: str = os.environ.get("MQTT_TOPIC_FILTER", "sensors/+/data")
    MQTT_USERNAME: str | None = os.environ.get("MQTT_USERNAME") or None
    MQTT_PASSWORD: str | None = os.environ.get("MQTT_PASSWORD") or None
    DB_PATH: str = os.environ.get("DB_PATH", "/data/aether.db")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


config = Config()
