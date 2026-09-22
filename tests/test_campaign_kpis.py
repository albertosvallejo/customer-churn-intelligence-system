import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.campaign_kpis import (
    build_closed_evaluation_frame,
    render_campaign_kpi_report,
    summarize_campaign_kpis,
)


class TestCampaignKpis(unittest.TestCase):
    def test_closed_evaluations_include_treated_and_holdout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ops.sqlite"
            engine = create_engine(f"sqlite:///{db_path}")
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE TABLE retention_actions (id INTEGER PRIMARY KEY, customer_unique_id TEXT, run_id TEXT, risk_tier TEXT, channel TEXT, executed_at TIMESTAMP, holdout BOOLEAN, campaign_cycle DATE, holdout_window_days INTEGER);"))
                    conn.execute(text("CREATE TABLE retention_events (customer_unique_id TEXT, event_type TEXT, event_ts TIMESTAMP, metadata TEXT);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES (1, 'cust_treated', 'run_1', 'HIGH', 'push', '2026-05-01 09:00:00', 0, '2026-05-01', NULL);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES (2, 'cust_holdout', 'run_1', 'MEDIUM', 'push', '2026-05-01 09:00:00', 1, '2026-05-01', NULL);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES (3, 'cust_open', 'run_2', 'LOW', 'push', '2026-05-25 09:00:00', 0, '2026-05-25', NULL);"))
                    conn.execute(text("INSERT INTO retention_events VALUES ('cust_treated', 'converted', '2026-05-10 10:00:00', '{}');"))
                    conn.execute(text("INSERT INTO retention_events VALUES ('cust_holdout', 'converted', '2026-05-18 10:00:00', '{}');"))

                frame = build_closed_evaluation_frame(engine=engine, as_of="2026-05-29T00:00:00Z")
                self.assertEqual(len(frame), 3)
                closed = frame[frame["closed_evaluation"]]
                self.assertEqual(len(closed), 2)
                self.assertTrue(frame.loc[frame["customer_unique_id"] == "cust_treated", "converted"].iloc[0])
                self.assertTrue(frame.loc[frame["customer_unique_id"] == "cust_holdout", "converted"].iloc[0])
                self.assertFalse(frame.loc[frame["customer_unique_id"] == "cust_open", "closed_evaluation"].iloc[0])

            finally:
                engine.dispose()

    def test_summary_reports_holdout_lift_when_both_groups_exist(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ops.sqlite"
            engine = create_engine(f"sqlite:///{db_path}")
            try:
                with engine.begin() as conn:
                    conn.execute(text("CREATE TABLE retention_actions (id INTEGER PRIMARY KEY, customer_unique_id TEXT, run_id TEXT, risk_tier TEXT, channel TEXT, executed_at TIMESTAMP, holdout BOOLEAN, campaign_cycle DATE, holdout_window_days INTEGER);"))
                    conn.execute(text("CREATE TABLE retention_events (customer_unique_id TEXT, event_type TEXT, event_ts TIMESTAMP, metadata TEXT);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES (1, 'cust_h1', 'run_1', 'HIGH', 'push', '2026-05-01 09:00:00', 0, '2026-05-01', NULL);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES (2, 'cust_h2', 'run_1', 'HIGH', 'push', '2026-05-01 09:00:00', 1, '2026-05-01', NULL);"))
                    conn.execute(text("INSERT INTO retention_events VALUES ('cust_h1', 'converted', '2026-05-03 10:00:00', '{}');"))

                payload = summarize_campaign_kpis(engine=engine, as_of="2026-05-29T00:00:00Z")
                self.assertEqual(payload["totals"]["closed_evaluations"], 2)
                self.assertEqual(len(payload["holdout_lift"]), 1)
                self.assertEqual(payload["holdout_lift"][0]["risk_tier"], "HIGH")
                self.assertAlmostEqual(payload["holdout_lift"][0]["holdout_lift"], 1.0)
                self.assertEqual(payload["label"], "Simulated campaign baseline · pre-holdout internal monitor")

            finally:
                engine.dispose()

    def test_synthetic_parquet_contract_is_supported(self):
        actions_path = PROJECT_ROOT / "data" / "processed" / "retention_actions_synthetic_30d.parquet"
        events_path = PROJECT_ROOT / "data" / "processed" / "retention_events_synthetic_30d.parquet"
        frame = build_closed_evaluation_frame(
            as_of="2026-05-30T00:00:00Z",
            actions_parquet_path=actions_path,
            events_parquet_path=events_path,
        )
        self.assertFalse(frame.empty)
        self.assertIn("action_id", frame.columns)
        self.assertIn("window_days", frame.columns)
        self.assertIn("converted", frame.columns)

        payload = summarize_campaign_kpis(
            as_of="2026-05-30T00:00:00Z",
            actions_parquet_path=actions_path,
            events_parquet_path=events_path,
        )
        self.assertEqual(sorted(item["risk_tier"] for item in payload["holdout_lift"]), ["HIGH", "LOW", "MEDIUM"])
        self.assertGreater(payload["totals"]["closed_evaluations"], 0)

        report_html = render_campaign_kpi_report(payload)
        self.assertIn("Campaign KPI Monitor", report_html)
        self.assertIn("pre-holdout", report_html)
        self.assertIn("Run timestamp", report_html)


if __name__ == "__main__":
    unittest.main()
