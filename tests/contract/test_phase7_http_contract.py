import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_tmpdir = tempfile.TemporaryDirectory()
os.environ["CHURN_DB_URL"] = f"sqlite:///{Path(_tmpdir.name) / 'test_ops.sqlite'}"
os.environ["PHASE7_REVIEW_TOKEN"] = "phase7-contract-token"

from api import churn_service
from api.fastapi_app import app
from evidence.phase7_artifacts import REAL_MODE
from evidence.phase7_integration import (
    build_integrated_actions,
    load_integrated_actions,
)


class TestPhase7HttpContract(unittest.TestCase):
    RUN_DATE = "20990101"

    @classmethod
    def setUpClass(cls):
        cls._previous_mode = os.environ.pop("MODE", None)
        cls._previous_app_env = os.environ.get("APP_ENV")
        os.environ["APP_ENV"] = "test"
        churn_service.DEFAULT_DB_URL = os.environ["CHURN_DB_URL"]
        churn_service._ops_engine().dispose()
        churn_service._ops_engine.cache_clear()

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
        cls._prepare_phase7_fixture(cls.RUN_DATE)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.socket.close()
        cls._cleanup_phase7_fixture(cls.RUN_DATE)
        if cls._previous_mode is not None:
            os.environ["MODE"] = cls._previous_mode
        if cls._previous_app_env is None:
            os.environ.pop("APP_ENV", None)
        else:
            os.environ["APP_ENV"] = cls._previous_app_env
        cached_engine = churn_service._ops_engine()
        cached_engine.dispose()
        churn_service._ops_engine.cache_clear()
        _tmpdir.cleanup()

    @classmethod
    def _url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls.port}{path}"

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

    def test_health_contract_exposes_core_fields(self):
        with urlopen(self._url("/health")) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["status"], "ok")
        for field in ["service", "timestamp", "run_id", "run_date_tag", "model_version", "pipeline_tag", "source_file", "risk_thresholds"]:
            self.assertIn(field, payload)

    def test_public_dashboard_contract_is_readable_without_token(self):
        with urlopen(self._url(f"/customer-churn/dashboard?run_date={self.RUN_DATE}")) as response:
            self.assertEqual(response.status, 200)
            html = response.read().decode("utf-8")

        self.assertIn("CHURN CAMPAIGNS DASHBOARD", html)
        self.assertIn("/customer-churn/new-actions-testing", html)
        self.assertIn("/customer-churn/tested-actions-approval", html)

    def test_get_review_pages_without_token_return_200(self):
        for path in [
            f"/customer-churn/tested-actions-approval?run_date={self.RUN_DATE}",
            f"/customer-churn/new-actions-testing?run_date={self.RUN_DATE}",
        ]:
            with urlopen(self._url(path)) as response:
                self.assertEqual(response.status, 200)

    def test_get_review_data_without_token_return_200(self):
        for path in [
            f"/customer-churn/tested-actions-approval/data?run_date={self.RUN_DATE}",
            f"/customer-churn/new-actions-testing/data?run_date={self.RUN_DATE}",
        ]:
            with urlopen(self._url(path)) as response:
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("history_rows", payload)
            self.assertEqual(payload["run_date"], self.RUN_DATE)

    def test_post_phase7_decision_without_token_returns_401(self):
        request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": self.RUN_DATE,
                    "decision_status": "approved",
                    "decision_reason": "Missing token contract check",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request)
        self.assertEqual(context.exception.code, 401)

    def test_post_phase7_decision_wrong_token_401_and_valid_token_2xx(self):
        before = load_integrated_actions(project_root=PROJECT_ROOT, run_date=self.RUN_DATE)
        before_action_count = len(before["actions"])

        invalid_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": self.RUN_DATE,
                    "decision_status": "approved",
                    "decision_reason": "Contract auth rejection check",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": "wrong-token"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(invalid_request)
        self.assertEqual(context.exception.code, 401)

        after_invalid = load_integrated_actions(project_root=PROJECT_ROOT, run_date=self.RUN_DATE)
        self.assertEqual(before_action_count, len(after_invalid["actions"]))

        valid_request = Request(
            self._url("/phase7/actions/decision"),
            data=json.dumps(
                {
                    "action_id": "P7-ACT-002",
                    "proposal_run_date": self.RUN_DATE,
                    "decision_status": "approved",
                    "decision_reason": "Valid token contract acceptance check",
                    "decided_by": "architect.openclaw@gmail.com",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": os.environ["PHASE7_REVIEW_TOKEN"]},
            method="POST",
        )
        with urlopen(valid_request) as response:
            self.assertIn(response.status, (200, 201, 202, 204))

    def test_deprecated_stat_launch_route_remains_410(self):
        request = Request(
            self._url("/phase7/stat-tests/launch"),
            data=json.dumps({"action_id": "P7-ACT-003", "proposal_run_date": self.RUN_DATE}).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-Phase7-Token": os.environ["PHASE7_REVIEW_TOKEN"]},
            method="POST",
        )
        with self.assertRaises(HTTPError) as context:
            urlopen(request)
        self.assertEqual(context.exception.code, 410)
        payload = json.loads(context.exception.read().decode("utf-8"))
        self.assertTrue(payload["deprecated"])


if __name__ == "__main__":
    unittest.main()
