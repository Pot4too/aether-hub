from typing import Any

from pydantic import BaseModel


class NodeOut(BaseModel):
    node_id: str
    first_seen: str
    last_seen: str
    label: str | None = None
    node_type: str | None = None


class ReadingOut(BaseModel):
    id: int
    reading_ts: str
    received_ts: str
    timestamp_source: str
    data: dict[str, Any]


class NodeDetailOut(NodeOut):
    latest_reading: ReadingOut | None = None


class ReadingsPage(BaseModel):
    items: list[ReadingOut]
    limit: int
    offset: int
    has_more: bool
