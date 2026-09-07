import threading
import time

import lf


def test_langfuse_outage_cannot_hold_a_worker_and_flushes_are_coalesced(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    class StalledLangfuse:
        calls = 0

        def flush(self):
            self.calls += 1
            entered.set()
            release.wait(timeout=2)

    client = StalledLangfuse()
    monkeypatch.setattr(lf, "_ENABLED", True)
    monkeypatch.setattr(lf, "_client", client)
    monkeypatch.setattr(lf, "_flush_requested", False)
    monkeypatch.setattr(lf, "_flush_thread", None)

    started = time.monotonic()
    lf.flush()
    assert time.monotonic() - started < 0.1
    assert entered.wait(timeout=1)

    # Repeated job completions during the outage neither block nor create more exporter threads.
    first_thread = lf._flush_thread
    for _ in range(20):
        lf.flush()
    assert lf._flush_thread is first_thread
    assert client.calls == 1

    release.set()
    first_thread.join(timeout=1)
    assert not first_thread.is_alive()
    assert client.calls == 2  # one coalesced follow-up exports events added during the first pass
