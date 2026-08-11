"""The SPA entry HTML must revalidate every load; content-hashed /assets/* may cache forever.

Plain StaticFiles sets an ETag but NO Cache-Control, so a browser is free to serve a stale
index.html without re-checking — and keep loading the OLD hashed JS bundle named in that cached
HTML after a deploy. On 2026-08-10 that stranded a signed-in Microsoft user on pre-fix JS that
never sent the X-Auth-Provider header, so every request 401'd ("session expired") against a backend
that was, by then, perfectly able to authenticate them. Only a manual hard-refresh cleared it.

SpaStaticFiles sets `no-cache` on HTML (revalidate via ETag — an unchanged fetch is a cheap 304) and
`immutable` on /assets/* (a new build gives a new filename, never mutating an old one). These pin it.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from app import SpaStaticFiles  # noqa: E402


def _client(root: Path) -> TestClient:
    app = FastAPI()
    app.mount("/", SpaStaticFiles(directory=str(root), html=True), name="spa")
    return TestClient(app)


def test_index_html_revalidates(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><html></html>")
    r = _client(tmp_path).get("/index.html")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_root_spa_fallback_html_revalidates(tmp_path):
    # html=True serves index.html for the directory root — the actual entry a browser loads.
    (tmp_path / "index.html").write_text("<!doctype html><html></html>")
    r = _client(tmp_path).get("/")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"


def test_hashed_asset_is_immutable(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    r = _client(tmp_path).get("/assets/index-abc123.js")
    assert r.status_code == 200
    cc = r.headers["cache-control"]
    assert "immutable" in cc and "max-age=31536000" in cc
