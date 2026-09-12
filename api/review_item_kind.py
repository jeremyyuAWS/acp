"""Optional inspection records describe work already performed, not new approvals."""

def optional_inspection(row):
    return row.get('rule_id') == 'auto/verify'


def serialize_review_item(row):
    if not optional_inspection(row):
        return row
    return {**row, 'inspection_only': True, 'review_required': False,
            'review_task_state': 'completed',
            'review_task_label': 'Automatic change recorded · inspection optional'}
