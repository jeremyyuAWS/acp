#!/usr/bin/env python3
"""Print reviewable non-secret relaxed AI configuration; never deploy or call APIs."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'api'))
from ai_model_profiles import PROFILES, RECOMMENDED_RUN_BUDGET_USD, model_config
from llm_waterfall_provider import TextModelSpec
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', required=True, choices=sorted(PROFILES))
    args = parser.parse_args()
    specs = [TextModelSpec(**s) for s in model_config(args.profile)]
    for spec in specs:
        spec.validate(time.time())
    print(json.dumps({
        'environment': {'ACP_BOUNDED_TEXT_PROFILE': args.profile},
        'future_run_policy': {'rule_based': 2, 'ai': 1,
                              'ai_budget_usd': RECOMMENDED_RUN_BUDGET_USD},
        'models': [{'model': s.model, 'maximum_reservation_usd': s.maximum_cost(),
                    'output_token_limit': s.output_token_limit} for s in specs],
        'requires': 'Selected provider enabled with a resolved credential; save policy with current revision.',
        'applied': False,
    }, indent=2))


if __name__ == '__main__':
    main()
