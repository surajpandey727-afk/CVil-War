"""Cross-process progress event bus over Redis pub/sub.

The worker runs in a separate process from the API, so the in-process
``ConnectionManager.broadcast`` could never reach connected clients. The worker
publishes per-user progress events here; each API process subscribes and fans them out
to that user's WebSocket connections (see ``api/websocket/subscriber.py``).
"""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

CHANNEL_PREFIX = "ws:user:"


def user_channel(user_id: str) -> str:
    """Redis pub/sub channel carrying a single user's real-time events."""
    return f"{CHANNEL_PREFIX}{user_id}"


async def publish_progress(redis: Redis, user_id: str, event: dict[str, Any]) -> None:
    """Publish a progress event to the owning user's channel."""
    await redis.publish(user_channel(user_id), json.dumps(event))
