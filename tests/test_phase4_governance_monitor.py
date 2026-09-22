import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.phase4_governance_monitor import (
    build_governance_payload,
    render_governance_report,
    render_model_card_v3,
)


class TestPhase4GovernanceMonitor(unittest.TestCase):
    def test_governance_payload_has_expected_layers(self):
        payload = build_governance_payload()
        self.assertEqual(payload["measurement_label"], "Simulated campaign baseline")
        self.assertEqual(len(payload["feature_drift"]), 5)
        self.assertIn("score_drift", payload)
        self.assertIn("tier_stability", payload)
        self.assertGreater(payload["totals"]["closed_evaluations"], 500)
        self.assertTrue(payload["trigger_summary"])

    def test_render_outputs_include_governance_and_model_card_sections(self):
        payload = build_governance_payload()
        html = render_governance_report(payload)
        model_card = render_model_card_v3(payload)
        self.assertIn("Phase 4 Governance & Drift Monitor", html)
        self.assertIn("Governance trigger summary", html)
        self.assertIn("logo.gif", html)
        self.assertIn("Executive summary", html)
        self.assertIn("MODEL CARD — DAILY CUSTOMER CHURN PREDICTOR", model_card)
        self.assertIn("Holdout lift by tier", model_card)
        self.assertIn("Simulated campaign baseline", model_card)


if __name__ == "__main__":
    unittest.main()
