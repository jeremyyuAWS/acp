"""Upload test corpus to Google Drive under a structured folder hierarchy.

Prerequisites:
  gcloud auth application-default login \
    --scopes=https://www.googleapis.com/auth/drive

Then run:
  python scripts/upload_to_drive.py [--root-name acp-test-suite]

Creates:
  acp-test-suite/
    critical/     pdf-critical-*, docx-critical-*, pptx-critical-*
    serious/      pdf-serious-*, docx-serious-*
    moderate/     pdf-moderate-*, docx-moderate-*, pptx-moderate-*
    borderline/   pdf-borderline-*
    clean/        pdf-clean-*, docx-clean-*, pptx-clean-*

Prints the folder IDs — set ACP_DRIVE_FOLDER to any of them to scope the scan.
"""
from __future__ import annotations
import argparse, json, os, time
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "test-corpus/files"

FOLDER_MAP: dict[str, list[str]] = {
    "critical":   ["pdf-critical", "docx-critical", "pptx-critical", "html-critical"],
    "serious":    ["pdf-serious",  "docx-serious",  "html-serious"],
    "moderate":   ["pdf-moderate", "docx-moderate", "pptx-moderate"],
    "borderline": ["pdf-borderline"],
    "clean":      ["pdf-clean",    "docx-clean",    "pptx-clean",    "html-clean"],
}

MIME = {
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html",
    ".htm":  "text/html",
}


def _drive_svc():
    import google.auth, google.auth.transport.requests
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive"])
    creds.refresh(google.auth.transport.requests.Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _make_folder(svc, name: str, parent: str) -> str:
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent]}
    f = svc.files().create(body=meta, fields="id").execute()
    return f["id"]


def _upload(svc, path: Path, parent: str) -> str:
    from googleapiclient.http import MediaFileUpload
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    media = MediaFileUpload(str(path), mimetype=mime, resumable=False)
    f = svc.files().create(
        body={"name": path.name, "parents": [parent]},
        media_body=media, fields="id,name").execute()
    return f["id"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root-name", default="acp-test-suite")
    args = parser.parse_args()

    svc = _drive_svc()
    about = svc.about().get(fields="user").execute()
    print(f"Signed in as: {about['user']['emailAddress']}")

    root_id = _make_folder(svc, args.root_name, "root")
    print(f"\nCreated root folder: {args.root_name}  (id={root_id})")
    print(f"  → Set ACP_DRIVE_FOLDER={root_id} to scan the whole suite\n")

    ids: dict[str, str] = {}
    for subfolder, prefixes in FOLDER_MAP.items():
        fid = _make_folder(svc, subfolder, root_id)
        ids[subfolder] = fid
        print(f"  Created {subfolder}/  (id={fid})")
        files_in_folder = [p for p in sorted(CORPUS.glob("*"))
                           if any(p.name.startswith(pfx) for pfx in prefixes)]
        for p in files_in_folder:
            file_id = _upload(svc, p, fid)
            print(f"    ↑ {p.name}  (id={file_id})")
            time.sleep(0.2)  # avoid Drive rate limit

    print("\nFolder IDs for ACP_DRIVE_FOLDER:")
    for name, fid in {"(all)": root_id, **ids}.items():
        print(f"  {name:<12} {fid}")
    print("\nDone. Re-deploy with ACP_DRIVE_FOLDER=<id> to scan a specific tier.")


if __name__ == "__main__":
    main()
