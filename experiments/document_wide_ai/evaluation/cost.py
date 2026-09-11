"""Cost/caching instrumentation (PRD "Cost and caching"). This prototype makes NO real
provider calls, so provider billing is never available here — only request/response
SHAPE is measured, and every figure derived from characters-as-a-proxy-for-tokens is
explicitly flagged `is_estimate=True`. Latency and counts taken from the mock call
itself are real measurements of THIS harness, not of a live provider.

Only a cache-ready stable prefix is implemented (`request/builder.py`); live caching,
provider pricing, and paid benchmarking are deferred per the PRD.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass

from experiments.document_wide_ai.contracts.v1 import DocumentContextManifest, EditResponseEnvelope
from experiments.document_wide_ai.request.builder import GenerationRequest

_CHARS_PER_TOKEN_ESTIMATE = 4  # crude, documented proxy — never presented as a real token count


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_ESTIMATE)


@dataclass(frozen=True)
class CostRecord:
    request_id: str
    stable_prefix_chars: int
    stable_prefix_tokens_estimated: int
    suffix_chars: int
    image_count: int
    output_edit_count: int
    output_unresolved_count: int
    latency_ms: float
    provider_cost_usd: float | None  # always None in this prototype — no real provider call
    is_estimate: bool = True


def record_cost(request: GenerationRequest, envelope: EditResponseEnvelope, *, latency_ms: float) -> CostRecord:
    return CostRecord(
        request_id=request.request_id,
        stable_prefix_chars=len(request.stable_prefix),
        stable_prefix_tokens_estimated=estimate_tokens(request.stable_prefix),
        suffix_chars=len(request.instruction_suffix),
        image_count=len(request.manifest.evidence),
        output_edit_count=len(envelope.edits),
        output_unresolved_count=len(envelope.unresolved),
        latency_ms=latency_ms,
        provider_cost_usd=None,
    )


@contextmanager
def timed():
    start = time.perf_counter()
    box: dict[str, float] = {}
    try:
        yield box
    finally:
        box["latency_ms"] = (time.perf_counter() - start) * 1000.0


@dataclass(frozen=True)
class CostComparison:
    """Structural comparison of request volume, NOT measured provider billing: document-wide
    generation sends the shared context prefix once for all findings; a repeated
    per-finding approach (the shape of the existing production waterfall's per-finding
    context, `api/document_context.py::context_for_finding`) would resend a comparable
    prefix once per finding. `is_estimate` is always True here — see module docstring.
    """

    finding_count: int
    document_wide_requests: int
    document_wide_prefix_chars_sent: int
    repeated_per_finding_requests: int
    repeated_per_finding_prefix_chars_sent: int
    is_estimate: bool = True


def compare_document_wide_vs_repeated(manifest: DocumentContextManifest, request: GenerationRequest) -> CostComparison:
    n = max(len(manifest.findings), 1)
    prefix_chars = len(request.stable_prefix)
    return CostComparison(
        finding_count=len(manifest.findings),
        document_wide_requests=1,
        document_wide_prefix_chars_sent=prefix_chars,
        repeated_per_finding_requests=n,
        repeated_per_finding_prefix_chars_sent=prefix_chars * n,
    )
