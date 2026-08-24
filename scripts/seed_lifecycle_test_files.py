"""Create Google Drive test files with controlled metadata for lifecycle rule testing.

This script seeds a test folder in Google Drive with files that have specific
modifiedTime values, so you can verify that lifecycle rules (modified_at:before,
modified_age_days:gt) fire correctly against real Drive scans.

LIMITATION — createdTime is read-only on Drive:
  Google Drive does not allow setting createdTime via the API. The 'Older than N days'
  rule (age_days:gt, based on created_at / Drive's createdTime) can only be tested
  against files that actually exist in Drive from that date, or against local files
  (where filesystem birthtime is used). The 'Not modified in last N days' rule
  (modified_age_days:gt) CAN be tested by backdating modifiedTime — which this script does.

Prerequisites:
  .secrets/drive-token.json  — OAuth token with drive.file scope (write access)

  To mint a write-scope token (separate from the read-only connector token):
    uv run --with google-auth-oauthlib python scripts/drive_auth_write.py
  (or re-run drive_auth.py with the drive.file scope instead of drive.readonly)

Usage:
  uv run python scripts/seed_lifecycle_test_files.py [FOLDER_ID]

  FOLDER_ID defaults to the env var ACP_TEST_FOLDER_ID (optional).
  If omitted, the script prints the URL of a newly created test folder.

What it creates (in the target folder):
  lifecycle-test-recent.txt       modifiedTime = today       → NOT matched by modified_age_days>30
  lifecycle-test-30d.txt          modifiedTime = 31 days ago → matched by modified_age_days>30
  lifecycle-test-1year.txt        modifiedTime = 366 days ago → matched by modified_age_days>365
  lifecycle-test-5year.txt        modifiedTime = 1826 days ago → matched by modified_age_days>1825
  lifecycle-test-finance-stale.txt  modifiedTime = 400 days ago, path contains "Finance"
  lifecycle-test-large-placeholder.txt  content padded to ~1050 KB → matched by size_kb>1000
  lifecycle-test-sharepoint-sim.txt  name signals SP origin for source-based rules

After running:
  1. Point a Discover scan at the test folder.
  2. Enable lifecycle rules (modified_age_days>30, etc.) and run the scan.
  3. Verify the expected files appear as Archive Candidates in the Discover step 3 UI.
  4. Check the DB: SELECT name, lifecycle_status, lifecycle_rule_id FROM scan_inventory.

Verifying modifiedTime is stored:
  After a scan, run:
    SELECT name, source_modified, lifecycle_status FROM scan_inventory WHERE scan_id=?
  The source_modified column should hold the Drive modifiedTime values set here.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "api"))


def _load_creds(token_path: Path):
    from google.oauth2.credentials import Credentials
    return Credentials.from_authorized_user_file(
        str(token_path),
        scopes=["https://www.googleapis.com/auth/drive.file"],
    )


def _build_service(creds):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _days_ago_iso(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _patch_modified_time(creds, file_id: str, mod_time: str) -> str:
    """Set modifiedTime via a direct PATCH, bypassing client-library schema checks.

    Some versions of google-api-python-client omit setModifiedTime from their
    discovery schema, causing a TypeError when passed as a kwarg.  A raw urllib
    PATCH with ?setModifiedTime=true always works regardless of library version.
    """
    import json
    import urllib.request
    auth_headers: dict = {}
    creds.apply(auth_headers)
    url = (
        f"https://www.googleapis.com/drive/v3/files/{file_id}"
        "?setModifiedTime=true&fields=modifiedTime"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps({"modifiedTime": mod_time}).encode(),
        headers={**auth_headers, "Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read()).get("modifiedTime", mod_time)


def _create_text_file(svc, name: str, content: str, parent_id: str,
                      modified_days_ago: int, *, creds=None) -> dict:
    """Create a plain-text file in Drive with a backdated modifiedTime."""
    from googleapiclient.http import MediaInMemoryUpload
    mod_time = _days_ago_iso(modified_days_ago)
    body = {
        "name": name,
        "parents": [parent_id],
        "mimeType": "text/plain",
    }
    media = MediaInMemoryUpload(content.encode(), mimetype="text/plain")
    result = svc.files().create(
        body=body, media_body=media,
        fields="id,name,modifiedTime,createdTime,size,webViewLink",
    ).execute()
    # Backdate modifiedTime via direct PATCH (avoids library schema issues)
    if creds is not None:
        result["modifiedTime"] = _patch_modified_time(creds, result["id"], mod_time)
    return result


def _get_or_create_folder(svc, name: str, parent_id: str | None) -> str:
    q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    existing = svc.files().list(q=q, fields="files(id,name)", pageSize=1).execute().get("files", [])
    if existing:
        return existing[0]["id"]
    body: dict = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        body["parents"] = [parent_id]
    f = svc.files().create(body=body, fields="id").execute()
    return f["id"]


# Test file specs: (filename, content_description, modified_days_ago)
_TEST_FILES = [
    (
        "lifecycle-test-recent.txt",
        "Modified today — should NOT be flagged by modified_age_days>30.",
        0,
    ),
    (
        "lifecycle-test-30d.txt",
        "Modified 31 days ago — should be flagged by modified_age_days>30.",
        31,
    ),
    (
        "lifecycle-test-1year.txt",
        "Modified 366 days ago — should be flagged by modified_age_days>365.",
        366,
    ),
    (
        "lifecycle-test-5year.txt",
        "Modified 1826 days ago — should be flagged by modified_age_days>1825 (5+ years).",
        1826,
    ),
    (
        "lifecycle-test-finance-stale.txt",
        "Finance folder simulation, modified 400 days ago. "
        "Matches a combined path:contains=Finance + modified_age_days>365 rule.",
        400,
    ),
]


def _make_large_content(target_kb: int = 1050) -> str:
    line = "X" * 80 + "\n"
    lines_needed = (target_kb * 1024) // len(line) + 1
    return line * lines_needed


def main() -> None:
    token_path = _ROOT / ".secrets" / "drive-write-token.json"
    if not token_path.exists():
        print(
            f"ERROR: {token_path} not found.\n"
            "Mint a drive.file-scope token first:\n"
            "  uv run --with google-auth-oauthlib python scripts/drive_auth_write.py",
            file=sys.stderr,
        )
        sys.exit(1)

    folder_id = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ACP_TEST_FOLDER_ID")

    creds = _load_creds(token_path)
    svc = _build_service(creds)

    if not folder_id:
        folder_id = _get_or_create_folder(svc, "acp-lifecycle-test", parent_id=None)
        print(f"Created test folder: https://drive.google.com/drive/folders/{folder_id}")
    else:
        print(f"Using existing folder: {folder_id}")

    created = []
    print("\nCreating test files with backdated modifiedTime …")

    for name, description, modified_days_ago in _TEST_FILES:
        content = f"{description}\n\nmodifiedTime target: {_days_ago_iso(modified_days_ago)}\n"
        result = _create_text_file(svc, name, content, folder_id, modified_days_ago, creds=creds)
        created.append(result)
        print(f"  ✓ {name:50s}  modifiedTime={result.get('modifiedTime', '?')}")

    # Large file (>1 MB) for size_kb>1000 rule testing
    large_content = _make_large_content(1050)
    result = _create_text_file(svc, "lifecycle-test-large-placeholder.txt",
                               large_content, folder_id, modified_days_ago=400, creds=creds)
    created.append(result)
    size_b = int(result.get("size") or 0)
    print(f"  ✓ lifecycle-test-large-placeholder.txt   {size_b // 1024} KB, "
          f"modifiedTime={result.get('modifiedTime', '?')}")

    print(f"\n{len(created)} files created in folder {folder_id}")
    print("\nNext steps:")
    print("  1. In ACP Discover, add the test folder as a source.")
    print("  2. Enable lifecycle rules (e.g. modified_age_days>30 → archive).")
    print("  3. Run Discover and check step 3 for Archive Candidates.")
    print("  4. Verify source_modified is stored correctly:")
    print("       SELECT name, source_modified, lifecycle_status")
    print("       FROM scan_inventory WHERE scan_id=?")
    print()
    print("Expected results for modified_age_days>30 archive rule:")
    for name, _, days in _TEST_FILES:
        expected = "Archive Candidate" if days > 30 else "Active"
        print(f"  {name:50s}  → {expected}")
    print(f"  {'lifecycle-test-large-placeholder.txt':50s}  → Archive Candidate (400d + size)")

    # Write a manifest for use in assertions
    manifest_path = _ROOT / ".secrets" / "lifecycle_test_manifest.json"
    manifest = {
        "folder_id": folder_id,
        "files": [
            {"id": f["id"], "name": f["name"],
             "modifiedTime": f.get("modifiedTime"),
             "webViewLink": f.get("webViewLink")}
            for f in created
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest written to {manifest_path} (for integration test assertions)")


if __name__ == "__main__":
    main()
