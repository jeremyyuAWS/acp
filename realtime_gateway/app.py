from __future__ import annotations

from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException, Request
from api.realtime_events import owner_scope
from api.realtime_stream import event_stream_response
from .auth import AuthenticationError, verify_token
from .config import Settings
from .store import RedisEventStore


def create_app(
    *, settings: Settings | None = None, store: RedisEventStore | None = None,
    snapshot_provider=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if store is None:
            import redis.asyncio as redis
            app.state.store = RedisEventStore(redis.from_url(settings.redis_url, decode_responses=True))
        else:
            app.state.store = store
        try:
            yield
        finally:
            await app.state.store.close()

    app = FastAPI(title="ACP Realtime Operations Gateway", version="1", lifespan=lifespan)

    def authenticated_scope(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "bearer token required")
        try:
            return owner_scope(verify_token(authorization[7:], settings.auth_secret))
        except AuthenticationError as exc:
            raise HTTPException(401, str(exc)) from exc

    @app.get("/healthz")
    async def healthz():
        try:
            await app.state.store.redis.ping()
        except Exception as exc:
            raise HTTPException(503, "redis unavailable") from exc
        return {"status": "ok", "namespace": "acp:realtime:v1:owner"}

    @app.get("/v1/events")
    async def events(
        request: Request,
        authorization: str | None = Header(default=None),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ):
        scope = authenticated_scope(authorization)
        return event_stream_response(
            request, scope=scope, store=app.state.store, block_ms=settings.block_ms,
            last_event_id=last_event_id, snapshot_provider=snapshot_provider,
        )

    return app
