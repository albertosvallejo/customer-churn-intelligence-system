import json
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.detect_conversions import (
    _ensure_retention_events_table,
    detect_conversions,
)


class TestDetectConversions(unittest.TestCase):
    def test_detect_conversions_inserts_window_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            ops_db = tmpdir_path / "ops.sqlite"
            source_db = tmpdir_path / "source.sqlite"

            ops_engine = create_engine(f"sqlite:///{ops_db}")
            source_engine = create_engine(f"sqlite:///{source_db}")
            try:
                with ops_engine.begin() as conn:
                    conn.execute(text("CREATE TABLE retention_actions (customer_unique_id TEXT, run_date_tag TEXT, coupon_code TEXT, executed_at TIMESTAMP, channel TEXT, risk_tier TEXT, holdout BOOLEAN);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES ('cust_001','20260524','VIVA-AAAA-BBBB','2026-05-24 09:00:00','email','HIGH',0);"))
                _ensure_retention_events_table(ops_engine)

                with source_engine.begin() as conn:
                    conn.execute(text("CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT);"))
                    conn.execute(text("CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_purchase_timestamp TIMESTAMP);"))
                    conn.execute(text("CREATE TABLE order_payments (order_id TEXT, payment_value REAL);"))
                    conn.execute(text("INSERT INTO customers VALUES ('c1','cust_001');"))
                    conn.execute(text("INSERT INTO orders VALUES ('o1','c1','2026-05-25 10:00:00');"))
                    conn.execute(text("INSERT INTO order_payments VALUES ('o1', 123.45);"))

                inserted = detect_conversions(ops_engine, source_engine)
                self.assertEqual(inserted, 1)

                with ops_engine.begin() as conn:
                    row = conn.execute(text("SELECT customer_unique_id, run_date_tag, channel, event_type, order_id, metadata FROM retention_events")).fetchone()
                self.assertEqual(tuple(row[:5]), ("cust_001", "20260524", "email", "converted", "o1"))
                metadata = json.loads(row[5])
                self.assertEqual(metadata["conversion_window_days"], 14)
                self.assertEqual(metadata["risk_tier"], "HIGH")
                self.assertFalse(metadata["holdout"])

            finally:
                source_engine.dispose()
                ops_engine.dispose()

    def test_detect_conversions_uses_tier_specific_windows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            ops_db = tmpdir_path / "ops.sqlite"
            source_db = tmpdir_path / "source.sqlite"

            ops_engine = create_engine(f"sqlite:///{ops_db}")
            source_engine = create_engine(f"sqlite:///{source_db}")
            try:
                with ops_engine.begin() as conn:
                    conn.execute(text("CREATE TABLE retention_actions (customer_unique_id TEXT, run_date_tag TEXT, coupon_code TEXT, executed_at TIMESTAMP, channel TEXT, risk_tier TEXT, holdout BOOLEAN);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES ('cust_med','20260524','VIVA-MEDM-0001','2026-05-24 09:00:00','push','MEDIUM',1);"))
                    conn.execute(text("INSERT INTO retention_actions VALUES ('cust_low','20260524','VIVA-LOWW-0001','2026-05-24 09:00:00','push','LOW',0);"))
                _ensure_retention_events_table(ops_engine)

                with source_engine.begin() as conn:
                    conn.execute(text("CREATE TABLE customers (customer_id TEXT, customer_unique_id TEXT);"))
                    conn.execute(text("CREATE TABLE orders (order_id TEXT, customer_id TEXT, order_purchase_timestamp TIMESTAMP);"))
                    conn.execute(text("CREATE TABLE order_payments (order_id TEXT, payment_value REAL);"))
                    conn.execute(text("INSERT INTO customers VALUES ('c_med','cust_med');"))
                    conn.execute(text("INSERT INTO customers VALUES ('c_low','cust_low');"))
                    conn.execute(text("INSERT INTO orders VALUES ('o_med','c_med','2026-06-10 10:00:00');"))
                    conn.execute(text("INSERT INTO orders VALUES ('o_low','c_low','2026-06-20 10:00:00');"))
                    conn.execute(text("INSERT INTO order_payments VALUES ('o_med', 88.00);"))
                    conn.execute(text("INSERT INTO order_payments VALUES ('o_low', 55.00);"))

                inserted = detect_conversions(ops_engine, source_engine)
                self.assertEqual(inserted, 2)

                with ops_engine.begin() as conn:
                    rows = conn.execute(text("SELECT customer_unique_id, metadata FROM retention_events ORDER BY customer_unique_id")).fetchall()

                parsed = {row[0]: json.loads(row[1]) for row in rows}
                self.assertEqual(parsed["cust_med"]["conversion_window_days"], 21)
                self.assertEqual(parsed["cust_med"]["risk_tier"], "MEDIUM")
                self.assertTrue(parsed["cust_med"]["holdout"])
                self.assertEqual(parsed["cust_low"]["conversion_window_days"], 30)
                self.assertEqual(parsed["cust_low"]["risk_tier"], "LOW")


            finally:
                source_engine.dispose()
                ops_engine.dispose()
if __name__ == "__main__":
    unittest.main()
