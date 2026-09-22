import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.phase7_reporting_page import (
    PHASE7_REPORTING_POLL_MS,
    _build_history_rows,
    _render_history_rows,
    build_phase7_reporting_view_model,
)


class TestPhase7ReportingPage(unittest.TestCase):
    def setUp(self):
        self._previous_mode = os.environ.pop("MODE", None)

    def tearDown(self):
        if self._previous_mode is not None:
            os.environ["MODE"] = self._previous_mode

    def _write_phase6_kpi_fixture(self, root: Path) -> None:
        payload = {
            "status": "ok",
            "generated_at": "2026-07-30T08:00:00Z",
            "deployment_mode": "simulated",
            "test_count": 3,
            "records": [
                {
                    "proposal_id": "p6-001",
                    "primary_kpi": "checkout_completion",
                    "status": "completed",
                    "verdict": "B_wins",
                    "conversion_lift": 0.035,
                    "guardrail_breach": False,
                    "launch_ts": "2026-07-21T09:15:00Z",
                },
                {
                    "proposal_id": "p6-002",
                    "primary_kpi": "cart_recovery",
                    "status": "completed",
                    "verdict": "B_wins",
                    "conversion_lift": 0.017,
                    "guardrail_breach": False,
                    "launch_ts": "2026-07-22T10:30:00Z",
                },
                {
                    "proposal_id": "p6-003",
                    "primary_kpi": "average_order_value",
                    "status": "running",
                    "verdict": "insufficient_sample",
                    "conversion_lift": None,
                    "guardrail_breach": False,
                    "launch_ts": "2026-07-29T12:10:00Z",
                },
            ],
        }
        processed = root / "data" / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        (processed / "phase6_kpi_status_20260730.json").write_text(json.dumps(payload), encoding="utf-8")

    def _write_phase7_history_fixture(self, root: Path, rows: list[dict]) -> None:
        processed = root / "data" / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_parquet(processed / "phase7_action_history_log.parquet", index=False)

    def test_reporting_page_view_model_with_visible_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase6_kpi_fixture(root)
            self._write_phase7_history_fixture(
                root,
                [
                    {
                        "event_id": "evt-1",
                        "event_type": "governance_decision",
                        "action_id": "P7-ACT-001",
                        "proposal_id": "P7-DRAFT-001",
                        "proposal_run_date": "20260730",
                        "decision_status": "approved",
                        "decision_reason": "Approved for monitoring",
                    },
                    {
                        "event_id": "evt-2",
                        "event_type": "stat_test_completed",
                        "action_id": "P7-ACT-002",
                        "proposal_id": "P7-DRAFT-002",
                        "proposal_run_date": "20260730",
                        "verdict": "B_wins",
                    },
                ],
            )

            view_model = build_phase7_reporting_view_model(root, run_date="20260730")

            self.assertEqual(view_model["summary"]["test_count"], 3)
            self.assertEqual(view_model["summary"]["winner_test_count"], 2)
            self.assertEqual(view_model["summary"]["guardrail_breach_count"], 0)
            self.assertEqual(view_model["summary"]["visible_history_count"], 2)
            self.assertEqual(view_model["history_rows"][0]["status"], "Approved")
            self.assertEqual(view_model["history_rows"][1]["result"], "New proposal wins")

    def test_reporting_page_view_model_handles_empty_history_without_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase6_kpi_fixture(root)

            view_model = build_phase7_reporting_view_model(root, run_date="20260730")

            self.assertEqual(view_model["history"], [])
            self.assertEqual(view_model["summary"]["visible_history_count"], 0)
            self.assertEqual(view_model["history_rows"], [])

    def test_history_rows_accept_legacy_and_normalized_field_names_without_blanks(self):
        rows = _render_history_rows(
            _build_history_rows(
                [
                    {
                        "action": "Legacy mapped action",
                        "kpi_to_improve": "Checkout completion",
                        "result": "New proposal wins",
                        "test_result": "+3.5%",
                        "guardrail": True,
                        "test_period": "21 Jul 2026 · 09:15 → 30 Jul 2026 · 08:00",
                        "decision_reason": "Approved for monitoring",
                        "status": "approved",
                    },
                    {
                        "action": "Normalized mapped action",
                        "kpi_to_improve": "Cart recovery",
                        "result": "Current action wins",
                        "test_result": "-1.2%",
                        "guardrail_risk": False,
                        "launch_at": "22 Jul 2026 · 10:30",
                        "closed_at": "30 Jul 2026 · 08:00",
                        "reason": "Incumbent remains active",
                        "status": "rejected",
                    },
                ],
                [],
            )
        )

        self.assertIn("Approved For Monitoring", rows)
        self.assertIn("Incumbent Remains Active", rows)
        self.assertIn("Risk detected", rows)
        self.assertIn("No risks detected", rows)
        self.assertIn("21 Jul 2026 · 09:15", rows)
        self.assertIn("30 Jul 2026 · 08:00", rows)
        self.assertNotIn("<td class='reason-cell'>—</td>", rows)
        self.assertNotIn("<td>—</td>", rows)

    def test_reporting_page_refresh_poll_constant_is_exactly_every_five_minutes(self):
        self.assertEqual(PHASE7_REPORTING_POLL_MS, 300000)

    def test_kpi_chip_states_cover_pending_and_empty_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            payload = {
                "status": "ok",
                "generated_at": "2026-07-30T08:00:00Z",
                "deployment_mode": "simulated",
                "test_count": 4,
                "records": [
                    {
                        "proposal_id": "p6-001",
                        "primary_kpi": "checkout_completion",
                        "status": "completed",
                        "verdict": "B_wins",
                        "conversion_lift": 0.035,
                        "guardrail_breach": False,
                        "launch_ts": "2026-07-21T09:15:00Z",
                    },
                    {
                        "proposal_id": "p6-002",
                        "primary_kpi": "cart_recovery",
                        "status": "running",
                        "verdict": "insufficient_sample",
                        "conversion_lift": None,
                        "guardrail_breach": False,
                        "launch_ts": "2026-07-22T10:30:00Z",
                    },
                    {
                        "proposal_id": "p6-003",
                        "primary_kpi": "",
                        "status": "completed",
                        "verdict": "insufficient_sample",
                        "conversion_lift": None,
                        "guardrail_breach": False,
                        "launch_ts": "2026-07-29T12:10:00Z",
                    },
                ],
            }
            processed = root / "data" / "processed"
            processed.mkdir(parents=True, exist_ok=True)
            (processed / "phase6_kpi_status_20260730.json").write_text(json.dumps(payload), encoding="utf-8")

            view_model = build_phase7_reporting_view_model(root, run_date="20260730")
            chips = {chip["kpi"]: chip for chip in view_model["kpi_chips"]}

            self.assertEqual(chips["Checkout completion"]["state"], "measured")
            self.assertEqual(chips["Checkout completion"]["value"], "+3.5%")
            self.assertEqual(chips["Cart recovery"]["state"], "pending")
            self.assertEqual(chips["Cart recovery"]["value"], "Pending")
            self.assertEqual(chips["Average order value"]["state"], "pending")
            self.assertEqual(chips["Average order value"]["subtitle"], "Collecting data")
            self.assertEqual(chips["Conversion rate"]["state"], "empty")
            self.assertEqual(chips["Conversion rate"]["subtitle"], "No active proposals")
            self.assertEqual(chips["KPI not assigned"]["state"], "empty")
            self.assertEqual(chips["KPI not assigned"]["value"], "No KPI yet")

    def test_dashboard_history_paginates_five_per_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase6_kpi_fixture(root)
            self._write_phase7_history_fixture(
                root,
                [
                    {
                        "event_id": f"evt-{index}",
                        "event_type": "governance_decision",
                        "action_id": f"P7-ACT-{index:03d}",
                        "proposal_id": f"P7-DRAFT-{index:03d}",
                        "proposal_run_date": "20260730",
                        "decision_status": "approved",
                        "decision_reason": f"Decision {index}",
                    }
                    for index in range(1, 8)
                ],
            )

            view_model = build_phase7_reporting_view_model(root, run_date="20260730")
            template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")
            js = (PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

            self.assertEqual(len(view_model["history_rows"]), 7)
            self.assertIn('id="history-pagination"', template)
            self.assertIn('id="history-export"', template)
            self.assertIn("pageSize: 5", js)
            self.assertIn("downloadCsv(`phase7_history_${runDate}.csv`", js)

    def test_history_rows_preserve_row_level_semantics_without_nan_or_cross_row_fallbacks(self):
        rows = _build_history_rows(
            [
                {
                    "proposal_id": "p6-001",
                    "event_type": "governance_decision",
                    "decision_status": "approved",
                    "decision_reason": "Approved for monitoring",
                    "launch_at": "2026-07-21T09:15:00Z",
                },
                {
                    "proposal_id": "p6-002",
                    "event_type": "stat_test_completed",
                    "verdict": "B_wins",
                    "conversion_lift": 0.017,
                    "guardrail_breach": False,
                    "launch_at": "2026-07-22T10:30:00Z",
                    "closed_at": "2026-07-30T08:00:00Z",
                },
                {
                    "proposal_id": "p6-003",
                    "event_type": "stat_test_completed",
                    "verdict": "insufficient_sample",
                    "conversion_lift": 0.008,
                    "guardrail_breach": False,
                    "launch_at": "2026-07-29T12:10:00Z",
                    "closed_at": "2026-07-30T08:00:00Z",
                },
            ],
            [
                {"proposal_id": "p6-001", "article_title": "A", "primary_kpi": "checkout_completion", "latest_conversion_lift": 0.035, "guardrail_breach": False, "lifecycle_state": "approved_for_stat_test"},
                {"proposal_id": "p6-002", "article_title": "B", "primary_kpi": "cart_recovery", "latest_conversion_lift": 0.017, "guardrail_breach": False, "lifecycle_state": "stat_test_completed"},
                {"proposal_id": "p6-003", "article_title": "C", "primary_kpi": "average_order_value", "latest_conversion_lift": 0.008, "guardrail_breach": False, "lifecycle_state": "stat_test_completed"},
            ],
        )

        self.assertEqual(rows[0]["result"], "Approved for test")
        self.assertEqual(rows[0]["test_result"], "+3.5%")
        self.assertEqual(rows[0]["guardrail"], "No risks detected")
        self.assertEqual(rows[1]["result"], "New proposal wins")
        self.assertEqual(rows[1]["test_result"], "+1.7%")
        self.assertEqual(rows[1]["guardrail"], "No risks detected")
        self.assertEqual(rows[1]["status"], "Pending for approval")
        self.assertEqual(rows[2]["result"], "Not enough data yet")
        self.assertEqual(rows[2]["test_result"], "+0.8%")
        self.assertEqual(rows[2]["guardrail"], "No risks detected")
        self.assertEqual(rows[2]["status"], "Pending of more data")
        self.assertTrue(all("NaN" not in str(value) and "nan" not in str(value) for row in rows for value in row.values()))

    def test_dashboard_run_meta_uses_effective_snapshot_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase6_kpi_fixture(root)
            view_model = build_phase7_reporting_view_model(root, run_date="20260730")

            self.assertEqual(view_model["effective_run_date"], "20260730")

    def test_dashboard_assets_and_removed_ctas_match_manual_review_requirements(self):
        template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn('favicon.ico', template)
        self.assertIn('favicon-16x16.png', template)
        self.assertIn('favicon-32x32.png', template)
        self.assertIn('apple-touch-icon.png', template)
        self.assertIn('CHURN CAMPAIGNS DASHBOARD', template)
        self.assertNotIn('Review tested winners', template)
        self.assertNotIn('Review new proposals', template)
        self.assertIn('resultTone(row.result)', js)
        self.assertIn('testResultTone(row.test_result)', js)
        self.assertIn('guardrailTone(row.guardrail_risk)', js)
        self.assertIn('statusTone(row.status)', js)

    def test_dashboard_poll_copy_shows_minutes(self):
        js = (PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

        self.assertIn("60000", js)
        self.assertIn("Auto-refresh every ${Math.max(1, Math.round(payload.poll_ms / 60000))} minutes", js)


if __name__ == "__main__":
    unittest.main()
