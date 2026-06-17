"""
Redis cache wrapper. Falls back to a no-op if Redis is disabled or unreachable.
Used for: embedding vectors (TTL 1h), picklist data (TTL 24h).
"""
import json
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

_client = None
_enabled = False


def _get_client():
    global _client, _enabled
    if _client is not None:
        return _client

    from src.config import Config
    if not Config.REDIS_ENABLED:
        return None

    try:
        import redis
        _client = redis.Redis(
            host=Config.REDIS_HOST,
            port=Config.REDIS_PORT,
            password=Config.REDIS_AUTH or None,
            ssl=Config.REDIS_SSL,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )
        _client.ping()
        _enabled = True
        log.info("Redis connected at %s:%s", Config.REDIS_HOST, Config.REDIS_PORT)
    except Exception as e:
        log.warning("Redis unavailable (%s) — caching disabled", e)
        _client = None
    return _client


def get(key: str) -> Optional[Any]:
    client = _get_client()
    if not client:
        return None
    try:
        raw = client.get(key)
        return json.loads(raw) if raw is not None else None
    except Exception as e:
        log.debug("Cache get error for %s: %s", key, e)
        return None


def set(key: str, value: Any, ttl: int = 3600) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.setex(key, ttl, json.dumps(value))
        return True
    except Exception as e:
        log.debug("Cache set error for %s: %s", key, e)
        return False


def delete(key: str) -> bool:
    client = _get_client()
    if not client:
        return False
    try:
        client.delete(key)
        return True
    except Exception as e:
        log.debug("Cache delete error for %s: %s", key, e)
        return False


def is_available() -> bool:
    return _get_client() is not None
