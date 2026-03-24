import redis.asyncio as redis

from app.config.settings import settings

_redis: redis.Redis | None = None


async def init_redis() -> None:
    """Called on app startup."""
    global _redis
    url = f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}"
    _redis = redis.from_url(
        url,
        password=settings.redis_password or None,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis() -> redis.Redis:
    if _redis is None:
        await init_redis()
    assert _redis is not None
    return _redis
