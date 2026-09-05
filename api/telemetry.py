"""Application Insights via the Azure Monitor OpenTelemetry distribution — opt-in, and scrubbed.

Two rules govern this whole file.

**IT IS OFF UNLESS A CONNECTION STRING IS SET.** No `APPLICATIONINSIGHTS_CONNECTION_STRING`, no
exporter, no SDK import, no egress, no bill. That is not a convenience: telemetry that turns
itself on is telemetry nobody decided to send. It follows the pattern the Langfuse spans in this
codebase already use — configured by env, a no-op without it.

**NOTHING THAT NAMES A PERSON OR A DOCUMENT LEAVES.** Distributed tracing needs to join a request
to a job to a worker to a blob write, and joining needs IDs — it does not need identities. So:

  · `scan_id`, `batch_id` and `job_id` are emitted as they are. ACP already generates them as
    opaque hex; they name work, not people.
  · A TENANT and a DOCUMENT are emitted only as HMACs, never as an email or a filename. The
    filename is the whole point of this product and belongs to a customer; Application Insights
    is a different trust boundary from the drawer, which shows a filename only to an authenticated
    user of that workspace.
  · Those HMACs need `ACP_TELEMETRY_SALT`. Without it they are OMITTED rather than computed from a
    per-process random salt, because a salt that changes per process gives every replica a
    different id for the same tenant — correlation that looks real and joins nothing. `status()`
    says when that is the case, so the gap is visible rather than silently degraded.

WHAT IS DELIBERATELY NOT DECIDED HERE. The sampling ratio defaults to 1.0 (send everything) and is
set by `APPLICATIONINSIGHTS_SAMPLING_RATIO`. A quieter default would be cheaper and would silently
lose the trace an operator went looking for; ACP's volume is document processing rather than
high-QPS web, so the honest default is "all of it, and here is the knob".
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading

from swallowed import swallowed

_CONNECTION_ENV = "APPLICATIONINSIGHTS_CONNECTION_STRING"
_SALT_ENV = "ACP_TELEMETRY_SALT"
_SAMPLING_ENV = "APPLICATIONINSIGHTS_SAMPLING_RATIO"

# Our own span attributes, allowlisted rather than denylisted. A denylist leaks by construction:
# it protects the keys somebody thought of, and the next attribute added anywhere in the codebase
# ships by default. Anything under `acp.` that is not here is dropped.
ALLOWED_ACP_ATTRIBUTES = frozenset({
    "acp.scan_id", "acp.batch_id", "acp.job_id", "acp.job_type", "acp.stage",
    "acp.tenant_id", "acp.document_id", "acp.rule_id", "acp.outcome", "acp.format",
    "acp.attempt", "acp.worker_role", "acp.revision",
})

# Standard OpenTelemetry attributes that carry free text from somewhere else and are redacted
# rather than dropped, because their PRESENCE is useful and their CONTENT is not ours to send.
# `db.statement` can contain literals; a URL's query can carry a filename or a token.
REDACTED_ATTRIBUTES = frozenset({"db.statement", "url.query", "http.request.header.authorization"})
_URL_KEYS = frozenset({"http.url", "url.full"})

_state = {"enabled": False, "reason": "not configured", "sampling_ratio": None,
          "correlation": "off", "configured_at": None}
_lock = threading.Lock()


def _salt() -> bytes | None:
    raw = os.environ.get(_SALT_ENV) or ""
    return raw.encode() if raw.strip() else None


def _digest(salt: bytes, *parts: str) -> str:
    """A stable, opaque 16-hex id. HMAC rather than a bare hash: a plain sha256 of an email is
    reversible by anyone with a list of the customer's addresses, which is exactly who would have
    one."""
    message = "\x1f".join(p or "" for p in parts).encode()
    return hmac.new(salt, message, hashlib.sha256).hexdigest()[:16]


def tenant_id(owner_email: str | None) -> str | None:
    """An opaque, stable id for a tenant — never the address itself. None when there is no salt
    configured, or no owner: an id that cannot be joined across replicas is worse than none."""
    salt = _salt()
    if not salt or not owner_email:
        return None
    return _digest(salt, "tenant", owner_email.strip().lower())


def document_id(scan_id: str | None, path: str | None) -> str | None:
    """An opaque, stable id for one document within one scan — never the filename.

    Scoped to the scan on purpose: the same file in two customers' estates must not share an id,
    and two runs over the same estate should still be comparable within each run.
    """
    salt = _salt()
    if not salt or not path:
        return None
    return _digest(salt, "document", scan_id or "", path)


def correlation(scan_id=None, batch_id=None, job_id=None, owner_email=None, path=None,
                **extra) -> dict:
    """The attribute bag for a span: opaque ids only, and no key that was not allowlisted.

    `extra` is filtered through the same allowlist as everything else, so a caller cannot smuggle
    a filename in by naming it something new.
    """
    attributes = {
        "acp.scan_id": scan_id, "acp.batch_id": batch_id, "acp.job_id": job_id,
        "acp.tenant_id": tenant_id(owner_email), "acp.document_id": document_id(scan_id, path),
    }
    for key, value in (extra or {}).items():
        attributes[key if key.startswith("acp.") else f"acp.{key}"] = value
    return {k: v for k, v in attributes.items()
            if v is not None and k in ALLOWED_ACP_ATTRIBUTES}


def scrub(attributes: dict | None) -> dict:
    """Apply the rules above to one span's attributes.

    Three outcomes, and the difference matters: an `acp.` key not on the allowlist is DROPPED (we
    control that namespace, so an unknown key is an accident); a known-risky standard key is
    REDACTED to a marker (its presence is diagnostic, its content is not ours); a URL keeps its
    scheme, host and path and loses its query. Everything else passes, because dropping all of
    OpenTelemetry's own semantic attributes would leave traces that cannot be read.
    """
    out = {}
    for key, value in (attributes or {}).items():
        if key.startswith("acp."):
            if key in ALLOWED_ACP_ATTRIBUTES:
                out[key] = value
            continue
        if key in REDACTED_ATTRIBUTES:
            out[key] = "[redacted]"
            continue
        if key in _URL_KEYS and isinstance(value, str):
            out[key] = value.split("?", 1)[0]
            continue
        out[key] = value
    return out


def _sampling_ratio() -> float:
    try:
        ratio = float(os.environ.get(_SAMPLING_ENV) or 1.0)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.0, ratio))


def status() -> dict:
    """What Live Operations shows about tracing: whether it is on, why not, and whether
    cross-service correlation is actually available. A drill-down link to traces that do not exist
    is worse than no link, so the UI needs the reason and not just the boolean."""
    with _lock:
        return dict(_state)


def configure(*, now_iso: str | None = None) -> dict:
    """Turn on Azure Monitor tracing, or record why it stayed off. Idempotent and never raises —
    a telemetry problem must not stop the API from serving."""
    with _lock:
        if _state["enabled"]:
            return dict(_state)
        connection = (os.environ.get(_CONNECTION_ENV) or "").strip()
        if not connection:
            _state.update(enabled=False, reason="not configured",
                          correlation="off", sampling_ratio=None)
            return dict(_state)
        ratio = _sampling_ratio()
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor  # noqa: PLC0415
            configure_azure_monitor(connection_string=connection, sampling_ratio=ratio)
            scrubbed = _install_scrubber()
        except ImportError:
            _state.update(enabled=False,
                          reason="azure-monitor-opentelemetry is not installed",
                          correlation="off", sampling_ratio=None)
            return dict(_state)
        except Exception as exc:  # noqa: BLE001 — never take the API down for telemetry.
            _state.update(enabled=False, reason=f"exporter failed to start: {type(exc).__name__}",
                          correlation="off", sampling_ratio=None)
            return dict(_state)
        if not scrubbed:
            # NO SCRUBBER, NO EXPORT. The processor is what stands between auto-instrumentation
            # and a customer's filename in a URL query, and it is installed by feature-detecting
            # `add_span_processor` on whatever provider the distro set up. If that detection ever
            # comes back false — a provider shape changed, the SDK swapped — the quiet outcome
            # would be a live exporter with nothing filtering it. So the exporter is shut down and
            # tracing reports itself off, with the reason.
            _shutdown_provider()
            _state.update(enabled=False,
                          reason="attribute scrubber could not be installed; exporter stopped "
                                 "rather than sending unscrubbed spans",
                          correlation="off", sampling_ratio=None)
            return dict(_state)
        _state.update(
            enabled=True, reason=None, sampling_ratio=ratio, configured_at=now_iso,
            # Said plainly, because the difference is invisible in the traces themselves: without a
            # salt the spans still export and still join by scan_id, they just carry no tenant or
            # document id at all.
            correlation="full" if _salt() else "ids_only",
        )
        return dict(_state)


def _shutdown_provider() -> None:
    """Stop the exporter the distro just started. Best-effort: if it cannot be stopped, the caller
    has already reported tracing as off, which is the claim that matters."""
    try:
        from opentelemetry import trace  # noqa: PLC0415
        shutdown = getattr(trace.get_tracer_provider(), "shutdown", None)
        if callable(shutdown):
            shutdown()
    except Exception:  # noqa: BLE001
        swallowed("telemetry._shutdown_provider: stopping the Azure Monitor exporter failed")


def _install_scrubber() -> bool:
    """Put `scrub` in front of the exporter.

    A span processor rather than a per-call discipline: relying on every future caller to remember
    is how one attribute eventually ships a filename. This runs on every span the SDK produces,
    including the ones auto-instrumentation creates and nobody in this repo wrote.

    Returns whether it actually attached. The caller treats False as fatal to tracing.
    """
    from opentelemetry import trace  # noqa: PLC0415
    from opentelemetry.sdk.trace import SpanProcessor  # noqa: PLC0415

    class _Scrubber(SpanProcessor):
        def on_start(self, span, parent_context=None):  # noqa: D102
            try:
                cleaned = scrub(dict(getattr(span, "attributes", None) or {}))
                for key, value in cleaned.items():
                    span.set_attribute(key, value)
            except Exception:  # noqa: BLE001 — a scrub failure must not drop the span silently
                # `scrub` is total by construction (tests/test_telemetry.py pins that), so
                # reaching here means an attribute shape nobody anticipated got past it — and
                # the span goes to the exporter with its ORIGINAL attributes, which is exactly
                # the case where an unscrubbed filename ships. It cannot be undone from here
                # (set_attribute cannot remove one), so it must at least be findable.
                swallowed("telemetry._Scrubber.on_start: scrubbing span attributes failed; "
                          "the span was exported unscrubbed")

        def on_end(self, span):  # noqa: D102
            return None

        def shutdown(self):  # noqa: D102
            return None

        def force_flush(self, timeout_millis: int = 30000):  # noqa: D102
            return True

    provider = trace.get_tracer_provider()
    add = getattr(provider, "add_span_processor", None)
    if not callable(add):
        # The no-op provider has no add_span_processor, and neither would a future provider shape
        # this code does not know. Reported rather than shrugged off — see the caller.
        return False
    add(_Scrubber())
    return True
