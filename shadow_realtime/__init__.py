"""Default-off realtime shadow-system experiments.

Nothing in the production application imports this package.  Operators must invoke the
collector or harness explicitly and opt in with SHADOW_REALTIME_ENABLED=1.
"""

from .contract import EventEnvelope

__all__ = ["EventEnvelope"]
