import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.phase7_review_page import build_phase7_review_page_view_model
from evidence.phase7_integration import (
    build_integrated_actions,
    evaluate_integrated_action,
    record_phase7_action_decision,
)


class TestPhase7ReviewPage(unittest.TestCase):
    def setUp(self):
        self._previous_mode = os.environ.pop("MODE", None)

    def tearDown(self):
        if self._previous_mode is not None:
            os.environ["MODE"] = self._previous_mode

    def _write_phase7_fixture(self, root: Path) -> None:
        payload = {
            "drafts": [
                {
                    "proposal_id": "P7-DRAFT-001",
                    "source_name": "Nielsen Norman Group",
                    "article_title": "Incumbent action",
                    "article_url": "https://example.com/incumbent",
                    "published_at": "2026-07-27T00:00:00+00:00",
                    "summary_for_business": "Current active incumbent summary.",
                    "pros": ["Stable"],
                    "cons": ["Older"],
                    "recommended_action": "Keep incumbent action",
                    "generation_contract_violation": False,
                },
                {
                    "proposal_id": "P7-DRAFT-002",
                    "source_name": "Baymard Institute",
                    "article_title": "Fresh candidate for governance",
                    "article_url": "https://example.com/pretest",
                    "published_at": "2026-07-27T01:00:00+00:00",
                    "summary_for_business": "Pending governance approval before test.",
                    "pros": ["Fresh"],
                    "cons": ["Untested"],
                    "recommended_action": "Approve for stat test",
                    "generation_contract_violation": False,
                },
                {
                    "proposal_id": "P7-DRAFT-003",
                    "source_name": "CXL",
                    "article_title": "Winning challenger awaiting confirmation",
                    "article_url": "https://example.com/posttest",
                    "published_at": "2026-07-27T02:00:00+00:00",
                    "summary_for_business": "This challenger already won the test.",
                    "pros": ["Winning"],
                    "cons": ["Needs decision"],
                    "recommended_action": "Review against active incumbent",
                    "generation_contract_violation": False,
                },
            ],
            "validation": [
                {"proposal_id": "P7-DRAFT-001", "passed": True},
                {"proposal_id": "P7-DRAFT-002", "passed": True},
                {"proposal_id": "P7-DRAFT-003", "passed": True},
            ],
        }
        processed = root / "data" / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        (processed / "phase7_action_drafts_20260727.json").write_text(json.dumps(payload), encoding="utf-8")
        build_integrated_actions(project_root=root, run_date="20260727")

        record_phase7_action_decision(
            {
                "action_id": "P7-ACT-001",
                "proposal_run_date": "20260727",
                "decision_status": "approved",
                "decision_reason": "Incumbent remains active",
                "decided_by": "architect.openclaw@gmail.com",
            },
            project_root=root,
        )
        record_phase7_action_decision(
            {
                "action_id": "P7-ACT-003",
                "proposal_run_date": "20260727",
                "decision_status": "approved",
                "decision_reason": "Approve challenger for statistical test",
                "decided_by": "architect.openclaw@gmail.com",
            },
            project_root=root,
        )
        integrated_path = root / "data" / "processed" / "phase7_integrated_actions_20260727.json"
        integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
        incumbent = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-001")
        incumbent["lifecycle_state"] = "active_winner"
        challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-003")
        challenger["lifecycle_state"] = "approved_for_stat_test"
        integrated_path.write_text(json.dumps(integrated, indent=2) + "\n", encoding="utf-8")

        evaluate_integrated_action(
            {
                "action_id": "P7-ACT-003",
                "proposal_run_date": "20260727",
                "launched_by": "architect.openclaw@gmail.com",
                "control_n": 1200,
                "control_converted": 108,
                "control_opt_out": 12,
                "variant_n": 1200,
                "variant_converted": 180,
                "variant_opt_out": 12,
            },
            project_root=root,
        )

        integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
        challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-003")
        challenger["recommended_action"] = "Promote the winning challenger once the current action comparison is complete"
        challenger["primary_kpi"] = "checkout_completion_rate"
        challenger["recommended_kpi"] = "checkout_completion_rate"
        challenger["guardrail_kpi"] = "opt_out_rate"
        challenger["latest_conversion_lift"] = 0.06
        challenger["launch_ts"] = "2026-07-27T02:00:00Z"
        challenger["latest_stat_completed_at"] = "2026-07-27T03:00:00Z"
        challenger["synthetic_previous_action"] = {
            "action_id": "P7-ACT-001",
            "article_title": "Incumbent action",
            "status_label": "Current action",
            "summary": "Current active incumbent summary.",
            "latest_stat_run_id": "p7-stat-incumbent",
        }
        integrated_path.write_text(json.dumps(integrated, indent=2) + "\n", encoding="utf-8")

    def test_review_page_view_model_contains_both_pending_views(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)
            payload = build_phase7_review_page_view_model(root, run_date="20260727")

            self.assertEqual(payload["pre_test_pending_count"], 1)
            self.assertEqual(payload["post_test_pending_count"], 1)
            self.assertEqual(payload["pending_pre_test_actions"][0]["action_id"], "P7-ACT-002")
            self.assertEqual(payload["pending_post_test_decisions"][0]["action_id"], "P7-ACT-003")
            self.assertEqual(payload["pending_post_test_decisions"][0]["previous_action"]["action_id"], "P7-ACT-001")
            self.assertEqual(payload["pending_post_test_decisions"][0]["candidate_incumbents"][0]["action_id"], "P7-ACT-001")


    def test_review_page_view_model_reuses_preloaded_integrated_payload_for_post_test_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)

            with mock.patch("api.phase7_review_page.build_phase7_post_test_decision_queue") as mocked_queue:
                mocked_queue.return_value = {"pending_count": 0, "pending_decisions": []}
                payload = build_phase7_review_page_view_model(root, run_date="20260727")

            self.assertEqual(payload["post_test_pending_count"], 0)
            self.assertEqual(mocked_queue.call_count, 1)
            self.assertIn("integrated_actions_payload", mocked_queue.call_args.kwargs)
            self.assertEqual(
                mocked_queue.call_args.kwargs["integrated_actions_payload"]["run_date"],
                "20260727",
            )

    def test_tested_history_paginates_and_exports(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)
            payload = build_phase7_review_page_view_model(root, run_date="20260727")
            template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
            js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")

            self.assertGreaterEqual(len(payload["history_rows"]), 2)
            self.assertIn('id="history-pagination"', template)
            self.assertIn('id="history-export"', template)
            self.assertIn("pageSize: 5", js)
            self.assertIn("downloadCsv(`phase7_history_${runDate}.csv`", js)

    def test_tested_notice_matches_visible_queue_semantics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)
            template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
            js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")
            payload = build_phase7_review_page_view_model(root, run_date="20260727")

            self.assertEqual(payload["post_test_pending_count"], 1)
            self.assertIn("Review each tested action before replacing the current incumbent", template)
            self.assertIn("Accept or reject every winning proposal", template)
            self.assertIn("Winning proposals", template)
            self.assertIn("Accept", js)
            self.assertIn("Reject", js)

    def test_tested_decision_flow_blocks_when_no_incumbent_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)

            blocked_queue = {
                "pending_count": 1,
                "pending_decisions": [
                    {
                        "action_id": "P7-ACT-003",
                        "proposal_id": "P7-DRAFT-003",
                        "candidate_incumbents": [],
                        "allowed_comparison_outcomes": [],
                        "allowed_decisions_by_comparison_outcome": {},
                    }
                ],
            }
            with mock.patch("api.phase7_review_page.build_phase7_post_test_decision_queue", return_value=blocked_queue):
                payload = build_phase7_review_page_view_model(root, run_date="20260727")

            row = payload["pending_post_test_decisions"][0]
            js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")

            self.assertFalse(row["can_decide"])
            self.assertIn("current action comparison", row["decision_blocker_message"])
            self.assertIn("row.decision_blocker_message", js)
            self.assertIn("Missing required decision context.", js)

    def test_new_actions_template_keeps_auth_out_of_page_content_and_reject_destructive_style(self):
        template = (PROJECT_ROOT / "web" / "templates" / "new-actions-testing.html").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "web" / "static" / "js" / "new-actions.js").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")

        self.assertNotIn("Operator token required", template)
        self.assertIn("ensureAuthGate", js)
        self.assertIn("showAuthGate", js)
        self.assertIn("data-action=\"reject\"", js)
        self.assertIn("[data-view=\"new-actions\"] .cta-button[data-action=\"reject\"]", css)
        self.assertIn("background: var(--red)", css)

    def test_tested_actions_template_uses_horizontal_positive_destructive_actions(self):
        template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
        css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")

        self.assertIn("Review each tested action before replacing the current incumbent", template)
        self.assertIn(".row-actions {", css)
        self.assertIn("display: flex", css)
        self.assertIn(".row-actions .cta-button.primary", css)
        self.assertIn("background: var(--green)", css)
        self.assertIn("resultTone(row.result)", js)
        self.assertIn("testResultTone(row.test_result)", js)

    def test_new_actions_disable_decision_when_recommendation_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_phase7_fixture(root)
            integrated_path = root / "data" / "processed" / "phase7_integrated_actions_20260727.json"
            integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
            pending_action = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            pending_action["recommended_action"] = ""
            integrated_path.write_text(json.dumps(integrated, indent=2) + "\n", encoding="utf-8")

            payload = build_phase7_review_page_view_model(root, run_date="20260727")
            row = payload["pending_pre_test_actions"][0]

            self.assertFalse(row["can_review"])
            self.assertIn("recommended action", row["decision_blocker_message"])


if __name__ == "__main__":
    unittest.main()
