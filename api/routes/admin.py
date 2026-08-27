"""Internal admin endpoint for programmatic DB access.

Protected by X-Admin-Key header matching the ACP_ADMIN_KEY env var.
The endpoint is a 404 when ACP_ADMIN_KEY is not set, so it is safe to
deploy everywhere — it only activates on containers where the key is
explicitly configured.
"""
from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import core

router = APIRouter()

_ADMIN_KEY = os.environ.get("ACP_ADMIN_KEY", "").strip()


def _check_key(request: Request) -> None:
    if not _ADMIN_KEY:
        raise HTTPException(404)
    provided = request.headers.get("X-Admin-Key", "")
    # constant-time compare to prevent timing attacks
    if not hmac.compare_digest(provided, _ADMIN_KEY):
        raise HTTPException(403, "invalid key")


class _SqlBody(BaseModel):
    sql: str
    params: list[Any] = []


@router.post("/internal/admin/sql")
async def admin_sql(body: _SqlBody, request: Request):
    """Run a SQL statement and return results. SELECT → rows list. DML → rowcount."""
    _check_key(request)
    try:
        with core.store._db.connect() as cur:
            core.store._db.execute(cur, body.sql, tuple(body.params))
            if cur.description:
                rows = core.store._db.fetchall(cur)
                return {"ok": True, "rows": rows, "count": len(rows)}
            return {"ok": True, "rowcount": cur.rowcount}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/internal/admin/status")
async def admin_status(request: Request):
    """Quick health check: confirms the key works and returns basic DB stats."""
    _check_key(request)
    try:
        with core.store._db.connect() as cur:
            core.store._db.execute(cur, "SELECT count(*) AS n FROM scan_runs")
            scans = (core.store._db.fetchone(cur) or {}).get("n", "?")
            core.store._db.execute(
                cur,
                "SELECT count(*) AS n FROM scan_runs WHERE owner_email IS NULL",
            )
            null_owners = (core.store._db.fetchone(cur) or {}).get("n", "?")
        return {"ok": True, "scan_runs": scans, "null_owner_runs": null_owners}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
