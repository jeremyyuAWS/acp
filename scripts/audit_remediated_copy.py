#!/usr/bin/env python3
"""Audit downloaded source/corrected files locally without tokens or provider writes."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from remediated_copy_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('corrected', type=Path)
    parser.add_argument('--expected', type=Path, help='JSON with corrected_sha256 and/or exact images.')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected.read_text()) if args.expected else {}
    report = audit(args.original.read_bytes(), args.corrected.read_bytes(),
                   args.original.suffix, expected_sha256=expected.get('corrected_sha256'),
                   expected_images=expected.get('images'))
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return 0 if report['supplied_claims_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
