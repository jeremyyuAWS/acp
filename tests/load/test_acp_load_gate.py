import json
import unittest
from pathlib import Path

from performance.acp_load_gate import run_scenario


SCENARIO = Path(__file__).parent / "scenarios" / "next_week_gate.json"


def scenario():
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


class LoadGateTests(unittest.TestCase):
    def test_next_week_baseline_is_repeatable_and_truthfully_no_go(self):
        first = run_scenario(scenario())
        second = run_scenario(scenario())

        self.assertEqual(first, second)
        self.assertEqual(first["result"], "NO_GO")
        self.assertEqual(
            {failure["metric"] for failure in first["failures"]},
            {"queue_wait_seconds.p95", "end_to_end_seconds.p99"},
        )
        self.assertEqual(first["metrics"]["documents_submitted"], 1800)
        self.assertEqual(first["metrics"]["deploy_interruptions"], 12)
        self.assertEqual(first["metrics"]["deploy_interruptions_recovered"], 12)
        self.assertEqual(first["metrics"]["deploy_interruption_recovery_rate"], 1.0)
        self.assertGreater(first["metrics"]["redis_errors"], 0)
        self.assertGreater(first["metrics"]["database_errors"], 0)
        self.assertGreater(first["metrics"]["retries"], 0)

    def test_a_breached_threshold_produces_machine_readable_no_go(self):
        config = scenario()
        config["thresholds"] = [{
            "metric": "throughput_jobs_per_second", "operator": "min", "value": 999,
            "reason": "deliberate test breach",
        }]

        result = run_scenario(config)

        self.assertEqual(result["result"], "NO_GO")
        self.assertEqual(result["failures"], [{
            "metric": "throughput_jobs_per_second", "operator": "min", "threshold": 999.0,
            "actual": result["metrics"]["throughput_jobs_per_second"],
            "reason": "deliberate test breach",
        }])

    def test_invalid_fault_rate_is_rejected(self):
        config = scenario()
        config["faults"]["redis_error_rate"] = 1.1

        with self.assertRaisesRegex(ValueError, "redis_error_rate"):
            run_scenario(config)
