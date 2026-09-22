import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_tmpdir = tempfile.TemporaryDirectory()
os.environ["CHURN_DB_URL"] = f"sqlite:///{Path(_tmpdir.name) / 'test_ops.sqlite'}"
os.environ["PHASE7_REVIEW_TOKEN"] = "phase7-fastapi-token"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient

from api import churn_service
from api.fastapi_app import app
from evidence.phase7_artifacts import REAL_MODE
from evidence.phase7_integration import (
    build_integrated_actions,
    load_integrated_actions,
)


class TestFastApiAppContract(unittest.TestCase):
    RUN_DATE = "20990101"

    @classmethod
    def setUpClass(cls):
        cls._previous_mode = os.environ.pop("MODE", None)
        churn_service.DEFAULT_DB_URL = os.environ["CHURN_DB_URL"]
        churn_service._ops_engine().dispose()
        churn_service._ops_engine.cache_clear()
        cls.client = TestClient(app)
        cls._prepare_phase7_fixture(cls.RUN_DATE)

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_phase7_fixture(cls.RUN_DATE)
        if cls._previous_mode is not None:
            os.environ["MODE"] = cls._previous_mode
        cached_engine = churn_service._ops_engine()
        cached_engine.dispose()
        churn_service._ops_engine.cache_clear()
        _tmpdir.cleanup()

    @classmethod
    def _phase7_headers(cls) -> dict[str, str]:
        return {"X-Phase7-Token": os.environ["PHASE7_REVIEW_TOKEN"]}

    @classmethod
    def _cleanup_phase7_fixture(cls, run_date: str) -> None:
        processed = PROJECT_ROOT / "data" / "processed"
        reports = PROJECT_ROOT / "reports"
        for path in [
            processed / f"phase7_action_drafts_{run_date}.json",
            processed / f"phase7_integrated_actions_{run_date}.json",
            processed / f"phase7_kpi_status_{run_date}.json",
            processed / f"phase7_n8n_payload_{run_date}.json",
            reports / f"phase7_integrated_actions_{run_date}.md",
            reports / f"phase7_kpi_status_{run_date}.md",
        ]:
            if path.exists():
                path.unlink()

        for parquet_path in [
            processed / "phase7_action_history_log.parquet",
            processed / "phase7_stat_launch_requests.parquet",
            processed / "phase7_stat_test_runs.parquet",
        ]:
            if parquet_path.exists():
                parquet_path.unlink()

    @classmethod
    def _prepare_phase7_fixture(cls, run_date: str) -> None:
        cls._cleanup_phase7_fixture(run_date)
        processed = PROJECT_ROOT / "data" / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        draft_source = PROJECT_ROOT / "tests" / "fixtures" / "phase7_action_drafts_20260727.json"
        draft_target = processed / f"phase7_action_drafts_{run_date}.json"
        draft_target.write_text(draft_source.read_text(encoding="utf-8"), encoding="utf-8")
        build_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date, mode=REAL_MODE)

    def test_public_html_routes_return_200_without_token(self):
        for path, marker in [
            (f"/customer-churn/dashboard?run_date={self.RUN_DATE}", "CHURN CAMPAIGNS DASHBOARD"),
            (f"/customer-churn/tested-actions-approval?run_date={self.RUN_DATE}", "Tested Actions Approval"),
            (f"/customer-churn/new-actions-testing?run_date={self.RUN_DATE}", "New Actions Approval"),
        ]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(marker, response.text)

    def test_public_data_routes_return_200_and_non_empty_payload_without_token(self):
        response = self.client.get(f"/customer-churn/dashboard/data?run_date={self.RUN_DATE}")
        self.assertEqual(response.status_code, 200)
        dashboard_payload = response.json()
        self.assertEqual(dashboard_payload["requested_run_date"], self.RUN_DATE)
        self.assertGreater(len(dashboard_payload["campaign_rows"]), 0)

        for path in [
            f"/customer-churn/tested-actions-approval/data?run_date={self.RUN_DATE}",
            f"/customer-churn/new-actions-testing/data?run_date={self.RUN_DATE}",
        ]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["run_date"], self.RUN_DATE)
            self.assertGreater(len(payload["pending_pre_test_actions"]), 0)

    def test_phase7_decision_requires_token_and_accepts_valid_token(self):
        before = load_integrated_actions(project_root=PROJECT_ROOT, run_date=self.RUN_DATE)
        action_id = next(
            action["action_id"]
            for action in before["actions"]
            if action.get("approval_status") == "pending_review"
        )

        missing_token_response = self.client.post(
            "/phase7/actions/decision",
            json={
                "action_id": action_id,
                "proposal_run_date": self.RUN_DATE,
                "decision_status": "approved",
                "decision_reason": "Missing token contract check",
                "decided_by": "architect.openclaw@gmail.com",
            },
        )
        self.assertEqual(missing_token_response.status_code, 401)
        self.assertEqual(missing_token_response.json()["error"], "Phase 7 review token is required")

        valid_token_response = self.client.post(
            "/phase7/actions/decision",
            json={
                "action_id": action_id,
                "proposal_run_date": self.RUN_DATE,
                "decision_status": "approved",
                "decision_reason": "Valid token contract acceptance check",
                "decided_by": "architect.openclaw@gmail.com",
            },
            headers=self._phase7_headers(),
        )
        self.assertEqual(valid_token_response.status_code, 201)

    def test_phase7_post_test_decision_requires_token_and_accepts_valid_token(self):
        run_date = "20990102"
        self._prepare_phase7_fixture(run_date)

        integrated_refresh = self.client.get(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")
        self.assertEqual(integrated_refresh.status_code, 200)
        integrated_payload = integrated_refresh.json()
        pending_actions = [
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        ]
        incumbent_action_id, challenger_action_id = pending_actions[:2]

        for action_id, reason in ((incumbent_action_id, "Incumbent active"), (challenger_action_id, "Challenger approved")):
            decision_response = self.client.post(
                "/phase7/actions/decision",
                json={
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": reason,
                    "decided_by": "architect.openclaw@gmail.com",
                },
                headers=self._phase7_headers(),
            )
            self.assertEqual(decision_response.status_code, 201)

        integrated = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        incumbent = next(action for action in integrated["actions"] if action["action_id"] == incumbent_action_id)
        incumbent["lifecycle_state"] = "active_winner"
        incumbent["latest_stat_run_id"] = "p7-stat-incumbent"
        (PROJECT_ROOT / "data" / "processed" / f"phase7_integrated_actions_{run_date}.json").write_text(
            json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
        )

        create_launch_response = self.client.post(
            "/phase7/stat-launch-requests",
            json={
                "action_id": challenger_action_id,
                "proposal_run_date": run_date,
                "requested_by": "architect.openclaw@gmail.com",
                "control_n": 1200,
                "control_converted": 108,
                "control_opt_out": 12,
                "variant_n": 1200,
                "variant_converted": 180,
                "variant_opt_out": 12,
            },
            headers=self._phase7_headers(),
        )
        self.assertEqual(create_launch_response.status_code, 201)
        launch_request_id = create_launch_response.json()["launch_request_id"]

        execute_launch_response = self.client.post(
            "/phase7/stat-launch-requests/execute",
            json={
                "launch_request_id": launch_request_id,
                "executed_by": "architect.openclaw@gmail.com",
            },
            headers=self._phase7_headers(),
        )
        self.assertEqual(execute_launch_response.status_code, 201)

        missing_token_response = self.client.post(
            "/phase7/actions/post-test-decision",
            json={
                "action_id": challenger_action_id,
                "proposal_run_date": run_date,
                "comparison_target_action_id": incumbent_action_id,
                "comparison_outcome": "candidate_wins",
                "decision_type": "promote_challenger",
                "previous_incumbent_status": "replaced",
                "decision_reason": "Promote challenger over the active incumbent",
                "decided_by": "architect.openclaw@gmail.com",
            },
        )
        self.assertEqual(missing_token_response.status_code, 401)

        valid_token_response = self.client.post(
            "/phase7/actions/post-test-decision",
            json={
                "action_id": challenger_action_id,
                "proposal_run_date": run_date,
                "comparison_target_action_id": incumbent_action_id,
                "comparison_outcome": "candidate_wins",
                "decision_type": "promote_challenger",
                "previous_incumbent_status": "replaced",
                "decision_reason": "Promote challenger over the active incumbent",
                "decided_by": "architect.openclaw@gmail.com",
            },
            headers=self._phase7_headers(),
        )
        self.assertEqual(valid_token_response.status_code, 201)

        self._cleanup_phase7_fixture(run_date)


if __name__ == "__main__":
    unittest.main()
