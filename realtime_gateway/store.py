"""Compatibility import for the standalone gateway package."""

from api.realtime_event_store import RedisEventStore, _with_stream_id

__all__ = ["RedisEventStore", "_with_stream_id"]
