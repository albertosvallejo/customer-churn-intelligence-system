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

import evidence.phase7_integration as phase7_integration_module
from evidence.phase7_integration import (
    build_integrated_actions,
    build_phase7_kpi_status_view,
    build_phase7_n8n_payload,
    build_phase7_post_test_decision_queue,
    build_phase7_stat_summary,
    create_phase7_stat_launch_request,
    evaluate_integrated_action,
    execute_phase7_stat_launch_request,
    load_integrated_actions,
    load_phase7_action_history,
    load_phase7_launch_requests,
    record_phase7_action_decision,
    record_phase7_post_test_decision,
)


class TestPhase7Integration(unittest.TestCase):
    def setUp(self):
        self._previous_mode = os.environ.pop("MODE", None)

    def tearDown(self):
        if self._previous_mode is not None:
            os.environ["MODE"] = self._previous_mode

    def test_build_integrated_actions_marks_blocked_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-009",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Blocked Article",
                        "article_url": "https://example.com/blocked",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Blocked summary",
                        "pros": ["Pro"],
                        "cons": ["Con"],
                        "recommended_action": "Blocked action",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-009", "passed": False}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

            build_integrated_actions(project_root=root, run_date="20260727")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(integrated["actions"][0]["stat_test_status"], "blocked")
            self.assertEqual(integrated["actions"][0]["block_reason"], "draft_validation_failed")

    def test_build_integrated_actions_creates_ready_candidates_from_valid_drafts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute public content",
                        "article_title": "Article B",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": True,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": False},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )

            result = build_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(result["action_count"], 2)
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(integrated["actions"][0]["stat_test_status"], "ready")
            self.assertEqual(integrated["actions"][1]["stat_test_status"], "blocked")

    def test_build_integrated_actions_preserves_pending_review_state_while_refreshing_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            initial_payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            draft_path = root / "data" / "processed" / "phase7_action_drafts_20260727.json"
            draft_path.write_text(json.dumps(initial_payload), encoding="utf-8")

            build_integrated_actions(project_root=root, run_date="20260727")

            refreshed_payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A Updated",
                        "article_url": "https://example.com/a-2",
                        "published_at": "2026-07-28T00:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            draft_path.write_text(json.dumps(refreshed_payload), encoding="utf-8")

            build_integrated_actions(project_root=root, run_date="20260727")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")

            self.assertEqual(integrated["actions"][0]["approval_status"], "pending_review")
            self.assertEqual(integrated["actions"][0]["summary_for_business"], "Summary B")
            self.assertEqual(integrated["actions"][0]["recommended_action"], "Action B")
            self.assertFalse(integrated["actions"][0]["draft_content_changed_since_decision"])
            self.assertIsNone(integrated["actions"][0]["draft_refresh_blocked_reason"])

    def test_build_integrated_actions_preserves_decided_snapshot_when_draft_content_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            initial_payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            draft_path = root / "data" / "processed" / "phase7_action_drafts_20260727.json"
            draft_path.write_text(json.dumps(initial_payload), encoding="utf-8")

            build_integrated_actions(project_root=root, run_date="20260727")
            decision = record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Approved snapshot",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            refreshed_payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group Updated",
                        "article_title": "Article A Updated",
                        "article_url": "https://example.com/a-2",
                        "published_at": "2026-07-28T00:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            draft_path.write_text(json.dumps(refreshed_payload), encoding="utf-8")

            build_integrated_actions(project_root=root, run_date="20260727")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            action = integrated["actions"][0]

            self.assertEqual(action["approval_status"], "approved")
            self.assertEqual(action["decision_reason"], "Approved snapshot")
            self.assertEqual(action["decided_by"], "architect.openclaw@gmail.com")
            self.assertEqual(action["decision_ts"], decision["decision_ts"])
            self.assertEqual(action["summary_for_business"], "Summary A")
            self.assertEqual(action["pros"], ["Pro A"])
            self.assertEqual(action["cons"], ["Con A"])
            self.assertEqual(action["recommended_action"], "Action A")
            self.assertEqual(action["article_title"], "Article A")
            self.assertTrue(action["draft_content_changed_since_decision"])
            self.assertEqual(action["draft_refresh_blocked_reason"], "governance_snapshot_preserved")

    def test_phase7_stat_summary_reports_persisted_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Ready for statistical evaluation",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            summary = build_phase7_stat_summary(project_root=root, run_date="20260727")
            self.assertEqual(summary["status"], "ok")
            self.assertEqual(summary["evaluated_action_count"], 1)
            self.assertEqual(summary["stat_run_count"], 1)
            self.assertEqual(summary["records"][0]["action_id"], "P7-ACT-001")

    def test_phase7_kpi_and_n8n_payload_builders_use_persisted_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Ready for statistical evaluation",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )
            kpi_payload = build_phase7_kpi_status_view(project_root=root, run_date="20260727")
            n8n_payload = build_phase7_n8n_payload(project_root=root, run_date="20260727")
            self.assertEqual(kpi_payload["status"], "ok")
            self.assertEqual(kpi_payload["stat_run_count"], 1)
            self.assertEqual(n8n_payload["status"], "ok")
            self.assertEqual(n8n_payload["actions"][0]["latest_verdict"], "no_significant_difference")

    def test_evaluate_integrated_action_reuses_statistical_engine_and_persists_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Ready for statistical evaluation",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            result = evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            self.assertEqual(result["action_id"], "P7-ACT-001")
            self.assertEqual(result["verdict"], "no_significant_difference")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(integrated["actions"][0]["latest_verdict"], "no_significant_difference")

    def test_phase7_decision_and_history_extend_lifecycle_before_stat_launch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            decision = record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Approved by governance",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            self.assertEqual(decision["decision_status"], "approved")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(integrated["actions"][0]["approval_status"], "approved")
            self.assertEqual(integrated["actions"][0]["lifecycle_state"], "approved_for_stat_test")
            history = load_phase7_action_history(project_root=root, run_date="20260727")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["event_type"], "governance_decision")

    def test_phase7_governed_launch_request_wraps_stat_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Approved by governance",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            launch_request = create_phase7_stat_launch_request(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )
            requests = load_phase7_launch_requests(project_root=root, run_date="20260727")
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0]["request_status"], "pending_execution")

            result = execute_phase7_stat_launch_request(
                {
                    "launch_request_id": launch_request["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            self.assertEqual(result["verdict"], "no_significant_difference")
            requests = load_phase7_launch_requests(project_root=root, run_date="20260727")
            self.assertEqual(requests[0]["request_status"], "executed")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            self.assertEqual(integrated["actions"][0]["launch_status"], "completed")

    def test_phase7_action_history_hides_pending_launch_events_until_there_is_result_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Approved by governance",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            create_phase7_stat_launch_request(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            history = load_phase7_action_history(project_root=root, run_date="20260727")
            self.assertEqual([row["event_type"] for row in history], ["governance_decision"])
            self.assertEqual(history[0]["visibility_status"], "visible")

    def test_phase7_action_history_marks_discarded_actions_as_visible_once(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "rejected",
                    "decision_reason": "Discard this action",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            history = load_phase7_action_history(project_root=root, run_date="20260727")
            self.assertEqual(len(history), 1)
            self.assertEqual(history[0]["event_type"], "governance_decision")
            self.assertEqual(history[0]["decision_status"], "rejected")
            self.assertEqual(history[0]["visibility_status"], "visible_discarded_once")

    def test_phase7_action_history_shows_stat_completion_once_result_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Article A",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Approved by governance",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            launch_request = create_phase7_stat_launch_request(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )
            execute_phase7_stat_launch_request(
                {
                    "launch_request_id": launch_request["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            history = load_phase7_action_history(project_root=root, run_date="20260727")
            completion_events = [row for row in history if row["event_type"] == "stat_test_completed"]
            self.assertEqual(len(completion_events), 1)
            self.assertEqual(completion_events[0]["visibility_status"], "visible")
            self.assertEqual(completion_events[0]["action_id"], "P7-ACT-001")

    def test_post_test_decision_promotes_challenger_and_replaces_incumbent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")

            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-001",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Incumbent already active",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            record_phase7_action_decision(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "decision_status": "approved",
                    "decision_reason": "Challenger approved for test",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-002",
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

            result = record_phase7_post_test_decision(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "comparison_target_action_id": "P7-ACT-001",
                    "comparison_outcome": "candidate_wins",
                    "decision_type": "promote_challenger",
                    "previous_incumbent_status": "replaced",
                    "decision_reason": "Promote the challenger after the winning readout",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            self.assertEqual(result["decision_type"], "promote_challenger")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            incumbent = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-001")
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            self.assertEqual(challenger["comparison_target_action_id"], "P7-ACT-001")
            self.assertEqual(challenger["comparison_outcome"], "candidate_wins")
            self.assertEqual(challenger["decision_type"], "promote_challenger")
            self.assertEqual(challenger["lifecycle_state"], "active_winner")
            self.assertEqual(incumbent["lifecycle_state"], "replaced")
            self.assertEqual(incumbent["launch_status"], "replaced")
            history = load_phase7_action_history(project_root=root, run_date="20260727")
            self.assertEqual(history[-1]["event_type"], "post_test_decision")

    def test_post_test_decision_rejects_outcome_incompatible_with_latest_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            for action_id in ("P7-ACT-001", "P7-ACT-002"):
                record_phase7_action_decision(
                    {
                        "action_id": action_id,
                        "proposal_run_date": "20260727",
                        "decision_status": "approved",
                        "decision_reason": "Approved",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            with self.assertRaises(ValueError) as context:
                record_phase7_post_test_decision(
                    {
                        "action_id": "P7-ACT-002",
                        "proposal_run_date": "20260727",
                        "comparison_target_action_id": "P7-ACT-001",
                        "comparison_outcome": "candidate_wins",
                        "decision_type": "promote_challenger",
                        "previous_incumbent_status": "replaced",
                        "decision_reason": "Invalid because verdict was inconclusive",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            self.assertIn("incompatible with latest_verdict", str(context.exception))

    def test_post_test_decision_rejects_unknown_latest_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            for action_id in ("P7-ACT-001", "P7-ACT-002"):
                record_phase7_action_decision(
                    {
                        "action_id": action_id,
                        "proposal_run_date": "20260727",
                        "decision_status": "approved",
                        "decision_reason": "Approved",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            challenger["launch_status"] = "completed"
            challenger["latest_stat_run_id"] = "p7-stat-manual"
            challenger["latest_verdict"] = "unexpected_verdict"
            (root / "data" / "processed" / "phase7_integrated_actions_20260727.json").write_text(
                json.dumps(integrated), encoding="utf-8"
            )

            with self.assertRaises(ValueError) as context:
                record_phase7_post_test_decision(
                    {
                        "action_id": "P7-ACT-002",
                        "proposal_run_date": "20260727",
                        "comparison_target_action_id": "P7-ACT-001",
                        "comparison_outcome": "candidate_wins",
                        "decision_type": "promote_challenger",
                        "previous_incumbent_status": "replaced",
                        "decision_reason": "Unknown verdict must fail closed",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            self.assertIn("unknown latest_verdict", str(context.exception))

    def test_post_test_decision_keep_incumbent_preserves_completed_launch_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            for action_id in ("P7-ACT-001", "P7-ACT-002"):
                record_phase7_action_decision(
                    {
                        "action_id": action_id,
                        "proposal_run_date": "20260727",
                        "decision_status": "approved",
                        "decision_reason": "Approved",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 180,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 108,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            result = record_phase7_post_test_decision(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "comparison_target_action_id": "P7-ACT-001",
                    "comparison_outcome": "incumbent_keeps",
                    "decision_type": "keep_incumbent",
                    "decision_reason": "Incumbent stays active after challenger loss",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            self.assertEqual(result["decision_type"], "keep_incumbent")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            self.assertEqual(challenger["lifecycle_state"], "post_test_incumbent_retained")
            self.assertEqual(challenger["launch_status"], "completed")
            self.assertEqual(challenger["stat_test_status"], "completed")

    def test_post_test_decision_retest_resets_launch_without_blocking_stat_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            for action_id in ("P7-ACT-001", "P7-ACT-002"):
                record_phase7_action_decision(
                    {
                        "action_id": action_id,
                        "proposal_run_date": "20260727",
                        "decision_status": "approved",
                        "decision_reason": "Approved",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            result = record_phase7_post_test_decision(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "comparison_target_action_id": "P7-ACT-001",
                    "comparison_outcome": "needs_retest",
                    "decision_type": "retest",
                    "decision_reason": "Result is inconclusive and needs another test",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            self.assertEqual(result["decision_type"], "retest")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            self.assertEqual(challenger["lifecycle_state"], "post_test_retest_required")
            self.assertEqual(challenger["launch_status"], "not_started")
            self.assertEqual(challenger["stat_test_status"], "completed")

    def test_post_test_decision_retire_candidate_blocks_future_stat_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")
            for action_id in ("P7-ACT-001", "P7-ACT-002"):
                record_phase7_action_decision(
                    {
                        "action_id": action_id,
                        "proposal_run_date": "20260727",
                        "decision_status": "approved",
                        "decision_reason": "Approved",
                        "decided_by": "architect.openclaw@gmail.com",
                    },
                    project_root=root,
                )
            evaluate_integrated_action(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 40,
                    "variant_n": 1200,
                    "variant_converted": 180,
                    "variant_opt_out": 12,
                },
                project_root=root,
            )

            result = record_phase7_post_test_decision(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": "20260727",
                    "comparison_target_action_id": "P7-ACT-001",
                    "comparison_outcome": "incumbent_keeps",
                    "decision_type": "retire_candidate",
                    "decision_reason": "Candidate is retired after guardrail outcome",
                    "decided_by": "architect.openclaw@gmail.com",
                },
                project_root=root,
            )

            self.assertEqual(result["decision_type"], "retire_candidate")
            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            self.assertEqual(challenger["lifecycle_state"], "candidate_retired")
            self.assertEqual(challenger["launch_status"], "retired")
            self.assertEqual(challenger["stat_test_status"], "blocked")
            self.assertEqual(challenger["block_reason"], "candidate_retired_post_test")


    def test_build_phase7_post_test_decision_queue_returns_challenger_with_active_incumbent_candidates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")

            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            incumbent = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-001")
            incumbent["approval_status"] = "approved"
            incumbent["lifecycle_state"] = "active_winner"
            incumbent["latest_stat_run_id"] = "p7-stat-incumbent"
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            challenger["approval_status"] = "approved"
            challenger["lifecycle_state"] = "stat_test_completed"
            challenger["latest_stat_run_id"] = "p7-stat-challenger"
            challenger["latest_verdict"] = "B_wins"
            challenger["primary_kpi"] = "checkout_completion_rate"
            challenger["recommended_kpi"] = "checkout_completion_rate"
            challenger["guardrail_kpi"] = "opt_out_rate"
            challenger["launch_ts"] = "2026-07-27T01:00:00Z"
            challenger["latest_stat_completed_at"] = "2026-07-27T02:00:00Z"
            challenger["latest_conversion_lift"] = 0.035
            challenger["synthetic_previous_action"] = {
                "action_id": "P7-ACT-001",
                "article_title": "Incumbent",
                "status_label": "Current action",
                "summary": "Summary A",
                "latest_stat_run_id": "p7-stat-incumbent",
            }
            (root / "data" / "processed" / "phase7_integrated_actions_20260727.json").write_text(
                json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
            )

            queue = build_phase7_post_test_decision_queue(project_root=root, run_date="20260727")
            self.assertEqual(queue["pending_count"], 1)
            pending = queue["pending_decisions"][0]
            self.assertEqual(pending["action_id"], "P7-ACT-002")
            self.assertEqual(pending["allowed_comparison_outcomes"], ["candidate_wins"])
            self.assertEqual(len(pending["candidate_incumbents"]), 1)
            self.assertEqual(pending["candidate_incumbents"][0]["action_id"], "P7-ACT-001")

    def test_build_phase7_post_test_decision_queue_keeps_empty_incumbent_list_when_none_available(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")

            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            challenger = integrated["actions"][0]
            challenger["approval_status"] = "approved"
            challenger["lifecycle_state"] = "stat_test_completed"
            challenger["latest_stat_run_id"] = "p7-stat-challenger"
            challenger["latest_verdict"] = "B_wins"
            challenger["primary_kpi"] = "checkout_completion_rate"
            challenger["recommended_kpi"] = "checkout_completion_rate"
            challenger["guardrail_kpi"] = "opt_out_rate"
            challenger["launch_ts"] = "2026-07-27T01:00:00Z"
            challenger["latest_stat_completed_at"] = "2026-07-27T02:00:00Z"
            challenger["latest_conversion_lift"] = 0.035
            (root / "data" / "processed" / "phase7_integrated_actions_20260727.json").write_text(
                json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
            )

            queue = build_phase7_post_test_decision_queue(project_root=root, run_date="20260727")
            self.assertEqual(queue["pending_count"], 1)
            pending = queue["pending_decisions"][0]
            self.assertEqual(pending["action_id"], "P7-ACT-002")
            self.assertEqual(pending["candidate_incumbents"], [])

    def test_build_phase7_post_test_decision_queue_skips_actions_with_decision_already_taken(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "Incumbent",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")

            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            incumbent = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-001")
            incumbent["approval_status"] = "approved"
            incumbent["lifecycle_state"] = "active_winner"
            challenger = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            challenger["approval_status"] = "approved"
            challenger["lifecycle_state"] = "stat_test_completed"
            challenger["latest_stat_run_id"] = "p7-stat-challenger"
            challenger["latest_verdict"] = "B_wins"
            challenger["decision_type"] = "promote_challenger"
            (root / "data" / "processed" / "phase7_integrated_actions_20260727.json").write_text(
                json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
            )

            queue = build_phase7_post_test_decision_queue(project_root=root, run_date="20260727")
            self.assertEqual(queue["pending_count"], 0)
            self.assertEqual(queue["pending_decisions"], [])

    def test_build_phase7_post_test_decision_queue_skips_actions_without_completed_state_or_recognized_verdict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "Nielsen Norman Group",
                        "article_title": "State mismatch challenger",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    },
                    {
                        "proposal_id": "P7-DRAFT-002",
                        "source_name": "Baymard Institute",
                        "article_title": "Unknown verdict challenger",
                        "article_url": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary_for_business": "Summary B",
                        "pros": ["Pro B"],
                        "cons": ["Con B"],
                        "recommended_action": "Action B",
                        "generation_contract_violation": False,
                    },
                ],
                "validation": [
                    {"proposal_id": "P7-DRAFT-001", "passed": True},
                    {"proposal_id": "P7-DRAFT-002", "passed": True},
                ],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            build_integrated_actions(project_root=root, run_date="20260727")

            integrated = load_integrated_actions(project_root=root, run_date="20260727")
            state_mismatch = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-001")
            state_mismatch["approval_status"] = "approved"
            state_mismatch["lifecycle_state"] = "approved_for_stat_test"
            state_mismatch["latest_stat_run_id"] = "p7-stat-state-mismatch"
            state_mismatch["latest_verdict"] = "B_wins"

            unknown_verdict = next(action for action in integrated["actions"] if action["action_id"] == "P7-ACT-002")
            unknown_verdict["approval_status"] = "approved"
            unknown_verdict["lifecycle_state"] = "stat_test_completed"
            unknown_verdict["latest_stat_run_id"] = "p7-stat-unknown-verdict"
            unknown_verdict["latest_verdict"] = "needs_manual_review"

            (root / "data" / "processed" / "phase7_integrated_actions_20260727.json").write_text(
                json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
            )

            queue = build_phase7_post_test_decision_queue(project_root=root, run_date="20260727")
            self.assertEqual(queue["pending_count"], 0)
            self.assertEqual(queue["pending_decisions"], [])

    def test_load_integrated_actions_uses_short_ttl_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            payload = {
                "drafts": [
                    {
                        "proposal_id": "P7-DRAFT-001",
                        "source_name": "NNG",
                        "article_title": "Cached action",
                        "article_url": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary_for_business": "Summary A",
                        "pros": ["Pro A"],
                        "cons": ["Con A"],
                        "recommended_action": "Action A",
                        "generation_contract_violation": False,
                    }
                ],
                "validation": [{"proposal_id": "P7-DRAFT-001", "passed": True}],
            }
            (root / "data" / "processed" / "phase7_action_drafts_20260727.json").write_text(json.dumps(payload), encoding="utf-8")
            build_integrated_actions(project_root=root, run_date="20260727")

            integrated_path = root / "data" / "processed" / "phase7_integrated_actions_20260727.json"
            phase7_integration_module._INTEGRATED_ACTIONS_CACHE.clear()
            original_read_text = Path.read_text
            read_calls = []

            def tracked_read_text(path_self: Path, *args, **kwargs):
                if path_self == integrated_path:
                    read_calls.append(path_self)
                return original_read_text(path_self, *args, **kwargs)

            with mock.patch.object(Path, "read_text", tracked_read_text):
                first = load_integrated_actions(project_root=root, run_date="20260727")
                second = load_integrated_actions(project_root=root, run_date="20260727")

            self.assertEqual(first["run_date"], "20260727")
            self.assertEqual(second["run_date"], "20260727")
            self.assertEqual(len(read_calls), 1)


if __name__ == "__main__":
    unittest.main()
