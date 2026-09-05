"""Microsoft Graph adapter for lifecycle archive auto-fire — the only part that touches a tenant.

SPLIT OUT FROM THE DECISION so every branch of archive_autofire.py is testable without a tenant,
and so the network surface this feature adds is one readable file rather than calls scattered
through a route. Everything here is a fact-gatherer or a mover; nothing here decides whether a
move is allowed.

THREE-VALUED ON PURPOSE, and it is the whole reason this file is not two `httpx` calls. Every
fact it returns is True, False, or None, where None means ACP could not establish it. A Graph
call that 403s tells you nothing about whether the item exists — reporting `exists: False` there
would send the caller down the "it was deleted, cancel" path when the truth is "we were refused",
and those need opposite handling. So every probe swallows its own failure into None and records
why, and archive_autofire.preflight routes every None to a human.

WHAT MAKES A MOVE SAFE HERE, all four enforced at the provider rather than hoped for:

  * `@microsoft.graph.conflictBehavior: fail` on the PATCH. Graph's default is `rename`, which
    would quietly land `x 1.docx` next to an existing `x.docx` and report success — a collision
    reported as a completed archive. `replace` would be worse. The collision pre-check exists too,
    but a check-then-act has a window, and this closes it at the provider.
  * `if-match` on the item's eTag. The evaluation said this document is superseded; if it has
    changed since, that evaluation is stale and the PATCH must fail rather than move a document
    nobody assessed in its current form.
  * Folders are created find-first, never `conflictBehavior: replace` — the same reasoning
    scanner._sp_folder_id records, and it matters more here: replace on an ARCHIVE folder
    destroys the archive.
  * A move whose response ACP cannot read is never reported as done. It returns
    `verified: None`, which becomes recovery-required upstream.

CREDENTIALS NEVER LEAVE THIS FILE. The token is a parameter, never stored on the returned facts,
never in a detail string, never in an event. Provider error text is passed upward only through
archive_autofire.event_payload, which withholds anything that looks like a credential.
"""
from __future__ import annotations

import posixpath

#: Graph failure kinds, as archive_autofire.FAILURE_ROUTES keys them.
PERMISSION, COLLISION, RATE_LIMITED, AMBIGUOUS, NOT_FOUND = (
    "permission", "collision", "rate_limited", "ambiguous", "not_found")


class ArchiveSourceError(Exception):
    """A provider failure with a classification the caller can route on.

    `kind` is one of the constants above; `detail` is safe to store. Deliberately not carrying the
    raw response — a Graph error body can contain a signed URL, and this object ends up in an
    audit row.
    """

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def classify_http(status: int | None, message: str = "") -> str:
    """An HTTP status → the failure kind it means for an archive move."""
    if status in (401, 403):
        return PERMISSION
    if status == 409 or "conflict" in (message or "").lower():
        return COLLISION
    if status == 429 or (status is not None and status >= 500):
        return RATE_LIMITED
    if status == 404:
        return NOT_FOUND
    return AMBIGUOUS


class GraphArchiveSource:
    """SharePoint/OneDrive item reads and one move, over injectable transport.

    `get`, `post` and `patch` are the seams. Production passes none and gets scanner's own
    throttling-aware `_sp_get` plus httpx for the two writes; tests pass callables and exercise
    every branch — including the throttle and the ambiguous response, which no live tenant will
    produce on demand.
    """

    def __init__(self, token: str, *, get=None, post=None, patch=None):
        self._token = token
        self._get = get
        self._post = post
        self._patch = patch

    # ── transport ────────────────────────────────────────────────────────────

    def _graph_get(self, url: str):
        if self._get is not None:
            return self._get(self._token, url)
        import scanner
        return scanner._sp_get(self._token, url)

    def _base(self, drive_id: str | None) -> str:
        if self._get is not None or self._post is not None or self._patch is not None:
            # Same convention scanner._sp_base encodes, restated here so an injected-transport
            # test does not have to import the scanner to know what URL it will be handed.
            root = "https://graph.microsoft.com/v1.0"
            return f"{root}/drives/{drive_id}" if drive_id else f"{root}/me/drive"
        import scanner
        return scanner._sp_base(drive_id)

    def _graph_post(self, url: str, body: dict) -> tuple[int, dict]:
        if self._post is not None:
            return self._post(self._token, url, body)
        import httpx
        r = httpx.post(url, headers={"Authorization": f"Bearer {self._token}",
                                     "Content-Type": "application/json"},
                       json=body, timeout=30, follow_redirects=True)
        return r.status_code, (r.json() if r.content else {})

    def _graph_patch(self, url: str, body: dict, *, etag: str | None) -> tuple[int, dict]:
        if self._patch is not None:
            return self._patch(self._token, url, body, etag)
        import httpx
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        if etag:
            # The precondition that makes "unchanged since evaluation" true AT THE MOMENT OF THE
            # MOVE rather than a few seconds earlier. Graph answers 412 when it no longer holds.
            headers["if-match"] = etag
        r = httpx.patch(url, headers=headers, json=body, timeout=30, follow_redirects=True)
        return r.status_code, (r.json() if r.content else {})

    # ── reads ────────────────────────────────────────────────────────────────

    _ITEM_SELECT = "id,eTag,name,webUrl,lastModifiedDateTime,parentReference,file,folder"

    def item(self, drive_id: str | None, item_id: str) -> dict:
        """One item, as `{"found": True|False|None, "item": {...}, "detail": str}`.

        The three values are the point. False is a 404 — Graph is telling us the item is gone.
        None is anything else: a refusal, a throttle, a transport error. Only False licenses the
        caller to conclude a document no longer exists.
        """
        url = f"{self._base(drive_id)}/items/{item_id}?$select={self._ITEM_SELECT}"
        try:
            data = self._graph_get(url)
        except PermissionError as e:
            return {"found": None, "item": None, "detail": f"Microsoft Graph refused the read: {e}"[:300]}
        except Exception as e:  # noqa: BLE001 — a read failure is a fact about the read, not an outage
            detail = f"{type(e).__name__}: {e}"[:300]
            if _looks_like_404(e):
                return {"found": False, "item": None, "detail": "The item was not found."}
            return {"found": None, "item": None, "detail": detail}
        if not isinstance(data, dict) or not data.get("id"):
            return {"found": None, "item": None,
                    "detail": "Microsoft Graph returned a shape ACP does not recognise."}
        return {"found": True, "item": data, "detail": ""}

    def path_item(self, drive_id: str | None, path: str) -> dict:
        """The item at a drive-relative PATH, same three-valued contract as `item`.

        Used for the destination collision check and for destination reachability, which are the
        two questions a path answers better than an id: neither the archive root nor a
        would-be-colliding sibling has an id ACP knows in advance.
        """
        clean = "/".join(p for p in str(path or "").split("/") if p)
        if not clean:
            return {"found": None, "item": None, "detail": "No path was given."}
        url = f"{self._base(drive_id)}/root:/{clean}?$select={self._ITEM_SELECT}"
        return self.item_from(url)

    def item_from(self, url: str) -> dict:
        try:
            data = self._graph_get(url)
        except PermissionError as e:
            return {"found": None, "item": None, "detail": f"Microsoft Graph refused the read: {e}"[:300]}
        except Exception as e:  # noqa: BLE001
            if _looks_like_404(e):
                return {"found": False, "item": None, "detail": "Nothing exists at that path."}
            return {"found": None, "item": None, "detail": f"{type(e).__name__}: {e}"[:300]}
        if not isinstance(data, dict) or not data.get("id"):
            return {"found": None, "item": None,
                    "detail": "Microsoft Graph returned a shape ACP does not recognise."}
        return {"found": True, "item": data, "detail": ""}

    def hold_state(self, drive_id: str | None, item_id: str) -> dict:
        """Legal-hold / retention / records state, in api/sp_writeback.py's own shape.

        Reused rather than re-derived: `sp_writeback.read_state` already reads exactly the three
        columns the decision turns on and already never raises. Its `checked: False` — "we did not
        look" — is what archive_autofire.preflight turns into an UNKNOWN and routes to a human,
        which is the opposite of what sp_writeback does with the same value and is the difference
        between an approved single write and an unattended queue.
        """
        import sp_writeback
        return sp_writeback.read_state(self._token, drive_id, item_id, get=self._get)

    def audience_ok(self, drive_id: str | None, item_id: str) -> bool | None:
        """Can the document's audience still reach the REPLACEMENT?

        Answered from the replacement's own permission grants: ACP compares the sharing reach of
        the two items rather than enumerating people, because enumerating a tenant's membership
        is neither in scope nor something a read-only connector can do reliably. A replacement
        that is not shared at all, where the original was, would strand its readers — and that is
        the case this catches. Anything unreadable is None, never True.
        """
        url = f"{self._base(drive_id)}/items/{item_id}/permissions?$select=id,roles,link,grantedToV2"
        try:
            data = self._graph_get(url)
        except Exception:  # noqa: BLE001 — an unreadable permission list is not an empty one
            return None
        if not isinstance(data, dict) or not isinstance(data.get("value"), list):
            return None
        return bool(data["value"])

    # ── the move ─────────────────────────────────────────────────────────────

    def ensure_folder_path(self, drive_id: str | None, path: str) -> str:
        """Find-or-create every segment of `path`, returning the deepest folder's id.

        This is what preserves the original hierarchy beneath the archive root: the destination
        `Archive/Policies/2024/x.docx` needs `Archive`, then `Policies`, then `2024` to exist, and
        creating them one level at a time is the only way Graph will do it without a path-based
        upload. Find-first at every level, `conflictBehavior: fail` on the create, and a 409
        re-reads instead of failing — two runs archiving into the same folder concurrently is
        ordinary, and it is exactly how duplicate mirror folders got created elsewhere.
        """
        parent = ""
        for segment in [p for p in str(path or "").split("/") if p]:
            parent = self._child_folder(drive_id, parent, segment)
        return parent

    def _child_folder(self, drive_id: str | None, parent_id: str, name: str) -> str:
        base = self._base(drive_id)
        container = f"{base}/items/{parent_id}" if parent_id else f"{base}/root"
        children = f"{container}/children"
        found = self._find_child_folder(children, name)
        if found:
            return found
        status, body = self._graph_post(children, {
            "name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
        if status in (401, 403):
            raise ArchiveSourceError(PERMISSION, (
                f"Microsoft Graph refused to create the archive folder '{name}'. Creating it needs "
                f"a write scope (Files.ReadWrite.All / Sites.ReadWrite.All). Nothing was moved."))
        if status == 409:
            again = self._find_child_folder(children, name)
            if again:
                return again
            raise ArchiveSourceError(COLLISION, (
                f"'{name}' already exists at the destination but is not a folder, so the archive "
                f"hierarchy cannot be created there. Nothing was moved."))
        if not (200 <= int(status or 0) < 300) or not isinstance(body, dict) or not body.get("id"):
            raise ArchiveSourceError(classify_http(status), (
                f"Creating the archive folder '{name}' failed (HTTP {status}). Nothing was moved."))
        return body["id"]

    def _find_child_folder(self, children_url: str, name: str) -> str:
        try:
            listing = self._graph_get(f"{children_url}?$select=id,name,folder&$top=200")
        except Exception:  # noqa: BLE001 — a failed lookup falls through to the create, which
            return ""      # is itself conflict-safe; it never falls through to an overwrite.
        for item in (listing or {}).get("value", []) if isinstance(listing, dict) else []:
            if item.get("name") == name and "folder" in item:
                return item.get("id") or ""
        return ""

    def move(self, *, drive_id: str | None, item_id: str, etag: str | None,
             destination_path: str) -> dict:
        """Move one item to `destination_path`. Returns a VERIFICATION, never a bare success.

        `{"verified": True|False|None, "destination_item_id", "destination_url",
          "destination_path", "detail"}` — and the None is the one that matters. A PATCH whose
        response ACP cannot read has not told us whether the file moved, and both answers are
        consequential: retry and it might move twice, report success and it might be lost. The
        caller turns None into recovery-required and stops.

        Raises ArchiveSourceError for failures that are classifiable — permission, collision,
        throttling, a stale eTag — because those have specific handling upstream and a generic
        "it failed" would collapse them into one.
        """
        folder = posixpath.dirname(destination_path)
        name = posixpath.basename(destination_path)
        if not name:
            raise ArchiveSourceError(AMBIGUOUS, "The destination path names no file.")
        parent_id = self.ensure_folder_path(drive_id, folder) if folder else ""
        body = {"name": name, "@microsoft.graph.conflictBehavior": "fail"}
        if parent_id:
            body["parentReference"] = {"id": parent_id}
        status, data = self._graph_patch(f"{self._base(drive_id)}/items/{item_id}", body, etag=etag)
        status = int(status or 0)
        if status in (401, 403):
            raise ArchiveSourceError(PERMISSION, (
                "Microsoft Graph refused the move. The source document was left untouched."))
        if status == 409:
            raise ArchiveSourceError(COLLISION, (
                "An item already exists at the destination path. ACP never overwrites one, so the "
                "source document was left untouched."))
        if status == 412:
            # if-match failed: the document changed between the preflight read and the PATCH.
            raise ArchiveSourceError("source_changed", (
                "The document changed between the safety checks and the move, so the move was "
                "refused. The source document was left untouched and will be re-evaluated."))
        if status == 429 or status >= 500:
            raise ArchiveSourceError(RATE_LIMITED, (
                f"Microsoft Graph returned {status}. The move was not performed; it will be "
                f"retried under the same idempotency key."))
        if not 200 <= status < 300:
            raise ArchiveSourceError(AMBIGUOUS, f"The move failed (HTTP {status}).")
        moved = data if isinstance(data, dict) else {}
        if not moved.get("id"):
            return {"verified": None, "destination_item_id": "", "destination_url": "",
                    "destination_path": destination_path,
                    "detail": ("Microsoft Graph accepted the move but returned no item, so it is "
                               "not known whether the document moved.")}
        return self.verify(drive_id=drive_id, item_id=moved["id"], expected_parent=parent_id,
                           expected_name=name, destination_path=destination_path,
                           moved_url=moved.get("webUrl") or "")

    def verify(self, *, drive_id: str | None, item_id: str, expected_parent: str,
               expected_name: str, destination_path: str, moved_url: str = "") -> dict:
        """Re-read the item after the move and check it is where the move claimed to put it.

        A separate read rather than trust in the PATCH response, because the PATCH response is the
        provider describing its own intent. This is the only thing that makes "successful moves
        are verified" a claim rather than an assumption — and an unreadable verification is
        `verified: None`, which is recovery-required, not a pass.
        """
        seen = self.item(drive_id, item_id)
        if seen["found"] is None:
            return {"verified": None, "destination_item_id": item_id, "destination_url": moved_url,
                    "destination_path": destination_path,
                    "detail": ("The move was accepted but the document could not be re-read "
                               "afterwards, so its location is not confirmed. " + seen["detail"])}
        if seen["found"] is False:
            return {"verified": False, "destination_item_id": item_id, "destination_url": moved_url,
                    "destination_path": destination_path,
                    "detail": "The move was accepted but the document is not at the destination."}
        item = seen["item"] or {}
        parent = (item.get("parentReference") or {}).get("id") or ""
        if expected_parent and parent != expected_parent:
            return {"verified": False, "destination_item_id": item_id,
                    "destination_url": item.get("webUrl") or moved_url,
                    "destination_path": destination_path,
                    "detail": "The document is not in the folder the move targeted."}
        if item.get("name") != expected_name:
            return {"verified": False, "destination_item_id": item_id,
                    "destination_url": item.get("webUrl") or moved_url,
                    "destination_path": destination_path,
                    "detail": (f"The document is named {item.get('name')!r} at the destination, "
                               f"not {expected_name!r}.")}
        return {"verified": True, "destination_item_id": item_id,
                "destination_url": item.get("webUrl") or moved_url,
                "destination_path": destination_path,
                "detail": "Verified at the destination after the move."}


def _looks_like_404(exc: Exception) -> bool:
    """Is this exception Graph saying 'not found' rather than 'I could not tell you'?

    Read off the exception rather than a status attribute because `_sp_get` raises through
    httpx's `raise_for_status`, whose exception carries the response, while an injected test
    transport raises whatever it likes. A wrong answer here is safe in one direction only: a
    missed 404 becomes UNKNOWN, which routes to a human. A false 404 would cancel an action that
    should have been reviewed, so the match is deliberately narrow.
    """
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if status == 404:
        return True
    return status is None and "404" in str(exc) and "not found" in str(exc).lower()


def probe(source: GraphArchiveSource, *, snapshot: dict, evidence: dict,
          destination_path: str, destination_drive_id: str | None = None) -> dict:
    """Every live fact archive_autofire.preflight needs, gathered in one place.

    Deliberately gathers ALL of them rather than short-circuiting on the first failure: a person
    sent this item for review needs the whole picture, and "the destination was also unreachable"
    is the difference between fixing one thing and fixing one thing then coming back.
    """
    drive_id = snapshot.get("drive_id")
    dest_drive = destination_drive_id if destination_drive_id is not None else drive_id
    live: dict = {}

    seen = source.item(drive_id, snapshot.get("source_item_id") or "")
    live["source_exists"] = seen["found"]
    live["source_item_id"] = (seen["item"] or {}).get("id") if seen["item"] else None
    # Two different markers, for two different guards. `source_marker` is the last-modified time,
    # which is what the evaluation recorded and therefore the only value the snapshot can be
    # compared against; `source_etag` is the concurrency token the PATCH sends as `if-match`,
    # which closes the window between the check and the move. Neither substitutes for the other.
    live["source_marker"] = (seen["item"] or {}).get("lastModifiedDateTime") if seen["item"] else None
    live["source_etag"] = (seen["item"] or {}).get("eTag") if seen["item"] else None
    live["source_detail"] = seen["detail"]

    replacement_id = evidence.get("replacement_item_id") or ""
    replacement_drive = evidence.get("replacement_drive_id") or drive_id
    rep = source.item(replacement_drive, replacement_id)
    live["replacement_exists"] = rep["found"]
    live["replacement_modified"] = (rep["item"] or {}).get("lastModifiedDateTime") if rep["item"] else None
    live["replacement_audience_ok"] = (
        source.audience_ok(replacement_drive, replacement_id) if rep["found"] else None)

    live["hold"] = source.hold_state(drive_id, snapshot.get("source_item_id") or "")

    root = posixpath.dirname(destination_path)
    if root:
        found_root = source.path_item(dest_drive, root)
        # A destination that does NOT exist yet is reachable — ACP creates the hierarchy. Only an
        # unreadable answer is unknown, and only a drive that refuses the read is unreachable.
        live["destination_reachable"] = True if found_root["found"] is not None else None
        live["destination_reachable_detail"] = found_root["detail"]
    else:
        live["destination_reachable"] = None
        live["destination_reachable_detail"] = "No archive destination folder was resolved."

    collision = source.path_item(dest_drive, destination_path)
    live["destination_collision"] = (None if collision["found"] is None
                                     else bool(collision["found"]))
    live["destination_collision_detail"] = (
        (collision["item"] or {}).get("name") if collision["found"] else collision["detail"])
    return live
