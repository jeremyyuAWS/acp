"""Provenance for files ACP writes back into a user's Drive.

Discovery must never re-ingest ACP's own output. A remediated copy re-discovered as a
source document inflates the file count, produces a phantom "duplicate", and shows up as
`remediated ✓` on a scan that remediated nothing — the user sees two documents where their
Drive holds one.

The original guard excluded files by the *folder* they sit in (default `Remediated/`). That
is brittle by construction, and every one of these breaks it:

  * the lookup takes the OLDEST folder matching the configured name, so a second folder of
    the same name anywhere in the Drive wins;
  * Drive's `not '<id>' in parents` only excludes files sitting DIRECTLY in that folder,
    not nested beneath it;
  * a file may have several parents, so "in the mirror folder" is not exclusive;
  * `routes/drive.py` writes to a hardcoded `Remediated`, while the exclusion looks up the
    admin-configured mirror name — rename it and the two disagree;
  * a copy written anywhere else (publish path, a user dragging it out) is never excluded.

So stamp the artifact, not its location. A file ACP produced says so about itself, wherever
it later gets moved to.

We use Drive `properties` (public custom metadata, visible to every OAuth client) rather
than `appProperties` (private to the client that wrote it). ACP writes through more than one
credential — per-user GIS tokens and the service-account ADC path — and an `appProperties`
stamp written under one client is invisible to the other, which would silently re-open the
exact hole this closes. The stamp is provenance, not a secret; nothing is gained by hiding it.

Note the asymmetry: the scan holds `drive.readonly`, so discovery can only READ this stamp.
Files remediated before this shipped carry no stamp and are still caught by the (retained)
folder-name exclusion — see `_search_drive` / `_search_folder`.
"""

# Drive caps a property at 124 bytes for key + value combined, and 100 properties per file.
ACP_STAMP_KEY = "acpGenerated"
ACP_STAMP_VALUE = "true"
ACP_SOURCE_KEY = "acpSourceFile"

# Ask for this in every files.list `fields` mask that feeds discovery — without it Drive
# omits `properties` entirely and `is_acp_generated` silently answers False for everything.
# size / owners / shared feed the estate drill-down's triage metadata (biggest-first, by owner,
# externally-shared-first); all are cheap list fields, so they ride the same page with no extra call.
DRIVE_FIELDS = ("id,name,mimeType,md5Checksum,modifiedTime,properties,"
                "size,owners(displayName,emailAddress),shared")


def stamp(source_filename: str | None = None) -> dict[str, str]:
    """The `properties` dict to attach to any document ACP creates or updates in Drive.

    Attach it to ACP's OUTPUT only — never to a user's original (an archive move, a rename),
    or discovery would skip the very documents it exists to find.
    """
    props = {ACP_STAMP_KEY: ACP_STAMP_VALUE}
    if source_filename:
        # Trimmed to stay under Drive's 124-byte key+value cap; this is a breadcrumb for a
        # human reading the file's metadata, not a key anything joins on.
        props[ACP_SOURCE_KEY] = source_filename[:100]
    return props


def is_acp_generated(drive_file: dict) -> bool:
    """True when this Drive file is ACP's own output and discovery must skip it."""
    return ((drive_file or {}).get("properties") or {}).get(ACP_STAMP_KEY) == ACP_STAMP_VALUE
