#!/usr/bin/env python3
"""Validate evidence offline; --ingest performs an explicit operator database write."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from ai_review_calibration import ingest_evaluation, normalize_evaluation, normalize_admin, ADMIN_KEY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--dataset', type=Path, help='Dataset artifact whose SHA256 matches evaluated provenance')
    parser.add_argument('--report', type=Path, help='Independent evaluation report whose SHA256 matches provenance')
    parser.add_argument('--owner', help='Required owner identity for evaluation ingestion')
    parser.add_argument('--administrator', action='store_true', help='Validate administrator family configuration instead')
    parser.add_argument('--ingest', action='store_true', help='Write to the configured application database')
    args = parser.parse_args()
    value = json.loads(args.input.read_text())
    result = normalize_admin(value) if args.administrator else normalize_evaluation(value)
    if args.ingest:
        if not args.administrator and not args.owner:
            parser.error('--owner is required for ingestion')
        if not args.administrator and result['provenance']['kind'] == 'evaluated':
            for path, field in ((args.dataset, 'dataset_sha256'), (args.report, 'evaluation_report_sha256')):
                if path is None or not path.is_file():
                    parser.error('Evaluated ingestion requires --dataset and --report artifacts')
                if hashlib.sha256(path.read_bytes()).hexdigest() != result['provenance'][field]:
                    parser.error('Evaluation artifact digest does not match recorded provenance: ' + field)
        from store import Store
        store = Store()
        if args.administrator:
            store.set_setting(ADMIN_KEY, json.dumps(result, sort_keys=True))
        else:
            result = ingest_evaluation(store, args.owner, value)
    print(json.dumps({'validated':True, 'ingested':args.ingest,
                      'evaluation_version':result.get('evaluation_version'),
                      'sample_size':result.get('sample_size'),
                      'reliability_lower_bound':result.get('reliability_lower_bound'),
                      'provenance':result.get('provenance')}, indent=2))


if __name__ == '__main__':
    main()
