# Discovery HTTP transport isolation

## Evidence and scope

Production scan `128d4bf609b4`, job `588229b14bb742ef`, was claimed at
2026-08-31 13:17:15 UTC. The worker logged `double free or corruption (!prev)`
at 13:19:13 and Azure recorded exit 139. A replacement claimed attempt 2
at 13:27:09. These facts do not identify the native library responsible.

The folder walk shares one Google service between executor threads. Previously
its generated requests all used the same httplib2 connection pool. Google's
[thread-safety guidance](https://googleapis.github.io/google-api-python-client/docs/thread_safety.html)
explicitly requires separate HTTP transports for concurrent threads.

The regression fixture uses the real generated SDK requests and a stub wire
operation, synchronizing four concurrent calls. Before the fix it observes ONE
transport across all four; the assertion fails. This reproduces the unsafe
sharing, **not the production native crash**.

## Change

`scanner._drive_service` installs a request builder whose ordinary `execute()`
creates a private authorized, socket-timeout-bounded transport, preserves SDK
retry/parsing behavior, and closes it in a finally block. Parallel folder
listing remains enabled. Credential token/expiry updates are execution-local
through a shallow copy. Explicit caller transports remain caller-owned.

## Limitations and rollout

- No process-level crash containment and no claim that the incident is cured.
- SDK batching and direct `MediaIoBaseDownload` transport access are not changed.
- Other Drive service constructors are not changed in this slice.
- A fresh connection per execution/page loses connection reuse. Measure throughput,
  TLS overhead and latency on a representative staging folder tree before rollout.
- Socket timeout is not a whole-job deadline; retries can exceed one socket timeout.
- ADC refresh behavior needs staging validation; synthetic-token tests cannot prove it.
- No production config, restart, submission, cancellation or deployment performed.

Run focused tests in this worktree, then full Linux CI and a controlled staging
Discovery. Observe worker exits, completed file/folder counts, cancellation,
401/429 handling, and first-progress/total duration. Only then consider production.
Do not assume successful API polling proves progress.
