"""Low-frequency Azure operations collector for the default-off shadow stream."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Callable, Iterable, Mapping
from uuid import uuid4

from .contract import EventEnvelope
from .stream import ShadowStream, enabled


@dataclass(frozen=True)
class CollectorConfig:
    redis_url: str
    subscription_id: str
    tenant_id: str
    resource_ids: tuple[str, ...]
    metric_names: tuple[str, ...] = ("Requests", "CpuUsage", "MemoryWorkingSetBytes")
    interval_seconds: int = 60
    max_events: int = 50_000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "CollectorConfig":
        env = os.environ if environ is None else environ
        if not enabled(dict(env)):
            raise RuntimeError("collector disabled; set SHADOW_REALTIME_ENABLED=1 to opt in")
        required = {
            "redis_url": env.get("SHADOW_REALTIME_REDIS_URL", ""),
            "subscription_id": env.get("SHADOW_REALTIME_AZURE_SUBSCRIPTION_ID", ""),
            "tenant_id": env.get("SHADOW_REALTIME_TENANT_ID", ""),
            "resource_ids": env.get("SHADOW_REALTIME_AZURE_RESOURCE_IDS", ""),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("missing shadow collector configuration: " + ", ".join(missing))
        interval = int(env.get("SHADOW_REALTIME_SAMPLE_INTERVAL_SECONDS", "60"))
        if interval < 30:
            raise RuntimeError("shadow infrastructure sampling interval must be at least 30 seconds")
        return cls(
            redis_url=required["redis_url"],
            subscription_id=required["subscription_id"],
            tenant_id=required["tenant_id"],
            resource_ids=tuple(v.strip() for v in required["resource_ids"].split(",") if v.strip()),
            metric_names=tuple(v.strip() for v in env.get("SHADOW_REALTIME_AZURE_METRICS", "Requests,CpuUsage,MemoryWorkingSetBytes").split(",") if v.strip()),
            interval_seconds=interval,
            max_events=int(env.get("SHADOW_REALTIME_MAX_EVENTS", "50000")),
        )


class OperationsCollector:
    def __init__(self, config: CollectorConfig, stream: ShadowStream, sampler: Callable[[str, tuple[str, ...]], Mapping]):
        self.config = config
        self.stream = stream
        self.sampler = sampler

    def collect_once(self) -> list[str]:
        emitted = []
        correlation = str(uuid4())
        for resource_id in self.config.resource_ids:
            payload = {"resource_id": resource_id, "metrics": dict(self.sampler(resource_id, self.config.metric_names))}
            event = EventEnvelope.new(
                event_type="infrastructure.sample",
                tenant_id=self.config.tenant_id,
                correlation_id=correlation,
                source="shadow.azure.operations-collector",
                priority="low",
                sequence=self.stream.next_sequence(self.config.tenant_id),
                payload=payload,
            )
            result = self.stream.publish(event, coalesce_key=resource_id)
            if result.stream_id:
                emitted.append(result.stream_id)
        return emitted

    def run(self) -> None:
        while True:
            self.collect_once()
            time.sleep(self.config.interval_seconds)


def azure_sampler(subscription_id: str):
    """Build the SDK sampler lazily so disabled installs require no Azure credentials."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.monitor import MonitorManagementClient

    client = MonitorManagementClient(DefaultAzureCredential(), subscription_id)

    def sample(resource_id: str, names: tuple[str, ...]) -> Mapping:
        response = client.metrics.list(resource_id, metricnames=",".join(names), timespan="PT5M", interval="PT1M")
        values = {}
        for metric in response.value:
            points = [point for series in metric.timeseries for point in series.data]
            latest = points[-1] if points else None
            values[metric.name.value] = {
                key: getattr(latest, key, None) if latest else None
                for key in ("average", "minimum", "maximum", "total", "count")
            }
        return values

    return sample


def main() -> int:
    try:
        config = CollectorConfig.from_env()
    except RuntimeError as exc:
        print(json.dumps({"status": "disabled", "reason": str(exc)}))
        return 2
    import redis

    client = redis.Redis.from_url(config.redis_url, decode_responses=False)
    collector = OperationsCollector(config, ShadowStream(client, max_events=config.max_events), azure_sampler(config.subscription_id))
    collector.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
