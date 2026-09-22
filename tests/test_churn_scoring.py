import sys
import tempfile
import unittest
from pathlib import Path

import joblib
import pandas as pd
from sklearn.dummy import DummyClassifier

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from models.churn_scoring import (
    apply_risk_tier,
    attach_retention_rules,
    score_dataframe,
)


class TestChurnScoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temp_dir = tempfile.TemporaryDirectory()
        cls.package_path = Path(cls._temp_dir.name) / "synthetic_churn_scoring_package.joblib"

        feature_columns = [
            "total_orders",
            "total_payment_value",
            "customer_state_SP",
        ]
        model = DummyClassifier(strategy="prior")
        model.fit(
            pd.DataFrame(
                {
                    "total_orders": [0.0, 1.0, 2.0, 3.0],
                    "total_payment_value": [0.0, 100.0, 200.0, 300.0],
                    "customer_state_SP": [1.0, 1.0, 1.0, 1.0],
                }
            ),
            [0, 0, 1, 1],
        )

        cls.metadata = {
            "model_name": "synthetic_test_model",
            "version_name": "test_v1",
            "model_version": "test_v1",
            "pipeline_tag": "pytest_fixture",
            "run_id": "pytest_fixture",
            "run_date_tag": "20260101",
            "target_column": "churn_v2_label",
            "feature_columns": feature_columns,
            "risk_thresholds": {
                "medium_min_score": 0.40,
                "high_min_score": 0.70,
                "quantile_policy": {
                    "low": "0%-50%",
                    "medium": "50%-80%",
                    "high": "80%-100%",
                },
            },
            "retention_rules": {
                "HIGH": {
                    "base_discount_pct": 25,
                    "vip_discount_pct": 30,
                    "free_shipping": True,
                    "priority_level": "immediate",
                },
                "MEDIUM": {
                    "base_discount_pct": 12,
                    "vip_discount_pct": 12,
                    "free_shipping": True,
                    "priority_level": "scheduled",
                },
                "LOW": {
                    "base_discount_pct": 0,
                    "vip_discount_pct": 0,
                    "free_shipping": False,
                    "priority_level": "light_touch",
                },
            },
        }
        bundle = {
            "metadata": cls.metadata,
            "model_package": {
                "version_name": "test_v1",
                "target_column": "churn_v2_label",
                "model_name": "synthetic_test_model",
                "model": model,
                "feature_columns": feature_columns,
                "train_snapshot_keys": [],
                "validation_snapshot_keys": [],
                "test_snapshot_keys": [],
            },
        }
        joblib.dump(bundle, cls.package_path)

        cls.sample_df = pd.DataFrame(
            [
                {
                    "total_orders": float(index + 1),
                    "total_payment_value": float((index + 1) * 100),
                    "customer_state": "SP",
                }
                for index in range(25)
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls._temp_dir.cleanup()

    def test_apply_risk_tier_boundaries(self):
        thresholds = self.metadata["risk_thresholds"]
        self.assertEqual(apply_risk_tier(thresholds["high_min_score"], thresholds), "HIGH")
        self.assertEqual(apply_risk_tier(thresholds["medium_min_score"], thresholds), "MEDIUM")
        self.assertEqual(apply_risk_tier(thresholds["medium_min_score"] - 1e-6, thresholds), "LOW")

    def test_attach_retention_rules_outputs_columns(self):
        sample = pd.DataFrame(
            {
                "risk_tier": ["HIGH", "HIGH", "MEDIUM", "LOW"],
                "total_payment_value": [1000.0, 100.0, 300.0, 50.0],
            }
        )
        scored = attach_retention_rules(sample, self.metadata)
        self.assertIn("recommended_discount_pct", scored.columns)
        self.assertIn("free_shipping_flag", scored.columns)
        self.assertIn("priority_level", scored.columns)
        self.assertIn("vip_human_touch_flag", scored.columns)
        self.assertEqual(scored.loc[0, "recommended_discount_pct"], 30)
        self.assertTrue(bool(scored.loc[0, "vip_human_touch_flag"]))
        self.assertEqual(scored.loc[1, "recommended_discount_pct"], 25)
        self.assertEqual(scored.loc[2, "recommended_discount_pct"], 12)
        self.assertEqual(scored.loc[3, "recommended_discount_pct"], 0)

    def test_score_dataframe_runs_on_fixture_sample(self):
        scored = score_dataframe(self.sample_df, str(self.package_path))
        self.assertEqual(len(scored), len(self.sample_df))
        for column in [
            "churn_probability",
            "risk_tier",
            "recommended_discount_pct",
            "free_shipping_flag",
            "vip_human_touch_flag",
            "priority_level",
        ]:
            self.assertIn(column, scored.columns)
        self.assertTrue(scored["churn_probability"].between(0, 1).all())
        self.assertTrue(set(scored["risk_tier"].unique()).issubset({"HIGH", "MEDIUM", "LOW"}))


if __name__ == "__main__":
    unittest.main()
