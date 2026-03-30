import pytest

import app.guardrails  # noqa: F401  # hub registry path before guardrails.hub
import app.db.redis_client as redis_client


class _AsyncFakeRedis:
    """Minimal async Redis shim over fakeredis for tests."""

    def __init__(self):
        import fakeredis

        self._r = fakeredis.FakeRedis(decode_responses=True)

    async def get(self, key: str):
        return self._r.get(key)

    async def setex(self, key: str, time: int, value: str):
        return self._r.setex(key, time, value)


@pytest.fixture(autouse=True)
def _patch_redis(monkeypatch):
    fake = _AsyncFakeRedis()

    async def init_redis():
        redis_client._redis = fake  # noqa: SLF001

    async def get_redis():
        return fake

    monkeypatch.setattr(redis_client, "init_redis", init_redis)
    monkeypatch.setattr(redis_client, "get_redis", get_redis)
