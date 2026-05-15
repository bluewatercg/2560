from __future__ import annotations

import logging
import os
from typing import Optional

import redis

logger = logging.getLogger(__name__)

_client: Optional[redis.Redis] = None


def _build_client() -> Optional[redis.Redis]:
    host = os.getenv("REDIS_HOST") or "localhost"
    port = int(os.getenv("REDIS_PORT", "6379"))
    db = int(os.getenv("REDIS_DB", "0"))
    password = os.getenv("REDIS_PASSWORD") or None

    try:
        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_timeout=5,
            socket_connect_timeout=3,
            decode_responses=True,
        )
        client.ping()
        return client
    except (redis.ConnectionError, redis.TimeoutError) as exc:
        logger.warning("[redis] connection failed: %s", exc)
        return None


def get_redis_client() -> Optional[redis.Redis]:
    """Return a singleton Redis client, or None if connection fails.

    If the cached client is stale (ping fails), it is reset and rebuilt
    on the next call.
    """
    global _client
    if _client is not None:
        try:
            _client.ping()
            return _client
        except (redis.ConnectionError, redis.TimeoutError):
            logger.warning("[redis] cached client stale, resetting")
            try:
                _client.close()
            except Exception:
                pass
            _client = None
    _client = _build_client()
    return _client


def ping_redis(client: Optional[redis.Redis]) -> bool:
    """Check if a Redis client is alive. Returns False if client is None."""
    if client is None:
        return False
    try:
        return client.ping()
    except (redis.ConnectionError, redis.TimeoutError):
        return False


def reset_client() -> None:
    """Reset the singleton (useful for testing or reconnection)."""
    global _client
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
