"""Refreshing one connector credential preserves the other credential for the same scan."""


def test_sharepoint_refresh_does_not_erase_drive_token(monkeypatch):
    import core
    monkeypatch.setattr(core, "_get_redis", lambda: None)
    core.SCAN_TOKENS.clear()
    core.register_scan_tokens("scan-refresh", drive="drive-token", sp="old-sp-token")

    core.register_scan_tokens("scan-refresh", sp="new-sp-token")

    assert core.get_scan_tokens("scan-refresh") == {
        "drive": "drive-token", "sp": "new-sp-token",
    }
    core.SCAN_TOKENS.clear()


def test_drive_refresh_does_not_erase_sharepoint_token(monkeypatch):
    import core
    monkeypatch.setattr(core, "_get_redis", lambda: None)
    core.SCAN_TOKENS.clear()
    core.register_scan_tokens("scan-refresh", drive="old-drive-token", sp="sp-token")

    core.register_scan_tokens("scan-refresh", drive="new-drive-token")

    assert core.get_scan_tokens("scan-refresh") == {
        "drive": "new-drive-token", "sp": "sp-token",
    }
    core.SCAN_TOKENS.clear()
