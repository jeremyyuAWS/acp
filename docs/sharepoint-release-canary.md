# SharePoint release production canary

Use one approved, non-customer test document in the intended production library. The operator must
have explicit authorization to publish it. This procedure does not grant that authorization.

1. Download the source document and its effective permissions before release.
2. Publish exactly that corrected copy through ACP.
3. Download the source again, the delivered copy, both effective permission snapshots, the raw
   Microsoft Graph `driveItem` JSON for the source (before and after) and destination, and ACP's
   server-generated release manifest. Request each item with `?$select=id,name,webUrl,parentReference`.
4. Record the expected immutable source-relative path and delivered relative path in `bundle.json`.
5. Run `python scripts/verify_sharepoint_release_canary.py bundle.json --output report.json`.

The bundle contains no access token. Paths are relative to the bundle file:

```json
{
  "manifest_response": {"manifest": {}, "content_digest": {"algorithm": "SHA-256", "value": "..."}},
  "expected": {
    "source_relative_path": "Policies/report.docx",
    "destination_relative_path": "Policies/report.docx",
    "provider_destination_path": "Remediated/2026-09-06 01-00 UTC/Policies/report.docx"
  },
  "artifacts": {
    "original_before": "original-before.docx",
    "original_after": "original-after.docx",
    "corrected": "corrected.docx"
  },
  "permissions": {
    "source_before": "source-before.json",
    "source_after": "source-after.json",
    "destination": "destination.json",
    "expected_destination": "expected-destination.json"
  },
  "provider_observations": {
    "source_before": "source-item-before.json",
    "source_after": "source-item-after.json",
    "destination": "destination-item.json"
  }
}
```

A passing report proves the manifest was not altered after ACP generated its digest; the original
bytes and permissions remained unchanged; the delivered bytes match ACP's corrected checksum; the
source and delivered provider IDs differ; Graph independently reports the expected source identity
and destination folder placement; the release contains exactly one successful document; ACP records
the actor, scan, snapshot, production version, and timestamps; and the delivered permissions match
the approved expectation. Retain the bundle and report with the
release evidence. The SHA-256 manifest digest is tamper evidence, not a digital signature.
