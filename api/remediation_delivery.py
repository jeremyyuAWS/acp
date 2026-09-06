"""Deliver an ALREADY-CORRECTED, ALREADY-VERIFIED artifact to its source provider. Nothing else.

This module is the executable half of PRD §11's delivery-failure class: "keep correction and
verification success; retry delivery only". It reads bytes ACP already stored, checks they are
the bytes it was authorised to send, and writes them to SharePoint, OneDrive or Google Drive.

WHAT IS NOT IN HERE, AND WHY THAT IS THE DESIGN RATHER THAN AN OMISSION. There is no import of a
fixer (`remediate_office`, `remediate_pdf`, `apply_*`), no import of an analyser, and no call that
re-runs verification. A delivery-only retry that could reach a fixer would be able to change what
the run claims about a document — and the run's `applied` and `verified` counters are exactly the
numbers a delivery failure must not disturb. Making that structural rather than careful is the
point: `tests/test_remediation_delivery_only.py` reads this file's imports and fails if a fixer
appears in them, because a rule enforced by a reviewer's attention is a rule that holds until the
day somebody is in a hurry.

The one write it makes to ACP's own record is `store.record_delivery_url`, which moves ONE column.
`record_remediation` moves four, including `remediated_at`, and calling it here would restamp a
week-old correction with today's time — making an artifact look newer than the verification that
passed it.
"""
from __future__ import annotations

import hashlib

#: The providers this module can address. Same tuple as remediation_exceptions.DELIVERY_PROVIDERS,
#: asserted equal in the tests rather than imported, so a provider added to the gate without a
#: writer here fails loudly instead of being refused at the last moment by a KeyError.
PROVIDERS: tuple[str, ...] = ("sharepoint", "onedrive", "drive")


class DeliveryRefused(Exception):
    """The artifact must not be sent. Carries the refusal code the gate would have used.

    Distinct from a delivery FAILURE: a refusal means ACP declined to write, and the corrected
    copy is exactly as it was. `code` is one of remediation_exceptions.REFUSAL_CODES so the
    worker's event and the request's own answer say the same thing.
    """

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


def load_artifact(*, owner: str | None, scan_id: str, file: str, expected_digest: str,
                  download) -> bytes:
    """The stored corrected copy, PROVEN to be the artifact this delivery was authorised for.

    `download(owner, scan_id, file) -> bytes | None` is injected so this can be tested without a
    storage account — and so nothing in this module holds a credential.

    THE DIGEST IS CHECKED HERE TOO, not only at the gate. The gate ran against a database row at
    request time; this runs against the bytes at write time, and between the two the object can
    have been replaced by a re-run of the document. Checking once would make "never deliver a
    stale artifact" true of the row and merely likely of the bytes.
    """
    if not expected_digest:
        raise DeliveryRefused("artifact_provenance_unknown")
    data = download(owner, scan_id, file)
    if not data:
        raise DeliveryRefused("artifact_missing")
    if hashlib.sha256(data).hexdigest() != expected_digest:
        raise DeliveryRefused("artifact_stale")
    return data


def mimetype_for(filename: str) -> str:
    import mimetypes
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


def deliver_to_drive(svc, *, folder_id: str, filename: str, data: bytes,
                     mimetype: str | None = None) -> str | None:
    """Upsert the corrected copy into the Drive mirror folder. Returns its webViewLink.

    An UPSERT rather than an unconditional create, for the reason the original mirror is one: a
    retry that piled a second copy beside the first would leave two documents claiming to be the
    corrected version of one source, and no way to tell which a link points at.
    """
    import io
    from googleapiclient.http import MediaIoBaseUpload
    import provenance

    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype or mimetype_for(filename),
                              resumable=False)
    safe = filename.replace("\\", "\\\\").replace("'", "\\'")
    existing = svc.files().list(
        q=f"name='{safe}' and '{folder_id}' in parents and trashed=false",
        fields="files(id)", pageSize=1).execute().get("files", [])
    props = provenance.stamp(filename)
    if existing:
        result = svc.files().update(fileId=existing[0]["id"], media_body=media,
                                    body={"properties": props},
                                    fields="id,webViewLink").execute()
    else:
        result = svc.files().create(body={"name": filename, "parents": [folder_id],
                                          "properties": props},
                                    media_body=media, fields="id,webViewLink").execute()
    return result.get("webViewLink") or None


def deliver_to_graph(token: str, *, drive_id: str | None, folder: str, filename: str,
                     data: bytes, mimetype: str | None = None) -> str | None:
    """Write the corrected copy into `folder` on a Graph drive. SharePoint and OneDrive both.

    NEVER IN PLACE. `scanner._sp_replace` exists and overwrites a source document; this does not
    call it. A delivery retry is a re-send of a copy, and turning it into an overwrite of the
    customer's original — on a path a user reaches by pressing Retry on a failure — would be a
    destructive action nobody authorised. The mirror folder is the same destination the first
    attempt addressed, which is what makes the retry a retry.
    """
    import scanner
    item = scanner._sp_upload(token, drive_id, folder, filename, data,
                              content_type=mimetype or mimetype_for(filename))
    return (item or {}).get("webUrl") or None


def perform_delivery(*, provider: str, destination: dict, filename: str, data: bytes,
                     drive_client=None, graph_token: str | None = None) -> str | None:
    """Dispatch one write by provider. Returns the destination URL, or None when the provider
    acknowledged the write without giving one.

    An unsupported provider raises `DeliveryRefused` rather than falling through to a default.
    ACP has been bitten by exactly that shape before — an unrecognised remediation source fell
    into the Drive branch and reported a missing Drive token (see handlers._remediate_file) — and
    the cost of a wrong default is higher here, because the fall-through would be a write.
    """
    key = (provider or "").strip().lower()
    if key not in PROVIDERS:
        raise DeliveryRefused("provider_unsupported")
    if key == "drive":
        folder_id = destination.get("folder_id") or destination.get("folder")
        if not folder_id:
            raise DeliveryRefused("destination_unknown")
        if drive_client is None:
            raise DeliveryRefused("destination_unknown")
        return deliver_to_drive(drive_client, folder_id=folder_id, filename=filename, data=data)
    drive_id, folder = destination.get("drive_id"), destination.get("folder")
    if not (drive_id and folder):
        raise DeliveryRefused("destination_unknown")
    if not graph_token:
        raise DeliveryRefused("destination_unknown")
    return deliver_to_graph(graph_token, drive_id=drive_id, folder=folder, filename=filename,
                            data=data)
