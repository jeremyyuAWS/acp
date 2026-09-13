"""Readiness must answer even when ordinary synchronous request slots are occupied."""
import asyncio
import threading

import anyio
import httpx
from fastapi import FastAPI


def test_probe_does_not_wait_for_the_request_threadpool(monkeypatch):
    import core
    from routes import system

    class Store:
        def ping(self):
            return None

    monkeypatch.setattr(core, 'store', Store())
    app = FastAPI()
    app.include_router(system.router)

    async def exercise():
        limiter = anyio.to_thread.current_default_thread_limiter()
        old = limiter.total_tokens
        limiter.total_tokens = 1
        await limiter.acquire()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await asyncio.wait_for(client.get('/probe/readyz'), timeout=0.4)
                assert response.status_code == 200
                assert response.json()['checks']['db'] == 'ok'
        finally:
            limiter.release()
            limiter.total_tokens = old

    anyio.run(exercise)


def test_hung_probe_has_a_deadline_and_cannot_stack_database_checks(monkeypatch):
    import core
    from routes import system

    release = threading.Event()
    calls = []

    class Store:
        def ping(self):
            calls.append(1)
            release.wait(5)

    monkeypatch.setattr(core, 'store', Store())
    monkeypatch.setattr(system, '_PROBE_HTTP_TIMEOUT_S', 0.03, raising=False)
    app = FastAPI()
    app.include_router(system.router)

    async def exercise():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                response = await asyncio.wait_for(client.get('/probe/readyz'), timeout=0.4)
                assert response.status_code == 503
                assert response.json()['checks']['db'] == 'db_check_timeout'
                response = await client.get('/probe/readyz')
                assert response.status_code == 503
                assert response.json()['checks']['db'] == 'db_check_in_flight'
                assert calls == [1]
        finally:
            release.set()

    anyio.run(exercise)
