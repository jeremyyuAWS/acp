"""Route modules for the acp control plane.

Each module exposes a `router` (fastapi.APIRouter). app.py includes them all.
Shared state and helpers live in api/core.py.
"""
from . import system, rubric, scans, drive, hitl, ai, disposition, campaigns

ROUTERS = [system.router, rubric.router, scans.router, drive.router, hitl.router, ai.router,
          disposition.router, campaigns.router]
