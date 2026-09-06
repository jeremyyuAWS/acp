from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.realtime_events import MAX_REPLAY_EVENTS, owner_scope, parse_last_event_id
from .auth import AuthenticationError, verify_token
from .config import Settings
from .store import RedisEventStore


SnapshotProvider = Callable[[str], Awaitable[Mapping]]


def _control(kind: str, payload: Mapping) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(dict(payload), separators=(',', ':'))}\n\n".encode()


def create_app(
    *, settings: Settings | None = None, store: RedisEventStore | None = None,
    snapshot_provider: SnapshotProvider | None = None,
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
        invalid_reason = None
        if last_event_id:
            try:
                parse_last_event_id(last_event_id)
                status = await app.state.store.cursor_status(scope, last_event_id)
                if status != "valid":
                    invalid_reason = status
            except ValueError:
                invalid_reason = "malformed"

        async def body():
            cursor = last_event_id
            if not cursor or invalid_reason:
                if invalid_reason:
                    yield _control("reconciliation-required", {"reason": invalid_reason})
                if snapshot_provider is not None:
                    yield _control("snapshot", await snapshot_provider(scope))
                cursor = "$"
            else:
                rows = await app.state.store.replay(scope, cursor, limit=MAX_REPLAY_EVENTS)
                for row_id, event in rows:
                    cursor = row_id
                    yield event.to_sse().encode()
                if len(rows) == MAX_REPLAY_EVENTS:
                    yield _control("reconciliation-required", {"reason": "replay-limit"})
                    return
            listener = app.state.store.listen(scope, cursor, block_ms=settings.block_ms)
            try:
                while not await request.is_disconnected():
                    try:
                        _row_id, event = await asyncio.wait_for(anext(listener), timeout=15)
                    except StopAsyncIteration:
                        return
                    except TimeoutError:
                        yield b": keepalive\n\n"
                        continue
                    yield event.to_sse().encode()
            finally:
                with suppress(Exception):
                    await listener.aclose()

        return StreamingResponse(
            body(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
