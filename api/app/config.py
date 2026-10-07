import os


class Config:
    DB_PATH: str = os.environ.get("DB_PATH", "/data/aether.db")
    CORS_ALLOW_ORIGINS: str = os.environ.get("CORS_ALLOW_ORIGINS", "*")
    LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO")


config = Config()
