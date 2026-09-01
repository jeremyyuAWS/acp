# Responsive Discovery with durable recovery

Production keeps `ACP_INLINE_DISCOVER=0` and `ACP_DEFER_ANALYSIS_TO_ASSESS=1`.
Discovery remains metadata-only and uses the durable queue, claim leases, retries,
and cancellation. The inline alternative from #1120 remains opt-in, not this rollout.

Set `ACP_DISCOVERY_RESERVED_WORKERS=1` on the worker tier. One existing pool slot
per replica claims only `scan_discover`; other slots keep their existing general
queue behavior, including accepting Discovery. No replicas or threads are added.
With the observed 12 threads per replica this leaves 11 general-purpose slots.
The reservation is capped below the pool size, preserving general work even after
live scale-down to one thread. Default zero preserves prior scheduling.

This prevents all slots from being occupied by long content jobs. It does not make
Drive itself faster or guarantee latency under arbitrary load. Compare identical
folder scopes and capture queue delay separately from enumeration and persistence.
Discovery's existing per-owner/source guard is unchanged; overlapping requests can
still conflict. This is not a new per-user fair queue.

`ACP_SCAN_FORMATS=pdf,docx,xlsx,pptx` scopes the production scan. Native Google
files follow their supported export format. No Drive search-index MIME predicate
is introduced; folder traversal remains necessary. HTML engines are retained and
can be restored to scan scope explicitly.

Roll back reservation with `ACP_DISCOVERY_RESERVED_WORKERS=0`; restore prior
format scope using `ACP_SCAN_FORMATS=pdf,docx,xlsx,pptx,html`. Image rollback must
use the previously recorded web and worker images. Do not enable inline Discovery
as a workaround: it gives up automatic recovery after API restarts.
