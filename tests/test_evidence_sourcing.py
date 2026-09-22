import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.recommendation_builder import (
    build_and_write_recommendations,
    build_recommendation_rows,
)


class TestEvidenceSourcingRecommendations(unittest.TestCase):
    def test_recommendation_report_respects_confidence_gate_and_priority_order(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            catalog = [
                {
                    "intervention_id": "INT-01",
                    "source_name": "CXL",
                    "ref_id": "[1]",
                    "confidence_score": "low",
                    "actionability_score": "high",
                    "applicability_to_vivamarket": "high",
                    "actionable_elements": {"copy": "value_first", "channel": "email", "timing": "pre", "incentive": "coupon"},
                    "effect_size_text": "heuristic",
                    "quote_or_anchor": "anchor 1",
                },
                {
                    "intervention_id": "INT-02",
                    "source_name": "ResearchGate",
                    "ref_id": "[4]",
                    "confidence_score": "medium",
                    "actionability_score": "high",
                    "applicability_to_vivamarket": "medium",
                    "actionable_elements": {"copy": "personalized", "channel": "email", "timing": "followup", "incentive": "offer"},
                    "effect_size_text": "quasi experimental",
                    "quote_or_anchor": "anchor 2",
                },
                {
                    "intervention_id": "INT-04",
                    "source_name": "Altcraft",
                    "ref_id": "[11]",
                    "confidence_score": "low",
                    "actionability_score": "high",
                    "applicability_to_vivamarket": "high",
                    "actionable_elements": {"copy": "short", "channel": "sms", "timing": "non_openers", "incentive": "same_coupon"},
                    "effect_size_text": "open rate",
                    "quote_or_anchor": "anchor 3",
                },
            ]
            (root / "data" / "processed" / "evidence_catalog_20260721.json").write_text(json.dumps(catalog), encoding="utf-8")

            payload = build_and_write_recommendations(project_root=root, run_date="20260721")
            report_path = Path(payload["report_path"])
            self.assertTrue(report_path.exists())
            report = report_path.read_text(encoding="utf-8")
            self.assertEqual(payload["top_intervention"], "INT-02")
            self.assertIn("approval-gate-eligible", report)
            self.assertIn("evidence_enrichment_only", report)
            self.assertIn("INT-02", report)
            self.assertIn("INT-01", report)
            self.assertIn("INT-04", report)

    def test_recommendation_rows_support_high_confidence_tier_1_and_stable_tie_break(self):
        catalog = [
            {
                "intervention_id": "INT-05",
                "source_name": "Journal A",
                "ref_id": "[20]",
                "confidence_score": "high",
                "actionability_score": "high",
                "applicability_to_vivamarket": "low",
                "actionable_elements": {"copy": "a", "channel": "email", "timing": "b", "incentive": "c"},
                "effect_size_text": "rct",
                "quote_or_anchor": "anchor 5",
            },
            {
                "intervention_id": "INT-01",
                "source_name": "CXL",
                "ref_id": "[1]",
                "confidence_score": "low",
                "actionability_score": "high",
                "applicability_to_vivamarket": "high",
                "actionable_elements": {"copy": "value_first", "channel": "email", "timing": "pre", "incentive": "coupon"},
                "effect_size_text": "heuristic",
                "quote_or_anchor": "anchor 1",
            },
            {
                "intervention_id": "INT-04",
                "source_name": "Altcraft",
                "ref_id": "[11]",
                "confidence_score": "low",
                "actionability_score": "high",
                "applicability_to_vivamarket": "high",
                "actionable_elements": {"copy": "short", "channel": "sms", "timing": "non_openers", "incentive": "same_coupon"},
                "effect_size_text": "open rate",
                "quote_or_anchor": "anchor 3",
            },
        ]

        rows = build_recommendation_rows(catalog)
        self.assertEqual(rows[0]["intervention_id"], "INT-05")
        self.assertEqual(rows[0]["recommendation_tier"], "tier_1")
        self.assertEqual(rows[0]["readiness"], "approval_gate_eligible")
        self.assertEqual([row["intervention_id"] for row in rows[1:]], ["INT-01", "INT-04"])

    def test_build_and_write_recommendations_fails_cleanly_without_catalog(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)

            with self.assertRaisesRegex(FileNotFoundError, "no evidence catalog found"):
                build_and_write_recommendations(project_root=root)

    def test_build_and_write_recommendations_without_run_date_uses_latest_catalog(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            older_catalog = [
                {
                    "intervention_id": "INT-01",
                    "source_name": "Older source",
                    "ref_id": "[1]",
                    "confidence_score": "low",
                    "actionability_score": "medium",
                    "applicability_to_vivamarket": "low",
                    "actionable_elements": {"copy": "older", "channel": "email", "timing": None, "incentive": None},
                    "effect_size_text": "older",
                    "quote_or_anchor": "older anchor",
                }
            ]
            latest_catalog = [
                {
                    "intervention_id": "INT-02",
                    "source_name": "Latest source",
                    "ref_id": "[4]",
                    "confidence_score": "medium",
                    "actionability_score": "high",
                    "applicability_to_vivamarket": "medium",
                    "actionable_elements": {"copy": "latest", "channel": "email", "timing": "followup", "incentive": "offer"},
                    "effect_size_text": "latest",
                    "quote_or_anchor": "latest anchor",
                }
            ]
            (root / "data" / "processed" / "evidence_catalog_20240101.json").write_text(json.dumps(older_catalog), encoding="utf-8")
            (root / "data" / "processed" / "evidence_catalog_20240601.json").write_text(json.dumps(latest_catalog), encoding="utf-8")

            payload = build_and_write_recommendations(project_root=root)

            self.assertEqual(payload["run_date"], "20240601")
            self.assertEqual(payload["top_intervention"], "INT-02")
            self.assertTrue(Path(payload["report_path"]).exists())
            self.assertTrue(payload["report_path"].endswith("phase6_dynamic_evidence_recommendations_20240601.md"))


if __name__ == "__main__":
    unittest.main()
