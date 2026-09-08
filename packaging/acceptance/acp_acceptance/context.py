"""What a scenario is handed: the target, the backend, and somewhere to put evidence.

SEPARATE FROM runner.py ON PURPOSE. `scenarios.py` needs this type and `runner.py` needs the
scenario registry; putting the context in the runner makes those two import each other. The split
also states the dependency the right way round: a scenario knows about a context, and knows
nothing about the runner that will collect its result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .backend import ExecutionBackend, HttpResponse
from .target import Target


@dataclass
class ArtifactSink:
    """Where a scenario writes evidence too big for the report — a manifest, a captured stream.

    IN-MEMORY BY DEFAULT, and that is what makes `--self-test` a real exercise of the artifact
    path rather than a branch around it. With no directory the sink records the relative path and
    the bytes and writes nothing, so the self-test produces a report whose `artifacts` arrays are
    populated exactly as a real run's would be, with no filesystem involved.

    PATHS ARE RELATIVE TO THE REPORT, always. An absolute path from the machine that produced the
    report is useless to everyone else who reads it, and on a CI runner it also leaks the job's
    directory layout into a document that goes to customers.
    """

    directory: Path | None = None
    written: dict[str, bytes] = field(default_factory=dict)

    def write(self, relative_path: str, data: str | bytes) -> str:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self.written[relative_path] = payload
        if self.directory is not None:
            full = self.directory / relative_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_bytes(payload)
        return relative_path


@dataclass
class ScenarioContext:
    target: Target
    backend: ExecutionBackend
    artifacts: ArtifactSink

    # Convenience wrappers. They exist so a scenario body reads as the question it is asking
    # rather than as transport plumbing — and so that every scenario goes through the backend,
    # which is the property the whole suite's testability rests on.
    def get(self, path: str, *, requires: str | None = None) -> HttpResponse:
        return self.backend.http("GET", path, requires=requires)

    def post(self, path: str, body: Any = None, *, requires: str | None = None) -> HttpResponse:
        return self.backend.http("POST", path, body=body, requires=requires)

    def artifact(self, name: str, data: str | bytes, *, scenario_id: str) -> str:
        return self.artifacts.write(f"artifacts/{scenario_id}/{name}", data)
