from api.routes import scans


def test_sealed_stage_input_uses_manifest_as_snapshot(monkeypatch):
    class Store:
        def current_stage_output_manifest(self, sid, stage):
            assert (sid, stage) == ("scan-1", "assess")
            return {"manifest_id": "sealed-assess-output"}

    monkeypatch.setattr(scans.core, "store", Store())
    assert scans._sealed_stage_input("scan-1", "assess", "legacy-snapshot") == (
        "sealed-assess-output", "sealed-assess-output")


def test_sealed_stage_input_preserves_legacy_fallback_when_upstream_is_unsealed(monkeypatch):
    class Store:
        def current_stage_output_manifest(self, sid, stage):
            return None

    monkeypatch.setattr(scans.core, "store", Store())
    assert scans._sealed_stage_input("scan-1", "assess", "legacy-snapshot") == (
        "legacy-snapshot", None)
