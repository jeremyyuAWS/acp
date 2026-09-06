from __future__ import annotations

from dataclasses import dataclass
import os


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Explicit settings for the isolated service; no ACP manifest enables it."""

    enabled: bool = False
    redis_url: str = "redis://127.0.0.1:6379/0"
    auth_secret: str = ""
    block_ms: int = 1_000

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            enabled=_enabled(os.getenv("ACP_REALTIME_V1_ENABLED")),
            redis_url=os.getenv("ACP_REALTIME_V1_REDIS_URL", cls.redis_url),
            auth_secret=os.getenv("ACP_REALTIME_V1_AUTH_SECRET", ""),
            block_ms=int(os.getenv("ACP_REALTIME_V1_BLOCK_MS", str(cls.block_ms))),
        )

    def validate(self) -> None:
        if not self.enabled:
            raise RuntimeError("realtime v1 is disabled")
        if len(self.auth_secret) < 32:
            raise RuntimeError("ACP_REALTIME_V1_AUTH_SECRET must be at least 32 characters")
        if self.block_ms < 1:
            raise RuntimeError("ACP_REALTIME_V1_BLOCK_MS must be positive")
