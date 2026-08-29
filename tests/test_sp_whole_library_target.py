"""scanner._sp_whole_library_target — is a SharePoint request narrow enough for delta
reconstruction (interactive scans, item 11)? Pure function, no I/O.

sp_delta_since is scoped to exactly ONE Graph drive and has no folder filter of its own, so the
only two eligible shapes are "no folder/folders at all" (the whole of the signed-in user's
OneDrive) and a single folder written "{driveId}/root" (Graph's own item-id alias for "the whole
of this one library", the same addressing the scheduled sweep already uses, #961). Everything
else — a bare site id, more than one location, a real sub-folder — is not eligible.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

DRIVE = "drv-1"
DRIVE2 = "drv-2"


def test_no_folder_or_folders_is_the_whole_onedrive():
    assert scanner._sp_whole_library_target(None, None) == (True, None)


def test_a_bare_root_sentinel_is_also_the_whole_onedrive():
    assert scanner._sp_whole_library_target("root", None) == (True, None)


def test_a_single_whole_library_folder_is_eligible():
    assert scanner._sp_whole_library_target(f"{DRIVE}/root", None) == (True, DRIVE)


def test_the_same_shape_via_the_folders_list_is_also_eligible():
    assert scanner._sp_whole_library_target(None, [f"{DRIVE}/root"]) == (True, DRIVE)


def test_a_bare_site_id_is_not_eligible():
    """Walks every library on the site — no single drive to scope a delta query to."""
    assert scanner._sp_whole_library_target("contoso.sharepoint.com,g1,g2", None) == (False, None)


def test_a_real_sub_folder_is_not_eligible():
    assert scanner._sp_whole_library_target(f"{DRIVE}/item123", None) == (False, None)


def test_more_than_one_location_is_not_eligible():
    assert scanner._sp_whole_library_target(
        None, [f"{DRIVE}/root", f"{DRIVE2}/root"]) == (False, None)


def test_folders_takes_precedence_over_folder_matching_lists_own_convention():
    """Same precedence _list() itself gives folders over the single folder param."""
    assert scanner._sp_whole_library_target(
        "some-other-value", [f"{DRIVE}/root"]) == (True, DRIVE)
