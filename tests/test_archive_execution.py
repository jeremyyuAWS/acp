"""Archive auto-fire against a real store and a fake tenant — the execution-semantics criteria.

WHY A FAKE GRAPH RATHER THAN A MOCK OF THE MODULE UNDER TEST. Every interesting case here is a
provider behaviour ACP must survive: a 429, a 412 on the eTag, a PATCH that returns nothing, a
verification read that disagrees with the move. None of those can be produced on demand against a
live tenant, and mocking `archive_sources` would test that this module calls a function rather
than that it handles what the function returns. So the transport is faked at the HTTP seam and
everything above it — classification, verification, routing, the audit row — is the real code.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import archive_autofire as af  # noqa: E402
import archive_execution  # noqa: E402
import archive_sources  # noqa: E402

OWNER = "owner@example.com"
NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)

OLD = {"id": "item-old", "eTag": "etag-old", "name": "Clinical-Access-v2.docx",
       "lastModifiedDateTime": "2024-01-01T00:00:00Z", "webUrl": "https://x/old",
       "parentReference": {"id": "folder-2024"}}
NEW = {"id": "item-new", "eTag": "etag-new", "name": "Clinical-Access-v3.docx",
       "lastModifiedDateTime": "2025-01-01T00:00:00Z", "webUrl": "https://x/new",
       "parentReference": {"id": "folder-2025"}}


_UNSET = object()


class FakeGraph:
    """A drive that answers the handful of shapes this feature reads and writes.

    Deliberately keyed by item id and by path, because those are the two ways the code addresses
    an item and a double that only supported one would silently pass the half it covered.
    """

    def __init__(self, *, items=None, paths=None, permissions=True, hold=_UNSET):
        self.items = dict(items or {"item-old": dict(OLD), "item-new": dict(NEW)})
        self.paths = dict(paths or {})
        self.permissions = permissions
        # A SENTINEL, not `or`/`is not None`: `hold=None` is the case under test — a tenant that
        # will not return the listItem at all — and a default that swallowed it would make
        # test_retention_uncertainty_fails_closed exercise the happy path while reading as if it
        # covered the refusal.
        self.hold = {"CheckoutUser": None, "_IsRecord": False} if hold is _UNSET else hold
        self.folders = {"Archive": "folder-archive", "Archive/Policies": "folder-pol",
                        "Archive/Policies/2024": "folder-dest"}
        self.patched = []
        self.patch_status = 200
        self.patch_body = None

    # ── reads ────────────────────────────────────────────────────────────────
    def get(self, token, url):
        base = url.split("?")[0]
        if "/listItem" in base:
            return {"fields": dict(self.hold)} if self.hold is not None else {}
        if "/permissions" in base:
            return {"value": [{"id": "p1", "roles": ["read"]}] if self.permissions else []}
        if base.endswith("/children") or "/children" in base:
            parent = base.split("/items/")[-1].split("/children")[0] if "/items/" in base else "root"
            return {"value": [{"id": v, "name": k.split("/")[-1], "folder": {}}
                              for k, v in self.folders.items()
                              if self._parent_of(k) == parent]}
        if "/root:/" in base:
            path = base.split("/root:/", 1)[1]
            if path in self.paths:
                return self.paths[path]
            raise _NotFound()
        if "/items/" in base:
            item_id = base.split("/items/")[-1]
            if item_id in self.items:
                return self.items[item_id]
            raise _NotFound()
        raise _NotFound()

    def _parent_of(self, folder_path):
        parent = "/".join(folder_path.split("/")[:-1])
        return self.folders.get(parent, "root") if parent else "root"

    # ── writes ───────────────────────────────────────────────────────────────
    def post(self, token, url, body):
        name = body.get("name")
        return 201, {"id": f"folder-{name}", "name": name, "folder": {}}

    def patch(self, token, url, body, etag):
        item_id = url.split("/items/")[-1]
        self.patched.append({"item": item_id, "body": body, "etag": etag})
        if self.patch_status != 200:
            return self.patch_status, {}
        if self.patch_body is not None:
            return 200, self.patch_body
        moved = dict(self.items[item_id])
        moved["name"] = body.get("name", moved["name"])
        moved["parentReference"] = body.get("parentReference", moved["parentReference"])
        self.items[item_id] = moved
        return 200, moved

    def source(self):
        return archive_sources.GraphArchiveSource("token", get=self.get, post=self.post,
                                                  patch=self.patch)


class _NotFound(Exception):
    def __init__(self):
        super().__init__("404 not found")


def _seed(store, *, scan_id="s1", owner=OWNER, source="sharepoint", supersedes="item-old",
          rule_id="r1", extra_pairs=0):
    """A scan with one archive candidate and one replacement that names it.

    `extra_pairs` adds further superseded/replacement pairs, for the tests that need a QUEUE
    rather than a single item — the kill switch and the per-run ceiling are only meaningful when
    there is a second item for them to stop.
    """
    store.enqueue_scan(scan_id, source, owner, "scan_sharepoint", {})
    store.init_scan_run(scan_id, source, 2 + 2 * extra_pairs, "2026-09-01T00:00:00Z", "default",
                        "rh", owner=owner, status="done")
    rows = [
        {"file": "Clinical-Access-v2.docx", "drive_file_id": "item-old", "drive_id": "d1",
         "path": "Policies/2024/Clinical-Access-v2.docx", "mime": "docx", "size_kb": 10,
         "doc_class": "word-document", "source_modified": "2024-01-01T00:00:00Z"},
        {"file": "Clinical-Access-v3.docx", "drive_file_id": "item-new", "drive_id": "d1",
         "path": "Policies/2025/Clinical-Access-v3.docx", "mime": "docx", "size_kb": 11,
         "doc_class": "word-document", "source_modified": "2025-01-01T00:00:00Z",
         "sp_metadata": json.dumps({"values": {"Supersedes": supersedes}})},
    ]
    for n in range(extra_pairs):
        rows += [
            {"file": f"Extra-{n}-v1.docx", "drive_file_id": f"extra-old-{n}", "drive_id": "d1",
             "path": f"Policies/2024/Extra-{n}-v1.docx", "mime": "docx", "size_kb": 10,
             "doc_class": "word-document", "source_modified": "2024-01-01T00:00:00Z"},
            {"file": f"Extra-{n}-v2.docx", "drive_file_id": f"extra-new-{n}", "drive_id": "d1",
             "path": f"Policies/2025/Extra-{n}-v2.docx", "mime": "docx", "size_kb": 10,
             "doc_class": "word-document", "source_modified": "2025-01-01T00:00:00Z",
             "sp_metadata": json.dumps({"values": {"Supersedes": f"extra-old-{n}"}})},
        ]
    store.add_inventory(scan_id, rows)
    # add_inventory deliberately does not write lifecycle_status (it is the rule evaluator's), so
    # the candidates are stamped the way a discover-time rule pass stamps them.
    for row in rows:
        if row["drive_file_id"].endswith("-old") or "-old-" in row["drive_file_id"]:
            store.set_lifecycle_status(scan_id, row["file"], "Archive Candidate",
                                       rule_id=rule_id, reason="matched archive rule")
    # policy_id is a global primary key, so a second tenant seeding the same fixture needs its
    # own rule id — an ordinary uniqueness fact, not a tenancy one.
    if not any(p["policy_id"] == rule_id for p in store.list_disposition_policies(owner)):
        store.create_disposition_policy(rule_id, name="Superseded clinical policies", match="[]",
                                        action="archive", action_config="{}",
                                        requires_approval=True, enabled=True, owner_email=owner)
    return scan_id


def _policy(**over):
    base = {"enabled": True, "dry_run": False, "archive_root": "Archive",
            "source_connections": ["sharepoint:d1"], "rule_ids": ["r1"],
            "required_evidence": [af.METADATA_LINK], "min_replacement_age_days": 30,
            "max_actions_per_run": 25, "max_actions_per_day": 100}
    base.update(over)
    return af.normalize_policy(base)


@pytest.fixture()
def seeded(isolated_store):
    _seed(isolated_store)
    return isolated_store


# ── Evaluation ───────────────────────────────────────────────────────────────

def test_evidence_is_derived_from_what_the_scan_already_recorded(seeded):
    seeded.set_archive_policy(OWNER, _policy(), actor=OWNER)
    report = archive_execution.evaluate(seeded, OWNER, "s1", now=NOW)
    item = next(i for i in report["items"] if i["file"] == "Clinical-Access-v2.docx")
    assert item["state"] == af.ELIGIBLE_AUTO
    assert item["evidence"][0]["type"] == af.METADATA_LINK
    assert item["destination_path"] == "Archive/Policies/2024/Clinical-Access-v2.docx"


def test_without_the_supersedes_column_the_same_estate_is_recommendation_only(isolated_store):
    """The SAME two documents, the same age, the same rule — minus the tenant's own link."""
    _seed(isolated_store, supersedes="")
    isolated_store.set_archive_policy(OWNER, _policy(), actor=OWNER)
    report = archive_execution.evaluate(isolated_store, OWNER, "s1", now=NOW)
    item = next(i for i in report["items"] if i["file"] == "Clinical-Access-v2.docx")
    assert item["state"] == af.RECOMMEND_ONLY


def test_a_tenant_cannot_evaluate_another_tenants_scan(seeded):
    seeded.set_archive_policy("intruder@example.com", _policy(), actor="intruder@example.com")
    report = archive_execution.evaluate(seeded, "intruder@example.com", "s1", now=NOW)
    assert report["items"] == []


def test_the_stored_default_policy_keeps_a_proven_pair_as_a_recommendation(seeded):
    """No policy stored at all — the tenant that has never configured this."""
    report = archive_execution.evaluate(seeded, OWNER, "s1", now=NOW)
    item = next(i for i in report["items"] if i["file"] == "Clinical-Access-v2.docx")
    assert item["state"] == af.RECOMMEND_ONLY
    assert "switched off" in item["reason"]


# ── Execution ────────────────────────────────────────────────────────────────

def _run(store, graph, *, policy=None, owner=OWNER, scan_id="s1"):
    store.set_archive_policy(owner, policy or _policy(), actor=owner)
    return archive_execution.run(store, owner, scan_id, source_factory=lambda c: graph.source(),
                                 actor=owner, now=NOW)


def test_a_proven_supersession_moves_and_is_verified(seeded):
    graph = FakeGraph()
    report = _run(seeded, graph)
    assert report["completed"] == 1 and report["blocked"] == 0
    execution = report["executions"][0]
    assert execution["state"] == af.ARCHIVED
    assert execution["destination_item_id"] == "item-old"
    assert graph.patched[0]["body"]["@microsoft.graph.conflictBehavior"] == "fail"
    assert graph.patched[0]["etag"] == "etag-old"


def test_an_identical_submission_creates_one_execution(seeded):
    graph = FakeGraph()
    first = _run(seeded, graph)
    second = _run(seeded, graph)
    assert first["completed"] == 1
    # The second run finds the decision already executed, so nothing is eligible and nothing moves.
    assert second["eligible"] == 0
    assert len(graph.patched) == 1
    assert len(seeded.list_archive_executions(OWNER)) == 1


def test_a_source_changed_since_evaluation_prevents_the_move(seeded):
    graph = FakeGraph()
    graph.items["item-old"]["lastModifiedDateTime"] = "2026-09-04T00:00:00Z"
    report = _run(seeded, graph)
    assert report["completed"] == 0
    assert graph.patched == []
    assert "out of date" in report["executions"][0]["detail"]


def test_retention_uncertainty_fails_closed(seeded):
    """A tenant that will not answer the listItem read. Nothing moves, and the row says why."""
    graph = FakeGraph(hold=None)
    report = _run(seeded, graph)
    assert graph.patched == []
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "not known whether a hold blocks" in report["executions"][0]["detail"]


def test_a_declared_record_is_never_moved(seeded):
    graph = FakeGraph(hold={"CheckoutUser": None, "_IsRecord": True, "_ComplianceTag": "7-year"})
    report = _run(seeded, graph)
    assert graph.patched == []
    assert report["executions"][0]["state"] == af.BLOCKED


def test_a_destination_collision_never_overwrites(seeded):
    graph = FakeGraph(paths={"Archive/Policies/2024/Clinical-Access-v2.docx":
                             {"id": "already-there", "name": "Clinical-Access-v2.docx"}})
    report = _run(seeded, graph)
    assert graph.patched == []
    assert "already exists at the destination" in report["executions"][0]["detail"]


def test_a_destination_that_cannot_be_read_is_unknown_rather_than_free(seeded):
    """A refused path read says nothing about whether something is already there.

    Distinct from the collision test above and worth its own case: that one proves ACP does not
    overwrite what it CAN see, and this one proves it does not proceed on what it cannot. A probe
    that collapsed the refusal into "nothing there" would pass the collision test unchanged.
    """
    graph = FakeGraph()
    real_get = graph.get

    def refuse_paths(token, url):
        if "/root:/" in url:
            raise PermissionError("Access denied")
        return real_get(token, url)

    graph.get = refuse_paths
    report = _run(seeded, graph)
    assert graph.patched == []
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "could not be established whether the destination path is free" in \
        report["executions"][0]["detail"]


def test_a_permission_failure_leaves_the_source_untouched_and_asks_for_review(seeded):
    graph = FakeGraph()
    graph.patch_status = 403
    report = _run(seeded, graph)
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "refused the move" in report["executions"][0]["detail"]


def test_a_stale_etag_at_the_moment_of_the_move_cancels(seeded):
    """The window between preflight and PATCH, closed by if-match rather than by hope."""
    graph = FakeGraph()
    graph.patch_status = 412
    report = _run(seeded, graph)
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "changed between the safety checks and the move" in report["executions"][0]["detail"]


def test_throttling_is_retryable_under_the_same_key_and_is_not_a_failure(seeded):
    graph = FakeGraph()
    graph.patch_status = 429
    report = _run(seeded, graph)
    execution = report["executions"][0]
    assert execution["state"] == af.ELIGIBLE_AUTO and execution["attempts"] == 1
    assert execution["completed_at"] in (None, "")


def test_an_ambiguous_provider_response_is_recovery_required_never_completed(seeded):
    graph = FakeGraph()
    graph.patch_body = {}
    report = _run(seeded, graph)
    assert report["executions"][0]["state"] == af.RECOVERY_REQUIRED
    assert report["completed"] == 0


def test_a_move_that_lands_somewhere_else_is_not_reported_as_completed(seeded):
    """The verification read disagreeing with the PATCH — the case that makes verification real."""
    graph = FakeGraph()
    graph.patch_body = {"id": "item-old", "name": "Something-Else.docx",
                        "parentReference": {"id": "folder-dest"}, "webUrl": "https://x/moved"}
    report = _run(seeded, graph)
    assert report["executions"][0]["state"] == af.RECOVERY_REQUIRED


def test_dry_run_checks_everything_and_moves_nothing(seeded):
    graph = FakeGraph()
    report = _run(seeded, graph, policy=_policy(dry_run=True))
    assert graph.patched == []
    execution = report["executions"][0]
    assert execution["state"] == af.ELIGIBLE_AUTO
    assert "every safety check passed" in execution["detail"]
    assert json.loads(execution["preflight_json"])["route"] == "proceed"


def test_the_kill_switch_stops_new_moves_immediately(isolated_store):
    """Thrown BETWEEN items, not between runs — the property the PRD calls "immediately".

    Written against real stored state rather than by patching the loader: an operator turning the
    switch on writes to the policy row, and the guarantee is that the run notices that row inside
    the queue. A patched loader would prove the loop calls a function, which is not the claim.
    """
    store = isolated_store
    _seed(store, extra_pairs=2)
    store.set_archive_policy(OWNER, _policy(), actor=OWNER)
    graph = FakeGraph(items={f"{side}-{n}": {"id": f"{side}-{n}", "eTag": f"e-{side}-{n}",
                                             "name": f"Extra-{n}-v{1 if side=='extra-old' else 2}.docx",
                                             "lastModifiedDateTime":
                                                 "2024-01-01T00:00:00Z" if side == "extra-old"
                                                 else "2025-01-01T00:00:00Z",
                                             "webUrl": "https://x", "parentReference": {"id": "p"}}
                             for side in ("extra-old", "extra-new") for n in (0, 1)}
                      | {"item-old": dict(OLD), "item-new": dict(NEW)})

    def factory(connection):
        # Called once per item, after that item's kill-switch read — so flipping here turns the
        # switch on partway through a real queue, which is exactly the operator's timing.
        policy = archive_execution.load_policy(store, OWNER)
        policy["kill_switch"] = True
        store.set_archive_policy(OWNER, policy, actor=OWNER)
        return graph.source()

    report = archive_execution.run(store, OWNER, "s1", source_factory=factory, actor=OWNER,
                                   now=NOW)
    assert report["eligible"] == 3
    # NOT ONE MOVE. The switch is read a second time inside preflight, which closes the window
    # between the loop's check and the PATCH: the item that was mid-flight when the switch was
    # thrown is failed EXPLICITLY, with a row saying why, rather than moved. Every item after it
    # is never started at all.
    assert graph.patched == []
    assert len(report["executions"]) == 1
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "kill switch is on" in report["executions"][0]["detail"]
    assert "kill switch was turned on" in report["stopped"]


def test_no_connection_for_a_source_is_a_truthful_blocked_row_not_a_crash(seeded):
    seeded.set_archive_policy(OWNER, _policy(), actor=OWNER)
    report = archive_execution.run(seeded, OWNER, "s1", source_factory=lambda c: None,
                                   actor=OWNER, now=NOW)
    assert report["executions"][0]["state"] == af.BLOCKED
    assert "No connection is available" in report["executions"][0]["detail"]


def test_the_daily_ceiling_counts_moves_that_happened_not_rows_that_were_claimed(seeded):
    graph = FakeGraph()
    _run(seeded, graph)
    assert seeded.archive_actions_today(OWNER) == 1
    # A dry run spends no budget: it moved nothing.
    _seed(seeded, scan_id="s2")
    _run(seeded, FakeGraph(), policy=_policy(dry_run=True), scan_id="s2")
    assert seeded.archive_actions_today(OWNER) == 1


# ── Audit trail ──────────────────────────────────────────────────────────────

def test_the_audit_row_records_everything_the_prd_requires(seeded):
    report = _run(seeded, FakeGraph())
    row = report["executions"][0]
    assert row["actor"] == OWNER
    assert row["snapshot_id"] and seeded.get_archive_snapshot(row["snapshot_id"], OWNER)
    assert row["policy_id"] == "r1"
    assert row["source_item_id"] == "item-old" and row["replacement_item_id"] == "item-new"
    assert json.loads(row["evidence_json"])[0]["type"] == af.METADATA_LINK
    assert json.loads(row["preflight_json"])["route"] == "proceed"
    assert row["destination_path"] == "Archive/Policies/2024/Clinical-Access-v2.docx"
    assert row["created_at"] and row["started_at"] and row["completed_at"]
    assert row["state"] == af.ARCHIVED and row["detail"]


def test_the_snapshot_resolves_to_the_policy_that_authorised_the_move(seeded):
    report = _run(seeded, FakeGraph())
    snapshot = seeded.get_archive_snapshot(report["snapshot_id"], OWNER)
    assert snapshot["policy"]["archive_root"] == "Archive"
    assert "kill_switch" not in snapshot["policy"]


def test_lifecycle_events_are_bounded_and_carry_no_document_content(seeded):
    _run(seeded, FakeGraph())
    events = seeded.list_orchestration_events(owner_email=OWNER, limit=50)
    kinds = {e["kind"] for e in events}
    assert "lifecycle.archive_run_started" in kinds
    assert "lifecycle.archive_item_completed" in kinds
    for event in events:
        detail = json.loads(event.get("detail_json") or "{}")
        assert set(detail) <= set(af.EVENT_KEYS)


def test_a_reset_removes_execution_records(seeded):
    _run(seeded, FakeGraph())
    assert seeded.list_archive_executions(OWNER)
    seeded.reset_analytics()
    assert seeded.list_archive_executions(OWNER) == []
    # The RULE survives, on this repo's existing rule/record split.
    assert seeded.get_archive_policy(OWNER) is not None


def test_per_user_deletion_removes_only_that_users_executions(seeded):
    _run(seeded, FakeGraph())
    _seed(seeded, scan_id="s9", owner="other@example.com", rule_id="r9")
    seeded.set_archive_policy("other@example.com", _policy(rule_ids=["r9"]),
                              actor="other@example.com")
    archive_execution.run(seeded, "other@example.com", "s9",
                          source_factory=lambda c: FakeGraph().source(),
                          actor="other@example.com", now=NOW)
    seeded.reset_user_data(OWNER)
    assert seeded.list_archive_executions(OWNER) == []
    assert len(seeded.list_archive_executions("other@example.com")) == 1


def test_one_tenant_cannot_read_another_tenants_execution(seeded):
    report = _run(seeded, FakeGraph())
    execution_id = report["executions"][0]["execution_id"]
    assert seeded.get_archive_execution_by_id(execution_id, "intruder@example.com") is None
    assert seeded.list_archive_executions("intruder@example.com") == []


# ── The provider adapter's own contract ──────────────────────────────────────

def test_a_refused_read_is_unknown_rather_than_absent():
    """A 403 says nothing about whether the item exists, and must not be read as a deletion."""
    def refuse(token, url):
        raise PermissionError("Access denied")
    source = archive_sources.GraphArchiveSource("t", get=refuse)
    assert source.item("d1", "item-old")["found"] is None


def test_a_404_is_absence():
    def gone(token, url):
        raise _NotFound()
    source = archive_sources.GraphArchiveSource("t", get=gone)
    assert source.item("d1", "item-old")["found"] is False


def test_the_hierarchy_is_created_one_level_at_a_time_and_never_replaces():
    graph = FakeGraph()
    created = []
    graph.post = lambda token, url, body: (created.append(body) or (201, {"id": "f", **body}))
    source = graph.source()
    source.ensure_folder_path("d1", "Archive/Policies/2026")
    assert all(b["@microsoft.graph.conflictBehavior"] == "fail" for b in created)
