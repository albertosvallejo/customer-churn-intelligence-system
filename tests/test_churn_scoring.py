import sys
import unittest
from pathlib import Path

import joblib
import pandas as pd

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
        cls.package_path = max((PROJECT_ROOT / "models").glob("churn_scoring_package_*.joblib"))
        cls.bundle = joblib.load(cls.package_path)
        cls.metadata = cls.bundle["metadata"]
        cls.feature_path = max((PROJECT_ROOT / "data" / "processed").glob("churn_features_*.parquet"))
        feature_df = pd.read_parquet(cls.feature_path)
        leakage_columns = [
            'customer_unique_id', 'snapshot_key', 'snapshot_date', 'first_purchase_timestamp',
            'last_purchase_timestamp', 'future_orders_90d', 'future_revenue_90d', 'churn_90d_label',
            'churn_v2_label', 'next_purchase_timestamp', 'days_to_next_purchase', 'future_purchase_within_horizon'
        ]
        cls.sample_df = feature_df[[c for c in feature_df.columns if c not in leakage_columns]].head(25).copy()

    def test_apply_risk_tier_boundaries(self):
        thresholds = self.metadata['risk_thresholds']
        self.assertEqual(apply_risk_tier(thresholds['high_min_score'], thresholds), 'HIGH')
        self.assertEqual(apply_risk_tier(thresholds['medium_min_score'], thresholds), 'MEDIUM')
        self.assertEqual(apply_risk_tier(thresholds['medium_min_score'] - 1e-6, thresholds), 'LOW')

    def test_attach_retention_rules_outputs_columns(self):
        sample = pd.DataFrame(
            {
                'risk_tier': ['HIGH', 'HIGH', 'MEDIUM', 'LOW'],
                'total_payment_value': [1000.0, 100.0, 300.0, 50.0],
            }
        )
        scored = attach_retention_rules(sample, self.metadata)
        self.assertIn('recommended_discount_pct', scored.columns)
        self.assertIn('free_shipping_flag', scored.columns)
        self.assertIn('priority_level', scored.columns)
        self.assertIn('vip_human_touch_flag', scored.columns)
        self.assertEqual(scored.loc[0, 'recommended_discount_pct'], 30)
        self.assertTrue(bool(scored.loc[0, 'vip_human_touch_flag']))
        self.assertEqual(scored.loc[1, 'recommended_discount_pct'], 25)
        self.assertEqual(scored.loc[2, 'recommended_discount_pct'], 12)
        self.assertEqual(scored.loc[3, 'recommended_discount_pct'], 0)

    def test_score_dataframe_runs_on_real_sample(self):
        scored = score_dataframe(self.sample_df, str(self.package_path))
        self.assertEqual(len(scored), len(self.sample_df))
        for col in ['churn_probability', 'risk_tier', 'recommended_discount_pct', 'free_shipping_flag', 'vip_human_touch_flag', 'priority_level']:
            self.assertIn(col, scored.columns)
        self.assertTrue(scored['churn_probability'].between(0, 1).all())
        self.assertTrue(set(scored['risk_tier'].unique()).issubset({'HIGH', 'MEDIUM', 'LOW'}))


if __name__ == '__main__':
    unittest.main()
