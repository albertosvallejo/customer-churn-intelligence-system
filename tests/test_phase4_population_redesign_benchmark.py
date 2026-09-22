import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.phase4_population_redesign_benchmark import (
    build_population_benchmark_payload,
    render_benchmark_html,
    render_decision_md,
)


class TestPhase4PopulationRedesignBenchmark(unittest.TestCase):
    def test_payload_contains_segments_and_decision(self):
        payload = build_population_benchmark_payload()
        self.assertEqual(payload["measurement_label"], "Portfolio decision benchmark")
        self.assertIn(payload["decision"], {"defer_v4_keep_v2c", "support_population_redesign_candidate"})
        self.assertGreaterEqual(payload["overall_baseline"]["customers"], 3000)
        self.assertTrue(payload["segment_summary"])
        self.assertGreater(payload["candidate_customer_summary"]["retainable_customers"], 0)

    def test_renderers_include_block_f_language(self):
        payload = build_population_benchmark_payload()
        html = render_benchmark_html(payload)
        md = render_decision_md(payload)
        self.assertIn("Population Redesign Benchmark", html)
        self.assertIn("Decision:", html)
        self.assertIn("logo.gif", html)
        self.assertIn("Executive summary", html)
        self.assertIn("Phase 4 Population Redesign Decision", md)
        self.assertIn("V2C baseline", md)


if __name__ == "__main__":
    unittest.main()
