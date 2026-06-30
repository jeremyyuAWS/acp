"""Upload every file in a directory to a single Google Drive folder.

  python scripts/upload_dir_to_drive.py --dir /tmp/acp-bulk-corpus --folder <FOLDER_ID>

Requires ADC with Drive WRITE scope:
  gcloud auth application-default login \\
    --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/drive
"""
from __future__ import annotations
import argparse, time
from pathlib import Path

MIME = {
    ".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _svc():
    import google.auth, google.auth.transport.requests
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    creds.refresh(google.auth.transport.requests.Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _existing_names(svc, folder: str) -> set[str]:
    """Names already present in the destination folder. Drive's API create() does NOT
    auto-rename on a name collision the way the web UI's drag-and-drop does — a second
    run of this script against the same folder used to silently double-upload every
    file. Paginate files().list() so this still works on folders with 1000+ entries."""
    names: set[str] = set()
    token = None
    while True:
        resp = svc.files().list(
            q=f"'{folder}' in parents and trashed=false",
            fields="nextPageToken, files(name)", pageSize=1000, pageToken=token,
        ).execute()
        names.update(f["name"] for f in resp.get("files", []))
        token = resp.get("nextPageToken")
        if not token:
            return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--folder", required=True, help="Drive folder ID to upload into")
    ap.add_argument("--force", action="store_true",
                     help="Re-upload even if a file with the same name already exists in the "
                          "folder (creates a second copy — Drive allows duplicate names). "
                          "Default: skip names that already exist, so re-running is safe.")
    args = ap.parse_args()

    from googleapiclient.http import MediaFileUpload
    svc = _svc()
    who = svc.about().get(fields="user").execute()["user"]["emailAddress"]
    files = sorted(p for p in Path(args.dir).glob("*") if p.is_file())
    existing = set() if args.force else _existing_names(svc, args.folder)
    skipped = sum(1 for p in files if p.name in existing)
    print(f"Uploading {len(files)} files to folder {args.folder} as {who}"
          f"{f' ({skipped} already present — skipping)' if skipped else ''}")
    i = 0
    for p in files:
        if p.name in existing:
            continue
        i += 1
        media = MediaFileUpload(str(p), mimetype=MIME.get(p.suffix.lower(), "application/octet-stream"),
                                resumable=False)
        svc.files().create(body={"name": p.name, "parents": [args.folder]},
                           media_body=media, fields="id").execute()
        if i % 20 == 0:
            print(f"  {i}/{len(files) - skipped}")
        time.sleep(0.08)  # gentle on the Drive rate limit
    print(f"Done. Uploaded {i}, skipped {skipped} already-present.")


if __name__ == "__main__":
    main()
