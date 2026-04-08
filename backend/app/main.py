from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RateLimitMiddleware
from app.api.routes import chat, conversation_viewer, health, session
from app.config.settings import settings
from app.db.redis_client import init_redis
from app.services.lead_delivery_service import end_session_and_maybe_deliver
from app.services.session_service import load_state, save_state

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


async def _sweep_inactive_sessions() -> None:
    """
    Safety net: end + deliver sessions that were abandoned.
    Uses SESSION_TIMEOUT_MINUTES. Runs forever in background.
    """
    while True:
        try:
            timeout_min = int(settings.session_timeout_minutes)
            cutoff = datetime.utcnow() - timedelta(minutes=timeout_min)

            redis = None
            from app.db.redis_client import get_redis  # local import to avoid startup ordering issues

            redis = await get_redis()
            async for key in redis.scan_iter(match="session:*", count=200):
                try:
                    session_id = str(key).split("session:", 1)[-1]
                    state = await load_state(session_id)
                    if not state:
                        continue
                    if bool(state.get("conversation_ended")) or bool(state.get("lead_delivered")):
                        continue
                    last_active = state.get("last_active") or ""
                    try:
                        last_dt = datetime.fromisoformat(str(last_active))
                    except Exception:
                        continue
                    if last_dt > cutoff:
                        continue

                    updated = await end_session_and_maybe_deliver(state, reason="inactive_sweep")
                    await save_state(session_id, updated)
                except Exception:
                    logger.exception("Inactive session sweep error for key=%s", key)
        except Exception:
            logger.exception("Inactive session sweep loop error")

        await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_redis()
    task = asyncio.create_task(_sweep_inactive_sessions())
    yield
    task.cancel()


app = FastAPI(
    title="Stark Digital AI Sales Consultant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(health.router)
app.include_router(session.router, prefix="/session")
app.include_router(chat.router, prefix="/chat")
app.include_router(conversation_viewer.router)
