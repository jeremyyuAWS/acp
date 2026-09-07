"""Large Release downloads build in the durable worker and persist outside the request."""
import io

import blob
import handlers
from routes import scans


class _Store:
    phases = []

    def get_scan(self, scan_id, owner=None):
        if scan_id == "scan-1" and owner == "owner@example.com":
            return {"run": {"source": "drive"}, "files": [{"file": "report.pdf"}]}
        return None

    def set_job_phase(self, job_id, phase):
        self.phases.append((job_id, phase))


def test_prepare_job_builds_and_persists_the_archive(monkeypatch):
    store = _Store()
    monkeypatch.setattr(handlers.core, "store", store)
    package = io.BytesIO(b"zip-bytes")
    monkeypatch.setattr(scans, "_build_release_zip",
        lambda *args, **kwargs: (package, 9, "Board.zip"))
    uploaded = []
    monkeypatch.setattr(blob, "upload_release_package",
        lambda owner, scan_id, job_id, stream: uploaded.append(
            (owner, scan_id, job_id, stream.read())) or "https://blob/package")

    handlers._prepare_release_package({
        "scan_id": "scan-1", "owner": "owner@example.com", "files": ["report.pdf"],
        "package_name": "Board", "preserve_hierarchy": True, "include_manifest": True,
    }, {"id": "job-1"})

    assert uploaded == [("owner@example.com", "scan-1", "job-1", b"zip-bytes")]
    assert store.phases == [
        ("job-1", "building the ZIP package"),
        ("job-1", "saving the package for download"),
    ]
