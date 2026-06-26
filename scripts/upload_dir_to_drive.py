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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--folder", required=True, help="Drive folder ID to upload into")
    args = ap.parse_args()

    from googleapiclient.http import MediaFileUpload
    svc = _svc()
    who = svc.about().get(fields="user").execute()["user"]["emailAddress"]
    files = sorted(p for p in Path(args.dir).glob("*") if p.is_file())
    print(f"Uploading {len(files)} files to folder {args.folder} as {who}")
    for i, p in enumerate(files, 1):
        media = MediaFileUpload(str(p), mimetype=MIME.get(p.suffix.lower(), "application/octet-stream"),
                                resumable=False)
        svc.files().create(body={"name": p.name, "parents": [args.folder]},
                           media_body=media, fields="id").execute()
        if i % 20 == 0 or i == len(files):
            print(f"  {i}/{len(files)}")
        time.sleep(0.08)  # gentle on the Drive rate limit
    print("Done.")


if __name__ == "__main__":
    main()
