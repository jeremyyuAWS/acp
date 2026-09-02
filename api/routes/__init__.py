"""Route modules for the acp control plane.

Each module exposes a `router` (fastapi.APIRouter). app.py includes them all.
Shared state and helpers live in api/core.py.
"""
from . import system, rubric, scans, drive, hitl, ai, disposition, campaigns, capability, sharepoint, control, assess, scope, analytics, public, discovery, openapi_health, workspace, content_workspaces, acr

ROUTERS = [system.router, rubric.router, scans.router, drive.router, hitl.router, ai.router,
          disposition.router, campaigns.router, capability.router, sharepoint.router,
          control.router, assess.router, scope.router, analytics.router, public.router,
          discovery.router, openapi_health.router, workspace.router, content_workspaces.router,
          acr.router]
