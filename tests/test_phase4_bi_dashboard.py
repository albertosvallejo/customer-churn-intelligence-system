import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.phase4_bi_dashboard import _load_inputs, render_dashboard


class TestPhase4BiDashboard(unittest.TestCase):
    def test_dashboard_render_contains_required_demo_labels_and_views(self):
        inputs = _load_inputs()
        html = render_dashboard(inputs)
        self.assertIn("Retention BI Dashboard", html)
        self.assertIn("Current portfolio baseline · canonical V2C + Phase 4 reporting layer", html)
        self.assertIn("Operational view", html)
        self.assertIn("Analytical view", html)
        self.assertIn("Holdout share", html)
        self.assertIn("Campaign effectiveness snapshot", html)
        self.assertIn("cdn.plot.ly", html)
        self.assertIn("tier-mix-chart", html)
        self.assertIn("campaign-kpi-chart", html)
        self.assertIn("driver-chart", html)


if __name__ == "__main__":
    unittest.main()
