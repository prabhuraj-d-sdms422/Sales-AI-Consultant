import time
from collections import defaultdict

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_RATE: dict[str, list[float]] = defaultdict(list)
_WINDOW_SEC = 60
_MAX_REQ = 120


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/health"):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - _WINDOW_SEC
        _RATE[client] = [t for t in _RATE[client] if t > window_start]
        if len(_RATE[client]) >= _MAX_REQ:
            return Response("Rate limit exceeded", status_code=429)
        _RATE[client].append(now)
        return await call_next(request)
