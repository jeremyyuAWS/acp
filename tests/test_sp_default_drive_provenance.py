"""Default OneDrive Graph alias retains the actual provider identity on inventory."""
import pytest
import scanner


def item(name='report.docx', drive='actual-drive'):
    parent = {'path': '/drive/root:/Documents'}
    if drive is not None:
        parent['driveId'] = drive
    return {'id': 'provider-item', 'name': name, 'file': {'mimeType': 'application/octet-stream'},
            'parentReference': parent, 'lastModifiedDateTime': '2026-09-12T00:00:00Z'}


def classify(raw, drive=None):
    return scanner._sp_classify_item(raw, drive_id=drive, skip_folders=set(),
                                     exts=scanner._sp_scannable_exts())


def test_default_alias_scannable_identity_survives_real_discovery_persistence(isolated_store):
    from handlers import _discover_norm_row, _discover_inventory_row
    classified = classify(item())['scannable']
    assert classified['driveId'] == 'actual-drive'
    # An actual OneDrive identity does not fabricate a SharePoint site/library.
    assert 'siteId' not in classified and 'libraryName' not in classified
    normalized = _discover_norm_row(classified)
    inventory = _discover_inventory_row(normalized)
    isolated_store.add_inventory('scan', [inventory])
    saved = isolated_store.list_inventory('scan')[0]
    assert saved['drive_id'] == 'actual-drive'
    assert saved['drive_file_id'] == 'provider-item'
    assert saved['source_modified'] == '2026-09-12T00:00:00Z'
    assert saved['site_id'] is None


def test_default_alias_non_scannable_files_keep_same_actual_identity():
    classified = classify(item('video.mp4'))
    assert classified['scannable'] is None
    assert classified['inventory_row']['drive_id'] == 'actual-drive'


def test_explicit_selected_drive_can_supply_missing_parent_drive_on_both_shapes():
    for name in ('report.docx', 'video.mp4'):
        classified = classify(item(name, drive=None), drive='selected-drive')
        row = classified['scannable'] or classified['inventory_row']
        assert (row.get('driveId') or row.get('drive_id')) == 'selected-drive'


def test_conflicting_drive_metadata_fails_instead_of_reassigning_item():
    with pytest.raises(ValueError, match='selected source library'):
        classify(item(), drive='other-selected-drive')


def test_unknown_drive_stays_unknown_no_guessed_site_or_drive():
    row = classify(item(drive=None))['scannable']
    assert 'driveId' not in row and 'siteId' not in row
