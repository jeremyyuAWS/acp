#!/usr/bin/env python3
"""Prepare real synthetic sources or score captured answers. No network or paid calls."""
from pathlib import Path
import argparse
import json
import sys
from hashlib import sha256
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evals.quality_first_benchmark import prepare, evaluate

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', type=Path, help='New directory for source fixtures and answer-free requests')
    action.add_argument('--responses', type=Path, help='Captured JSON answer array; never fabricated baseline scores')
    parser.add_argument('--candidate', default='')
    parser.add_argument('--prompt-revision', default='')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--manifest', type=Path, help='requests.json from the original prepared sources')
    args = parser.parse_args()
    if args.prepare:
        report = prepare(args.prepare)
        print(f"Prepared {len(report['requests'])} synthetic source files; no model calls or scores.")
        return 0
    if not args.output or not args.manifest:
        parser.error('--responses requires --output and --manifest')
    manifest = json.loads(args.manifest.read_text())
    for row in manifest['requests']:
        path = (args.manifest.parent / row['source_file']).resolve()
        if path.parent != args.manifest.parent.resolve() or sha256(path.read_bytes()).hexdigest() != row['source_sha256']:
            raise ValueError('prepared source file changed or escaped its directory')
    report = evaluate(json.loads(args.responses.read_text()), manifest=manifest, candidate=args.candidate, prompt_revision=args.prompt_revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(f"{report['probe_passes']}/{report['total']} structured probes passed; semantic review still required.")
    return 0 if report['probe_passes'] == report['total'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
