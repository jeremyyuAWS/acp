"""Bounded, content-free explanations of the actual corrected-copy assessment."""
import io
import re


def verification_event_detail(verification, diffs, data, filename):
    manual = []
    if verification.ok and '1.3.1' in verification.residual and filename.lower().endswith('.pdf'):
        try:
            import pikepdf
            with pikepdf.open(io.BytesIO(data), attempt_recovery=False) as pdf:
                if '/StructTreeRoot' not in pdf.Root:
                    manual.append({'criterion': '1.3.1', 'reason_code': 'pdf_structure_tagging_required'})
        except Exception:
            # Unreadable bytes establish no structural diagnosis.
            pass
    manual_ids = {row['criterion'] for row in manual}
    failed = []
    for criterion in sorted({str(d.get('rule_id', '')) for d in diffs}):
        if not re.fullmatch(r'\d+\.\d+\.\d+', criterion) or criterion in manual_ids:
            continue
        if not verification.cleared({criterion}):
            failed.append({'criterion': criterion, 'reason_code':
                           'criterion_still_failing' if verification.ok else 'verification_unavailable'})
    return {'failed_criteria': failed, 'manual_criteria': manual}
