"""Azure Container Apps implementation of the capacity application boundary.

Azure imports stay lazy so local development and non-Azure deployments do not need the
management-plane packages merely to import the API.  A GET snapshot supplies both the location
required by the SDK model and the ETag used to prevent overwriting a concurrent scale edit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from capacity_policy import AppPolicy


@dataclass(frozen=True)
class _Snapshot:
    location: str
    etag: str


def _sdk_models():
    from azure.mgmt.appcontainers import models
    return models


class AzureCapacityGateway:
    """Apply complete scale blocks through Azure's JSON Merge Patch operation."""

    def __init__(self, client: Any, resource_group: str, *, allowed_apps: tuple[str, ...]):
        self._client = client
        self._resource_group = resource_group
        self._allowed_apps = frozenset(allowed_apps)
        self._snapshots: dict[str, _Snapshot] = {}

    def _resolve_app(self, app: str) -> str:
        """Resolve one logical policy name without ever broadening the deployment allowlist."""
        if app in self._allowed_apps:
            return app
        staging_name = f"{app}-staging"
        if staging_name in self._allowed_apps:
            return staging_name
        raise RuntimeError("capacity app is outside the configured deployment fleet")

    def read_scale(self, app: str) -> dict | None:
        target_app = self._resolve_app(app)
        def capture(response, model, _headers):
            return model, response.http_response.headers.get("ETag")

        model, etag = self._client.container_apps.get(
            self._resource_group, target_app, cls=capture)
        location = getattr(model, "location", None)
        if location and etag:
            self._snapshots[target_app] = _Snapshot(str(location), str(etag))
        else:
            self._snapshots.pop(target_app, None)

        properties = getattr(model, "properties", None)
        template = getattr(properties, "template", None)
        scale = getattr(template, "scale", None)
        if scale is None:
            return None
        return {
            "min_replicas": getattr(scale, "min_replicas", None),
            "max_replicas": getattr(scale, "max_replicas", None),
            "rules": [self._observed_rule(rule) for rule in (getattr(scale, "rules", None) or [])],
        }

    @staticmethod
    def _observed_rule(rule: Any) -> dict:
        custom = getattr(rule, "custom", None)
        if custom is not None:
            return {"name": getattr(rule, "name", ""),
                    "type": getattr(custom, "type", ""),
                    "metadata": dict(getattr(custom, "metadata", None) or {})}
        for attribute, kind in (("azure_queue", "azure_queue"), ("http", "http"),
                                ("tcp", "tcp")):
            value = getattr(rule, attribute, None)
            if value is not None:
                return {"name": getattr(rule, "name", ""), "type": kind,
                        "metadata": dict(getattr(value, "metadata", None) or {})}
        return {"name": getattr(rule, "name", ""), "type": "unknown", "metadata": {}}

    def apply_scale(self, policy: AppPolicy) -> None:
        target_app = self._resolve_app(policy.app)
        snapshot = self._snapshots.get(target_app)
        if snapshot is None or not snapshot.location or not snapshot.etag:
            raise RuntimeError("capacity snapshot with location and ETag is required before apply")

        models = _sdk_models()
        rules = []
        for rule in policy.rules:
            auth = [models.ScaleRuleAuth(trigger_parameter=parameter, secret_ref=secret)
                    for parameter, secret in (rule.auth or {}).items()]
            custom = models.CustomScaleRule(type=rule.type, metadata=dict(rule.metadata),
                                            auth=auth or None)
            rules.append(models.ScaleRule(name=rule.name, custom=custom))
        envelope = models.ContainerApp(
            location=snapshot.location,
            template=models.Template(scale=models.Scale(
                min_replicas=policy.min_replicas,
                max_replicas=policy.max_replicas,
                rules=rules,
            )),
        )
        poller = self._client.container_apps.begin_update(
            self._resource_group, target_app, envelope,
            headers={"If-Match": snapshot.etag})
        poller.result()


def default_gateway(subscription_id: str, resource_group: str, *,
                    allowed_apps: tuple[str, ...]) -> AzureCapacityGateway:
    """Construct the managed-identity client only after the environment gate has passed."""
    from azure.identity import DefaultAzureCredential
    from azure.mgmt.appcontainers import ContainerAppsAPIClient
    return AzureCapacityGateway(
        ContainerAppsAPIClient(DefaultAzureCredential(), subscription_id), resource_group,
        allowed_apps=allowed_apps)
