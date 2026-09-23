import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd
import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api import churn_service
from api.churn_service import COUPON_REGISTRY_PATH
from evidence.phase6_integration import build_action_proposals
from evidence.phase7_integration import load_integrated_actions


class TestChurnService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls._previous_app_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "test"
        os.environ["CHURN_DB_URL"] = f"sqlite:///{Path(cls._tmpdir.name) / 'test_ops.sqlite'}"
        os.environ["PHASE7_REVIEW_TOKEN"] = "phase7-test-token"
        churn_service.DEFAULT_DB_URL = os.environ["CHURN_DB_URL"]
        churn_service._ops_engine().dispose()
        churn_service._ops_engine.cache_clear()
        cls._registry_backup = None
        if COUPON_REGISTRY_PATH.exists():
            cls._registry_backup = COUPON_REGISTRY_PATH.read_text(encoding="utf-8")
        COUPON_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        COUPON_REGISTRY_PATH.write_text("", encoding="utf-8")

        from api.fastapi_app import app

        cls.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.socket.bind(("127.0.0.1", 0))
        cls.socket.listen(5)
        cls.port = cls.socket.getsockname()[1]
        config = uvicorn.Config(app, log_level="warning", lifespan="off")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(
            target=cls.server.run,
            kwargs={"sockets": [cls.socket]},
            daemon=True,
        )
        cls.thread.start()
        for _ in range(100):
            if cls.server.started:
                break
            time.sleep(0.05)
        else:
            raise RuntimeError("FastAPI/Uvicorn test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.socket.close()
        if cls._registry_backup is None:
            if COUPON_REGISTRY_PATH.exists():
                COUPON_REGISTRY_PATH.unlink()
        else:
            COUPON_REGISTRY_PATH.write_text(cls._registry_backup, encoding="utf-8")
        cached_engine = churn_service._ops_engine()
        cached_engine.dispose()
        churn_service._ops_engine.cache_clear()
        if cls._previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = cls._previous_app_env
        cls._tmpdir.cleanup()

    def _url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def _phase7_headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json", "X-Phase7-Token": os.environ["PHASE7_REVIEW_TOKEN"]}

    def _reset_phase7_run_state(self, run_date: str) -> None:
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

        parquet_paths = [
            processed / "phase7_action_history_log.parquet",
            processed / "phase7_stat_launch_requests.parquet",
            processed / "phase7_stat_test_runs.parquet",
        ]
        for parquet_path in parquet_paths:
            if parquet_path.exists():
                parquet_path.unlink()

    def _prepare_phase7_draft_fixture(self, run_date: str) -> None:
        self._reset_phase7_run_state(run_date)
        draft_source = PROJECT_ROOT / "tests" / "fixtures" / "phase7_action_drafts_20260727.json"
        draft_target = PROJECT_ROOT / "data" / "processed" / f"phase7_action_drafts_{run_date}.json"
        draft_target.write_text(draft_source.read_text(encoding="utf-8"), encoding="utf-8")

    def test_health_endpoint(self):
        with urlopen(self._url("/health")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertIn("run_id", payload)
        self.assertIn("run_date_tag", payload)
        self.assertIn("model_version", payload)
        self.assertIn("risk_thresholds", payload)

    def test_explainability_latest_endpoint(self):
        with urlopen(self._url("/explainability/latest?limit=5")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("source_file", payload)
        self.assertIn("records", payload)
        self.assertLessEqual(payload["record_count"], 5)
        self.assertEqual(len(payload["records"]), payload["record_count"])

    def test_thresholds_latest_endpoint(self):
        with urlopen(self._url("/thresholds/latest")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertIn("run_id", payload)
        self.assertIn("run_date_tag", payload)
        self.assertIn("risk_thresholds", payload)
        self.assertIn("high_min_score", payload["risk_thresholds"])
        self.assertIn("medium_min_score", payload["risk_thresholds"])

    def test_coupon_generation_endpoint(self):
        request = Request(
            self._url("/coupons/generate"),
            data=json.dumps(
                {
                    "customer_unique_id": "cust_001",
                    "risk_tier": "HIGH",
                    "discount_pct": 25,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 201)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["customer_unique_id"], "cust_001")
        self.assertEqual(payload["risk_tier"], "HIGH")
        self.assertIn("run_id", payload)
        self.assertIn("run_date_tag", payload)
        self.assertRegex(payload["coupon_code"], r"^VIVA-[A-Z0-9]{4}-[A-Z0-9]{4}$")

    def test_coupon_generation_validation(self):
        request = Request(
            self._url("/coupons/generate"),
            data=json.dumps({"customer_unique_id": "cust_001"}).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request)
        self.assertEqual(context.exception.code, 400)

    def test_event_health_endpoint(self):
        with urlopen(self._url("/health/events")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["event_table"], "retention_events")

    def test_agent_status_endpoint(self):
        with urlopen(self._url("/agent/status")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["shadow_mode"])
        self.assertIn("drift", payload)
        self.assertIn("tier_distribution", payload)
        self.assertIn("holdout_lift", payload)
        self.assertIn("conversion_rates", payload)
        self.assertIn("agent_action_required", payload)
        self.assertEqual(payload["decision_log_table"], "agent_decision_log")
        self.assertIn("pending_human_decision_count", payload)

    def test_agent_daily_status_endpoint(self):
        with urlopen(self._url("/agent/status/daily?refresh=true")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("gate", payload)
        self.assertIn("decision_quality", payload)
        self.assertIn("operational_status", payload)
        self.assertIn("artifacts", payload)
        self.assertTrue(payload["artifacts"]["refreshed"])
        self.assertIn("markdown_preview", payload)
        self.assertEqual(payload["gate"]["target_shadow_days"], 14)

    def test_agent_shadow_monitor_status_endpoint(self):
        with urlopen(self._url("/agent/status/shadow-monitor?refresh=true")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("summary", payload)
        self.assertIn("status_snapshot", payload)
        self.assertIn("recent_cycles", payload)
        self.assertIn("artifacts", payload)
        self.assertTrue(payload["artifacts"]["refreshed"])
        self.assertEqual(payload["artifacts"]["html"].replace("\\", "/"), "reports/phase5_shadow_monitor_latest.html")

    def test_agent_phase5_operational_status_endpoint(self):
        with urlopen(self._url("/agent/status/phase5?refresh=true")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["phase"], "phase5")
        self.assertIn("agent_status", payload)
        self.assertIn("daily_status", payload)
        self.assertIn("shadow_monitor", payload)
        self.assertTrue(payload["daily_status"]["artifacts"]["refreshed"])
        self.assertTrue(payload["shadow_monitor"]["artifacts"]["refreshed"])

    def test_shadow_decision_logging_endpoint(self):
        request = Request(
            self._url("/agent/decisions/shadow"),
            data=json.dumps(
                {
                    "decision_type": "dispatch_confirm",
                    "agent_decision": "dispatch_confirm",
                    "rationale": "Synthetic governance baseline shows no active triggers.",
                    "cycle_date": "2026-06-05",
                    "input_snapshot": {"agent_action_required": False},
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 201)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(payload["shadow_mode"])
        self.assertEqual(payload["decision_type"], "dispatch_confirm")
        self.assertEqual(payload["monitor_refresh"]["status"], "ok")
        self.assertEqual(payload["monitor_refresh"]["trigger"], "shadow_create")
        self.assertEqual(payload["monitor_refresh"]["daily_status_refresh"]["status"], "ok")

        with urlopen(self._url("/agent/status")) as response:
            status_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(status_payload["shadow_log_count"], 1)

    def test_shadow_decision_run_endpoint(self):
        with patch(
            "api.churn_service._refresh_shadow_monitor_artifacts",
            return_value={
                "status": "ok",
                "trigger": "shadow_run",
                "daily_status_refresh": {"status": "ok"},
            },
        ):
            request = Request(
                self._url("/agent/decisions/shadow/run"),
                data=json.dumps({"cycle_date": "2026-06-06"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request) as response:
                self.assertEqual(response.status, 201)
                payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["decision_type"], "dispatch_confirm")
        self.assertEqual(payload["agent_decision"], "dispatch_confirm")
        self.assertEqual(payload["scenario"], "normal_cycle_no_anomalies")
        self.assertFalse(payload["escalation_required"])
        self.assertEqual(payload["monitor_refresh"]["status"], "ok")
        self.assertEqual(payload["monitor_refresh"]["daily_status_refresh"]["status"], "ok")

    def test_shadow_decision_reconcile_endpoint(self):
        with patch(
            "api.churn_service._refresh_shadow_monitor_artifacts",
            return_value={"status": "ok", "trigger": "shadow_run", "daily_status_refresh": {"status": "ok"}},
        ):
            run_request = Request(
                self._url("/agent/decisions/shadow/run"),
                data=json.dumps({"cycle_date": "2026-06-07"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(run_request) as response:
                run_payload = json.loads(response.read().decode("utf-8"))

        with patch(
            "api.churn_service._refresh_shadow_monitor_artifacts",
            return_value={"status": "ok", "trigger": "shadow_reconcile", "daily_status_refresh": {"status": "ok"}},
        ):
            reconcile_request = Request(
                self._url("/agent/decisions/shadow/reconcile"),
                data=json.dumps(
                    {
                        "record_id": run_payload["record_id"],
                        "human_decision": "dispatch_confirm",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(reconcile_request) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "ok")

    def test_phase6_proposals_endpoint_and_decision_history(self):
        build_payload = build_action_proposals(project_root=PROJECT_ROOT, run_date="20260724")
        with urlopen(self._url(f"/phase6/proposals/latest?run_date={build_payload['run_date']}")) as response:
            self.assertEqual(response.status, 200)
            proposals_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(proposals_payload["proposal_count"], 1)
        proposal_id = proposals_payload["proposals"][0]["proposal_id"]

        decision_request = Request(
            self._url("/phase6/proposals/decision"),
            data=json.dumps(
                {
                    "proposal_id": proposal_id,
                    "proposal_run_date": build_payload["run_date"],
                    "decision_status": "approved",
                    "decision_reason": "Approved for simulated launch",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)
            decision_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(decision_payload["decision_status"], "approved")

        with urlopen(self._url("/phase6/action-history/latest")) as response:
            self.assertEqual(response.status, 200)
            history_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(history_payload["record_count"], 1)

    def test_phase6_ab_launch_kpi_and_n8n_endpoints(self):
        build_payload = build_action_proposals(project_root=PROJECT_ROOT, run_date="20260725")
        with urlopen(self._url(f"/phase6/proposals/latest?run_date={build_payload['run_date']}")) as response:
            proposals_payload = json.loads(response.read().decode("utf-8"))
        proposal_id = proposals_payload["proposals"][0]["proposal_id"]

        decision_request = Request(
            self._url("/phase6/proposals/decision"),
            data=json.dumps(
                {
                    "proposal_id": proposal_id,
                    "proposal_run_date": build_payload["run_date"],
                    "decision_status": "approved",
                    "decision_reason": "Approved for simulated launch",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)

        launch_request = Request(
            self._url("/phase6/ab-tests/launch"),
            data=json.dumps(
                {
                    "proposal_id": proposal_id,
                    "proposal_run_date": build_payload["run_date"],
                    "launched_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(launch_request) as response:
            self.assertEqual(response.status, 201)
            launch_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(launch_payload["status"], "completed")

        with urlopen(self._url("/phase6/kpis/latest?refresh=true")) as response:
            self.assertEqual(response.status, 200)
            kpi_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(kpi_payload["test_count"], 1)

        with urlopen(self._url(f"/phase6/n8n-payload/latest?run_date={build_payload['run_date']}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            n8n_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(n8n_payload["action_count"], 1)

    def test_phase7_reporting_page_endpoint(self):
        run_date = "20260730"
        processed = PROJECT_ROOT / "data" / "processed"
        phase6_kpi_path = processed / "phase6_kpi_status_20260730.json"
        history_path = processed / "phase7_action_history_log.parquet"

        existing_kpi = phase6_kpi_path.read_text(encoding="utf-8") if phase6_kpi_path.exists() else None
        existing_history = history_path.read_bytes() if history_path.exists() else None
        try:
            phase6_kpi_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "generated_at": "2026-07-30T08:00:00Z",
                        "deployment_mode": "simulated",
                        "test_count": 1,
                        "records": [
                            {
                                "proposal_id": "p6-001",
                                "primary_kpi": "conversion_rate",
                                "status": "completed",
                                "verdict": "B_wins",
                                "conversion_lift": 0.03,
                                "guardrail_breach": False,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            pd.DataFrame(
                [
                    {
                        "event_id": "evt-reporting-1",
                        "event_type": "governance_decision",
                        "action_id": "P7-ACT-010",
                        "proposal_id": "P7-DRAFT-010",
                        "proposal_run_date": run_date,
                        "decision_status": "approved",
                        "decision_reason": "Approved for reporting page",
                    }
                ]
            ).to_parquet(history_path, index=False)

            with urlopen(self._url(f"/customer-churn/dashboard?run_date={run_date}")) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("text/html", response.headers.get("Content-Type", ""))
                body = response.read().decode("utf-8")
            self.assertIn("CHURN CAMPAIGNS DASHBOARD", body)
            self.assertIn("History of all actions", body)
            self.assertIn("/static/js/dashboard.js", body)
            self.assertNotIn("/phase7/actions/post-test-decision", body)
            self.assertNotIn("/phase7/stat-launch-requests", body)
        finally:
            if existing_kpi is None:
                phase6_kpi_path.unlink(missing_ok=True)
            else:
                phase6_kpi_path.write_text(existing_kpi, encoding="utf-8")
            if existing_history is None:
                history_path.unlink(missing_ok=True)
            else:
                history_path.write_bytes(existing_history)

    def test_phase7_review_page_2_2_endpoints_and_token_gate(self):
        run_date = "20260726"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            integrated_payload = json.loads(response.read().decode("utf-8"))

        pending_actions = [
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        ]
        incumbent_action_id, challenger_action_id = pending_actions[:2]

        for action_id, reason in ((incumbent_action_id, "Incumbent active"), (challenger_action_id, "Challenger approved")):
            decision_request = Request(
                self._url("/phase7/actions/decision"),
                data=json.dumps(
                    {
                        "action_id": action_id,
                        "proposal_run_date": run_date,
                        "decision_status": "approved",
                        "decision_reason": reason,
                        "decided_by": "architect.openclaw@gmail.com",
                    }
                ).encode("utf-8"),
                headers=self._phase7_headers(),
                method="POST",
            )
            with urlopen(decision_request) as response:
                self.assertEqual(response.status, 201)

        integrated = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        incumbent = next(action for action in integrated["actions"] if action["action_id"] == incumbent_action_id)
        incumbent["lifecycle_state"] = "active_winner"
        (PROJECT_ROOT / "data" / "processed" / f"phase7_integrated_actions_{run_date}.json").write_text(
            json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
        )

        create_launch_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 180,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(create_launch_request) as response:
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)

        with urlopen(self._url(f"/customer-churn/tested-actions-approval?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            body = response.read().decode("utf-8")
        self.assertIn("Tested Actions Approval", body)
        self.assertIn("Review each tested action before replacing the current incumbent", body)
        self.assertIn("/static/js/tested-actions.js", body)
        self.assertNotIn("/phase7/actions/decision", body)
        self.assertNotIn("setInterval", body)

        with urlopen(self._url(f"/customer-churn/tested-actions-approval/data?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("pending_pre_test_actions", payload)
        self.assertGreaterEqual(payload["post_test_pending_count"], 1)
        self.assertIn(
            challenger_action_id,
            [entry["action_id"] for entry in payload["pending_post_test_decisions"]],
        )

        invalid_data_request = Request(
            self._url(f"/customer-churn/tested-actions-approval/data?run_date={run_date}"),
            headers={"X-Phase7-Token": "wrong-token"},
        )
        with urlopen(invalid_data_request) as response:
            self.assertEqual(response.status, 200)

    def test_phase7_review_token_rejects_write_before_persisting_any_change(self):
        run_date = "20260732"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            integrated_payload = json.loads(response.read().decode("utf-8"))
        action_id = next(
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        )

        before = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        before_action = next(action for action in before["actions"] if action["action_id"] == action_id)
        self.assertEqual(before_action["approval_status"], "pending_review")

        invalid_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": "Should be rejected atomically",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": "wrong-token"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(invalid_request)
        self.assertEqual(context.exception.code, 401)

        after = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        after_action = next(action for action in after["actions"] if action["action_id"] == action_id)
        self.assertEqual(after_action["approval_status"], before_action["approval_status"])
        self.assertEqual(after_action["lifecycle_state"], before_action["lifecycle_state"])
        self.assertEqual(after_action.get("decision_reason"), before_action.get("decision_reason"))

    def test_phase7_review_token_rejects_launch_request_and_execute_routes(self):
        run_date = "20260735"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            integrated_payload = json.loads(response.read().decode("utf-8"))
        action_id = next(
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        )

        decision_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": "Approved for launch-request auth test",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)

        invalid_create_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": "wrong-token"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(invalid_create_request)
        self.assertEqual(context.exception.code, 401)

        with urlopen(self._url(f"/phase7/stat-launch-requests/latest?run_date={run_date}")) as response:
            requests_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(requests_payload["requests"], [])

        valid_create_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(valid_create_request) as response:
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        invalid_execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": "wrong-token"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(invalid_execute_request)
        self.assertEqual(context.exception.code, 401)

        with urlopen(self._url(f"/phase7/stat-launch-requests/latest?run_date={run_date}")) as response:
            requests_after = json.loads(response.read().decode("utf-8"))
        pending = [row for row in requests_after["requests"] if row["launch_request_id"] == launch_request_payload["launch_request_id"]]
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["request_status"], "pending_execution")

    def test_phase7_review_page_post_test_write_persists_and_refreshes_queue_state(self):
        run_date = "20260733"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            integrated_payload = json.loads(response.read().decode("utf-8"))

        pending_actions = [
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        ]
        incumbent_action_id, challenger_action_id = pending_actions[:2]

        for action_id, reason in ((incumbent_action_id, "Incumbent active"), (challenger_action_id, "Challenger approved")):
            decision_request = Request(
                self._url("/phase7/actions/decision"),
                data=json.dumps(
                    {
                        "action_id": action_id,
                        "proposal_run_date": run_date,
                        "decision_status": "approved",
                        "decision_reason": reason,
                        "decided_by": "architect.openclaw@gmail.com",
                    }
                ).encode("utf-8"),
                headers=self._phase7_headers(),
                method="POST",
            )
            with urlopen(decision_request) as response:
                self.assertEqual(response.status, 201)

        integrated = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        incumbent = next(action for action in integrated["actions"] if action["action_id"] == incumbent_action_id)
        incumbent["lifecycle_state"] = "active_winner"
        (PROJECT_ROOT / "data" / "processed" / f"phase7_integrated_actions_{run_date}.json").write_text(
            json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
        )

        create_launch_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 180,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(create_launch_request) as response:
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)

        with urlopen(self._url(f"/customer-churn/tested-actions-approval/data?run_date={run_date}")) as response:
            before_payload = json.loads(response.read().decode("utf-8"))
        self.assertIn(
            challenger_action_id,
            [entry["action_id"] for entry in before_payload["pending_post_test_decisions"]],
        )

        post_test_request = Request(
            self._url("/phase7/actions/post-test-decision"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "comparison_target_action_id": incumbent_action_id,
                    "comparison_outcome": "candidate_wins",
                    "decision_type": "promote_challenger",
                    "previous_incumbent_status": "replaced",
                    "decision_reason": "Promote challenger over the active incumbent",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(post_test_request) as response:
            self.assertEqual(response.status, 201)

        with urlopen(self._url(f"/customer-churn/tested-actions-approval/data?run_date={run_date}")) as response:
            after_payload = json.loads(response.read().decode("utf-8"))
        self.assertNotIn(
            challenger_action_id,
            [entry["action_id"] for entry in after_payload["pending_post_test_decisions"]],
        )

        integrated_after = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        challenger_after = next(action for action in integrated_after["actions"] if action["action_id"] == challenger_action_id)
        self.assertEqual(challenger_after["decision_type"], "promote_challenger")

    def test_phase7_integrated_actions_and_stat_launch_endpoints(self):
        run_date = "20260728"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            integrated_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(integrated_payload["integrated"]["action_count"], 1)
        action_id = next(
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        )

        decision_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": "Approved for statistical evaluation",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)

        create_launch_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(create_launch_request) as response:
            self.assertEqual(response.status, 201)
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)
            launch_payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(launch_payload["action_id"], action_id)
        self.assertEqual(launch_payload["verdict"], "no_significant_difference")

        with urlopen(self._url(f"/phase7/stat-tests/latest?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            stat_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(stat_payload["stat_run_count"], 1)

        with urlopen(self._url(f"/phase7/stat-launch-requests/latest?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            requests_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(len(requests_payload["requests"]), 1)

        with urlopen(self._url(f"/phase7/action-history/latest?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            history_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(len(history_payload["history"]), 2)
        self.assertNotIn("stat_launch_requested", [row["event_type"] for row in history_payload["history"]])
        self.assertTrue(all(row["visibility_status"].startswith("visible") for row in history_payload["history"]))

    def test_phase7_direct_stat_launch_endpoint_is_no_longer_public(self):
        request = Request(
            self._url("/phase7/stat-tests/launch"),
            data=json.dumps(
                {
                    "action_id": "P7-ACT-003",
                    "proposal_run_date": "20260727",
                    "launched_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request)
        self.assertEqual(ctx.exception.code, 410)
        payload = json.loads(ctx.exception.read().decode("utf-8"))
        self.assertTrue(payload["deprecated"])

    def test_phase7_kpi_and_n8n_endpoints(self):
        run_date = "20260730"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            integrated_payload = json.loads(response.read().decode("utf-8"))
        action_id = next(
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        )

        decision_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "decision_status": "approved",
                    "decision_reason": "Approved for statistical evaluation",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)

        create_launch_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 111,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(create_launch_request) as response:
            self.assertEqual(response.status, 201)
            launch_request_payload = json.loads(response.read().decode("utf-8"))
        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)
        with urlopen(self._url(f"/phase7/kpis/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            kpi_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(kpi_payload["stat_run_count"], 1)
        with urlopen(self._url(f"/phase7/n8n-payload/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            n8n_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(n8n_payload["action_count"], 1)

    def test_phase7_post_test_decision_pending_endpoint(self):
        run_date = "20260731"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            integrated_payload = json.loads(response.read().decode("utf-8"))

        pending_actions = [
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        ]
        incumbent_action_id, challenger_action_id = pending_actions[:2]

        for action_id, reason in ((incumbent_action_id, "Incumbent active"), (challenger_action_id, "Challenger approved")):
            decision_request = Request(
                self._url("/phase7/actions/decision"),
                data=json.dumps(
                    {
                        "action_id": action_id,
                        "proposal_run_date": run_date,
                        "decision_status": "approved",
                        "decision_reason": reason,
                        "decided_by": "architect.openclaw@gmail.com",
                    }
                ).encode("utf-8"),
                headers=self._phase7_headers(),
                method="POST",
            )
            with urlopen(decision_request) as response:
                self.assertEqual(response.status, 201)

        integrated = load_integrated_actions(project_root=PROJECT_ROOT, run_date=run_date)
        incumbent = next(action for action in integrated["actions"] if action["action_id"] == incumbent_action_id)
        incumbent["lifecycle_state"] = "active_winner"
        incumbent["latest_stat_run_id"] = "p7-stat-incumbent"
        (PROJECT_ROOT / "data" / "processed" / f"phase7_integrated_actions_{run_date}.json").write_text(
            json.dumps(integrated, indent=2) + "\n", encoding="utf-8"
        )

        post_test_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 180,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(post_test_request) as response:
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)

        with urlopen(self._url(f"/phase7/post-test-decisions/pending?run_date={run_date}")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["pending_count"], 1)
        self.assertEqual(payload["pending_decisions"][0]["allowed_comparison_outcomes"], ["candidate_wins"])
        self.assertEqual(payload["pending_decisions"][0]["candidate_incumbents"][0]["action_id"], incumbent_action_id)

    def test_phase7_post_test_decision_endpoint(self):
        run_date = "20260729"
        self._prepare_phase7_draft_fixture(run_date)

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}&refresh=true")) as response:
            self.assertEqual(response.status, 200)
            integrated_payload = json.loads(response.read().decode("utf-8"))

        pending_actions = [
            action["action_id"]
            for action in integrated_payload["integrated"]["actions"]
            if action.get("approval_status") == "pending_review"
        ]
        incumbent_action_id, challenger_action_id = pending_actions[:2]

        for action_id, reason in ((incumbent_action_id, "Incumbent active"), (challenger_action_id, "Challenger approved")):
            decision_request = Request(
                self._url("/phase7/actions/decision"),
                data=json.dumps(
                    {
                        "action_id": action_id,
                        "proposal_run_date": run_date,
                        "decision_status": "approved",
                        "decision_reason": reason,
                        "decided_by": "architect.openclaw@gmail.com",
                    }
                ).encode("utf-8"),
                headers=self._phase7_headers(),
                method="POST",
            )
            with urlopen(decision_request) as response:
                self.assertEqual(response.status, 201)

        create_launch_request = Request(
            self._url("/phase7/stat-launch-requests"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "requested_by": "architect.openclaw@gmail.com",
                    "control_n": 1200,
                    "control_converted": 108,
                    "control_opt_out": 12,
                    "variant_n": 1200,
                    "variant_converted": 180,
                    "variant_opt_out": 12,
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(create_launch_request) as response:
            self.assertEqual(response.status, 201)
            launch_request_payload = json.loads(response.read().decode("utf-8"))

        execute_request = Request(
            self._url("/phase7/stat-launch-requests/execute"),
            data=json.dumps(
                {
                    "launch_request_id": launch_request_payload["launch_request_id"],
                    "executed_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(execute_request) as response:
            self.assertEqual(response.status, 201)

        post_test_request = Request(
            self._url("/phase7/actions/post-test-decision"),
            data=json.dumps(
                {
                    "action_id": challenger_action_id,
                    "proposal_run_date": run_date,
                    "comparison_target_action_id": incumbent_action_id,
                    "comparison_outcome": "candidate_wins",
                    "decision_type": "promote_challenger",
                    "previous_incumbent_status": "replaced",
                    "decision_reason": "Promote challenger over the active incumbent",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers=self._phase7_headers(),
            method="POST",
        )
        with urlopen(post_test_request) as response:
            self.assertEqual(response.status, 201)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["decision_type"], "promote_challenger")

        with urlopen(self._url(f"/phase7/integrated-actions/latest?run_date={run_date}")) as response:
            integrated_payload = json.loads(response.read().decode("utf-8"))
        challenger = next(action for action in integrated_payload["actions"] if action["action_id"] == challenger_action_id)
        incumbent = next(action for action in integrated_payload["actions"] if action["action_id"] == incumbent_action_id)
        self.assertEqual(challenger["comparison_outcome"], "candidate_wins")
        self.assertEqual(challenger["decision_type"], "promote_challenger")
        self.assertEqual(incumbent["lifecycle_state"], "replaced")

    def test_phase6_ab_launch_endpoint_rejects_public_scenario_selector(self):
        build_payload = build_action_proposals(project_root=PROJECT_ROOT, run_date="20260725")
        with urlopen(self._url(f"/phase6/proposals/latest?run_date={build_payload['run_date']}")) as response:
            proposals_payload = json.loads(response.read().decode("utf-8"))
        proposal_id = proposals_payload["proposals"][0]["proposal_id"]

        decision_request = Request(
            self._url("/phase6/proposals/decision"),
            data=json.dumps(
                {
                    "proposal_id": proposal_id,
                    "proposal_run_date": build_payload["run_date"],
                    "decision_status": "approved",
                    "decision_reason": "Approved for simulated launch",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(decision_request) as response:
            self.assertEqual(response.status, 201)

        launch_request = Request(
            self._url("/phase6/ab-tests/launch"),
            data=json.dumps(
                {
                    "proposal_id": proposal_id,
                    "proposal_run_date": build_payload["run_date"],
                    "launched_by": "architect.openclaw@gmail.com",
                    "scenario_key": "guardrail_breach",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(launch_request)
        self.assertEqual(context.exception.code, 400)
        payload = json.loads(context.exception.read().decode("utf-8"))
        self.assertIn("scenario_key is not accepted by the public API", payload["error"])

    def test_onesignal_event_ingestion_endpoint(self):
        body = {
            "events": [
                {
                    "event": "notification.clicked",
                    "event_time": "2026-05-28T14:30:00Z",
                    "external_user_id": "cust_001",
                    "notification_id": "notif-123",
                    "run_date_tag": "20260528",
                }
            ]
        }
        request = Request(
            self._url("/events/onesignal"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 201)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["received"], 1)
        self.assertEqual(payload["inserted"], 1)
        self.assertEqual(payload["duplicates"], 0)

        with urlopen(self._url("/health/events")) as response:
            health_payload = json.loads(response.read().decode("utf-8"))
        self.assertGreaterEqual(health_payload["event_count"], 1)

    def test_onesignal_event_ingestion_is_idempotent(self):
        body = {
            "events": [
                {
                    "event": "notification.delivered",
                    "event_time": "2026-05-28T14:31:00Z",
                    "external_user_id": "cust_002",
                    "notification_id": "notif-duplicate",
                    "run_date_tag": "20260528",
                }
            ]
        }
        request = Request(
            self._url("/events/onesignal"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            first = json.loads(response.read().decode("utf-8"))
        self.assertEqual(first["inserted"], 1)

        request = Request(
            self._url("/events/onesignal"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            second = json.loads(response.read().decode("utf-8"))
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["duplicates"], 1)


if __name__ == "__main__":
    unittest.main()
