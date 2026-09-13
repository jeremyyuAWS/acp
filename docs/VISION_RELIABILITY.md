# Vision reliability

All replicas share endpoint-wide Redis admission (one active GPU request by default).
Leases renew while a request is active and expire after a crashed worker. A missing
coordinator fails closed in production; an unowned response cannot become a draft.
Capacity rejection does not open the provider circuit or strand its half-open probe.

Dependency timeouts and open circuits skip the immediate smaller-prompt retry.
Existing managed cloud generation retains its approved provider positions, image
limits, real provenance, and per-run spending ledger. Local-only consent never
escalates to paid/cloud vision. Uncertain billed requests are not automatically repeated.

Exhausted transient description requests schedule at most two proposal-only retries
after 60 and 120 seconds. Each restores the original run authorization and uses the
exact saved corrected artifact, source revision, and unchanged pending review.
Cancellation, permission changes, artifact replacement, and review changes stop recovery.
Pending recovery holds automatic publication of that file. Recovery creates drafts;
the existing apply and reassessment workflow still saves and verifies corrections.

Office image recovery is supported. PDF recovery is explicitly blocked until an
exact figure image association is available; whole-page body text must never become
figure alt text. These figures remain available for individual review. No retry grants accessibility certification or verification credit.

GPU residency and measurement controls are documented in
[OLLAMA_VISION_WARMING.md](OLLAMA_VISION_WARMING.md). The runtime overlay Dockerfile
requires an explicit digest of the currently deployed baked GPU image; it preserves
models and GPU capacity. The replay benchmark is a test harness, not measured live
model quality. A real representative quality/latency benchmark precedes model replacement.

Redis lease renewal cannot cancel work already accepted by a remote GPU during a
prolonged coordination outage. New dispatch fails closed and lost-lease responses
are rejected; Ollama's server parallelism stays at one by default as a second ceiling.
