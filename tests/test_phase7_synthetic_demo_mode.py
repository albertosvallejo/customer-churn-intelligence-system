import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from api.phase7_reporting_page import build_phase7_reporting_view_model
from api.phase7_review_page import build_phase7_review_page_view_model
from evidence.phase7_artifacts import (
    DEFAULT_MODE,
    SYNTHETIC_DEMO_MODE,
    assert_phase7_mode_namespace,
    load_synthetic_manifest,
    phase7_namespace_dir,
    resolve_phase7_mode,
    resolve_synthetic_runtime_artifact,
)
from evidence.phase7_integration import build_integrated_actions


class TestPhase7SyntheticDemoMode(unittest.TestCase):
    def setUp(self):
        self._previous_mode = os.environ.pop("MODE", None)

    def tearDown(self):
        if self._previous_mode is not None:
            os.environ["MODE"] = self._previous_mode

    def _bundle_hashes(self, root: Path, run_date: str) -> dict[str, str]:
        manifest = load_synthetic_manifest(root, run_date)
        hashes = {}
        for logical_name, artifact in manifest["artifacts"].items():
            path = root / artifact["path"]
            hashes[logical_name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def _write_seed_files(self, root: Path) -> None:
        processed = root / "data" / "processed"
        synthetic = root / "data" / "synthetic_demo"
        processed.mkdir(parents=True, exist_ok=True)
        synthetic.mkdir(parents=True, exist_ok=True)

        (processed / "phase6_kpi_status_20260730.json").write_text(
            json.dumps({"status": "ok", "generated_at": "2026-07-30T08:00:00Z", "test_count": 0, "records": []}),
            encoding="utf-8",
        )
        (processed / "phase7_action_drafts_20260730.json").write_text(
            json.dumps({"drafts": [], "validation": []}),
            encoding="utf-8",
        )

        synthetic_drafts = {
            "mode": "synthetic_demo",
            "warning": "DATOS SINTÉTICOS — NO SON RESULTADOS REALES",
            "run_date": "20260730",
            "generated_at": "2026-07-30T08:00:00Z",
            "drafts": [
                {
                    "proposal_id": "p7-20260730-demo1",
                    "source_name": "NNG",
                    "article_title": "Synthetic active winner",
                    "article_url": "https://example.com/1",
                    "published_at": "2026-07-30T00:00:00Z",
                    "summary_for_business": "Synthetic approved and completed test.",
                    "pros": ["Fast"],
                    "cons": ["Synthetic"],
                    "recommended_action": "Promote",
                    "generation_contract_violation": False,
                },
                {
                    "proposal_id": "p7-20260730-demo2",
                    "source_name": "Baymard",
                    "article_title": "Synthetic pending post-test decision",
                    "article_url": "https://example.com/2",
                    "published_at": "2026-07-30T00:00:00Z",
                    "summary_for_business": "Synthetic completed test pending governance decision.",
                    "pros": ["Interesting"],
                    "cons": ["Synthetic"],
                    "recommended_action": "Review",
                    "generation_contract_violation": False,
                },
            ],
            "validation": [
                {"proposal_id": "p7-20260730-demo1", "passed": True},
                {"proposal_id": "p7-20260730-demo2", "passed": True},
            ],
        }
        (synthetic / "synthetic_demo__phase7_action_drafts_20260730.json").write_text(
            json.dumps(synthetic_drafts), encoding="utf-8"
        )
        (synthetic / "synthetic_demo__phase6_kpi_status_20260730.json").write_text(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "synthetic_demo",
                    "warning": "DATOS SINTÉTICOS — NO SON RESULTADOS REALES",
                    "generated_at": "2026-07-30T08:00:00Z",
                    "test_count": 1,
                    "records": [
                        {
                            "ab_test_run_id": "ab-demo-1",
                            "proposal_id": "p7-20260730-demo2",
                            "status": "completed",
                            "primary_kpi": "conversion_rate",
                            "verdict": "B_wins",
                            "conversion_lift": 0.01,
                            "guardrail_breach": False,
                            "p_value": 0.07,
                            "power_achieved": 0.55,
                            "launch_ts": "2026-07-30T08:30:00Z",
                            "control_conversion_rate": 0.10,
                            "variant_conversion_rate": 0.11,
                            "control_opt_out_rate": 0.01,
                            "variant_opt_out_rate": 0.01,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        (synthetic / "synthetic_demo__phase7_source_snapshot_20260730.json").write_text(
            json.dumps({"run_date": "20260730", "records": []}), encoding="utf-8"
        )
        build_integrated_actions(project_root=root, run_date="20260730", mode=SYNTHETIC_DEMO_MODE)
        integrated_path = synthetic / "synthetic_demo__phase7_integrated_actions_20260730.json"
        integrated = json.loads(integrated_path.read_text(encoding="utf-8"))
        a1, a2 = integrated["actions"]
        a1["approval_status"] = "pending_review"
        a1["lifecycle_state"] = "draft_ready_for_review"
        a1["launch_status"] = "not_started"
        a1["stat_test_status"] = "ready"
        a1["latest_stat_run_id"] = None
        a1["latest_verdict"] = None
        a2["approval_status"] = "approved"
        a2["lifecycle_state"] = "stat_test_completed"
        a2["launch_status"] = "completed"
        a2["stat_test_status"] = "completed"
        a2["latest_stat_run_id"] = "ab-demo-1"
        a2["latest_verdict"] = "B_wins"
        a2["primary_kpi"] = "checkout_completion_rate"
        a2["recommended_kpi"] = "checkout_completion_rate"
        a2["guardrail_kpi"] = "opt_out_rate"
        a2["latest_conversion_lift"] = 0.01
        a2["launch_ts"] = "2026-07-30T08:30:00Z"
        a2["latest_stat_completed_at"] = "2026-07-30T08:30:00Z"
        a2["recommended_action"] = "Review"
        a2["synthetic_previous_action"] = {
            "action_id": a1["action_id"],
            "article_title": a1["article_title"],
            "status_label": "Current action",
            "summary": a1["summary_for_business"],
            "latest_stat_run_id": "ab-demo-incumbent",
        }
        integrated_path.write_text(json.dumps(integrated, indent=2) + "\n", encoding="utf-8")
        pd.DataFrame(
            [
                {
                    "event_id": "evt-1",
                    "event_type": "governance_decision",
                    "action_id": a1["action_id"],
                    "proposal_id": a1["proposal_id"],
                    "proposal_run_date": "20260730",
                    "decision_status": "approved",
                    "decision_reason": "seed",
                },
                {
                    "event_id": "evt-2",
                    "event_type": "stat_test_completed",
                    "action_id": a2["action_id"],
                    "proposal_id": a2["proposal_id"],
                    "proposal_run_date": "20260730",
                    "verdict": "B_wins",
                },
            ]
        ).to_parquet(synthetic / "synthetic_demo__phase7_action_history_log.parquet", index=False)
        pd.DataFrame([
            {
                "stat_test_run_id": "ab-demo-1",
                "action_id": a2["action_id"],
                "proposal_id": a2["proposal_id"],
                "proposal_run_date": "20260730",
                "launched_by": "synthetic_demo_seed",
                "launch_ts": "2026-07-30T08:30:00Z",
                "baseline_p0": 0.096,
                "guardrail_q_threshold": 0.02,
                "control_n": 1000,
                "control_converted": 100,
                "control_opt_out": 10,
                "variant_n": 1000,
                "variant_converted": 110,
                "variant_opt_out": 10,
                "test_used": "synthetic_seed",
                "guardrail_breach": False,
                "p_value": 0.01,
                "power_achieved": 0.8,
                "verdict": "B_wins",
                "conversion_lift": 0.01,
            }
        ]).to_parquet(synthetic / "synthetic_demo__phase7_stat_test_runs.parquet", index=False)
        pd.DataFrame([], columns=[
            "launch_request_id", "action_id", "proposal_id", "proposal_run_date", "requested_by", "request_ts",
            "request_status", "executed_ts", "executed_by", "stat_test_run_id", "baseline_p0", "guardrail_q_threshold",
            "control_n", "control_converted", "control_opt_out", "variant_n", "variant_converted", "variant_opt_out"
        ]).to_parquet(synthetic / "synthetic_demo__phase7_stat_launch_requests.parquet", index=False)
        phase7_kpi_status = {
            "status": "ok",
            "generated_at": "2026-07-30T08:30:00Z",
            "run_date": "20260730",
            "action_count": 2,
            "evaluated_action_count": 1,
            "stat_run_count": 1,
            "records": [{"action_id": a2["action_id"], "proposal_id": a2["proposal_id"], "verdict": "B_wins", "test_used": "synthetic_seed", "guardrail_breach": False, "p_value": 0.01, "power_achieved": 0.8}],
            "mode": SYNTHETIC_DEMO_MODE,
            "warning": "DATOS SINTÉTICOS — NO SON RESULTADOS REALES",
        }
        (synthetic / "synthetic_demo__phase7_kpi_status_20260730.json").write_text(json.dumps(phase7_kpi_status), encoding="utf-8")
        (synthetic / "synthetic_demo__phase7_n8n_payload_20260730.json").write_text(json.dumps({"status": "ok", "run_date": "20260730", "actions": []}), encoding="utf-8")
        manifest = {
            "manifest_version": "phase7_synthetic_demo_v1",
            "bundle_version": "test-seed",
            "mode": SYNTHETIC_DEMO_MODE,
            "run_date": "20260730",
            "logical_date": "2026-07-30",
            "seed_version": "test-seed",
            "generator_script": "tests/test_phase7_synthetic_demo_mode.py",
            "validation_script": "tests/test_phase7_synthetic_demo_mode.py",
            "schema": {},
            "artifacts": {
                "phase7_source_snapshot": {"name": "synthetic_demo__phase7_source_snapshot_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase7_source_snapshot_20260730.json", "sha256": "", "size_bytes": 0},
                "phase7_action_drafts": {"name": "synthetic_demo__phase7_action_drafts_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase7_action_drafts_20260730.json", "sha256": "", "size_bytes": 0},
                "phase6_kpi_status": {"name": "synthetic_demo__phase6_kpi_status_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase6_kpi_status_20260730.json", "sha256": "", "size_bytes": 0},
                "phase7_integrated_actions": {"name": "synthetic_demo__phase7_integrated_actions_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase7_integrated_actions_20260730.json", "sha256": "", "size_bytes": 0},
                "phase7_kpi_status": {"name": "synthetic_demo__phase7_kpi_status_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase7_kpi_status_20260730.json", "sha256": "", "size_bytes": 0},
                "phase7_n8n_payload": {"name": "synthetic_demo__phase7_n8n_payload_20260730.json", "path": "data/synthetic_demo/synthetic_demo__phase7_n8n_payload_20260730.json", "sha256": "", "size_bytes": 0},
                "phase7_stat_test_runs": {"name": "synthetic_demo__phase7_stat_test_runs.parquet", "path": "data/synthetic_demo/synthetic_demo__phase7_stat_test_runs.parquet", "sha256": "", "size_bytes": 0},
                "phase7_action_history_log": {"name": "synthetic_demo__phase7_action_history_log.parquet", "path": "data/synthetic_demo/synthetic_demo__phase7_action_history_log.parquet", "sha256": "", "size_bytes": 0},
                "phase7_stat_launch_requests": {"name": "synthetic_demo__phase7_stat_launch_requests.parquet", "path": "data/synthetic_demo/synthetic_demo__phase7_stat_launch_requests.parquet", "sha256": "", "size_bytes": 0},
            },
        }
        (synthetic / "synthetic_demo__phase7_manifest_20260730.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_default_mode_is_real_not_synthetic(self):
        self.assertEqual(DEFAULT_MODE, "real")
        self.assertEqual(resolve_phase7_mode(None), "real")
        previous = os.environ.get("MODE")
        try:
            os.environ.pop("MODE", None)
            self.assertEqual(resolve_phase7_mode(None), "real")
        finally:
            if previous is not None:
                os.environ["MODE"] = previous

    def test_real_mode_and_synthetic_mode_resolve_different_namespaces(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_seed_files(root)
            self.assertEqual(phase7_namespace_dir(root, None), root / "data" / "processed")
            self.assertEqual(phase7_namespace_dir(root, SYNTHETIC_DEMO_MODE), root / "data" / "synthetic_demo")
            real_files = list((root / "data" / "processed").glob("synthetic_demo__*"))
            self.assertEqual(real_files, [])

    def test_namespace_guard_rejects_cross_mode_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_seed_files(root)
            self.assertEqual(
                assert_phase7_mode_namespace(root / "data" / "synthetic_demo" / "synthetic_demo__phase7_action_drafts_20260730.json", SYNTHETIC_DEMO_MODE),
                (root / "data" / "synthetic_demo" / "synthetic_demo__phase7_action_drafts_20260730.json").resolve(),
            )
            with self.assertRaises(ValueError):
                assert_phase7_mode_namespace(root / "data" / "synthetic_demo" / "synthetic_demo__phase7_action_drafts_20260730.json", None)
            with self.assertRaises(ValueError):
                assert_phase7_mode_namespace(root / "data" / "processed" / "phase6_kpi_status_20260730.json", SYNTHETIC_DEMO_MODE)

    def test_reporting_page_view_model_preserves_synthetic_demo_banner_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_seed_files(root)
            view_model = build_phase7_reporting_view_model(root, run_date="20260730", mode=SYNTHETIC_DEMO_MODE)
            self.assertEqual(view_model["mode"], SYNTHETIC_DEMO_MODE)
            self.assertEqual(view_model["warning"], "SYNTHETIC DATA — NOT REAL RESULTS")

    def test_review_page_view_model_preserves_synthetic_demo_banner_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._write_seed_files(root)
            view_model = build_phase7_review_page_view_model(root, run_date="20260730", mode=SYNTHETIC_DEMO_MODE)
            self.assertEqual(view_model["mode"], SYNTHETIC_DEMO_MODE)
            self.assertEqual(view_model["warning"], "SYNTHETIC DATA — NOT REAL RESULTS")
            self.assertEqual(view_model["pre_test_pending_count"], 1)
            self.assertEqual(view_model["post_test_pending_count"], 1)

    def test_build_script_regenerates_manifest_and_is_deterministic_across_clean_copies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            copy_a = workspace / "copy_a"
            copy_b = workspace / "copy_b"
            shutil.copytree(PROJECT_ROOT, copy_a)
            shutil.copytree(PROJECT_ROOT, copy_b)

            target_rel_paths = [
                Path("data/synthetic_demo/synthetic_demo__phase7_integrated_actions_20260727.json"),
                Path("data/synthetic_demo/synthetic_demo__phase7_stat_test_runs.parquet"),
                Path("data/synthetic_demo/synthetic_demo__phase7_action_history_log.parquet"),
                Path("data/synthetic_demo/synthetic_demo__phase7_manifest_20260727.json"),
                Path("reports/reproducibility/PHASE7_SYNTHETIC_DEMO_MANIFEST_20260727.json"),
            ]

            hashes = []
            for root in [copy_a, copy_b]:
                for rel_path in target_rel_paths:
                    path = root / rel_path
                    if path.exists():
                        path.unlink()
                subprocess.run(
                    [sys.executable, "scripts/build_phase7_synthetic_demo_bundle.py"],
                    cwd=root,
                    check=True,
                    env={**os.environ, "PYTHONPATH": "src"},
                    capture_output=True,
                    text=True,
                )
                manifest_path = root / "data/synthetic_demo/synthetic_demo__phase7_manifest_20260727.json"
                self.assertTrue(manifest_path.exists())
                report_manifest_path = root / "reports/reproducibility/PHASE7_SYNTHETIC_DEMO_MANIFEST_20260727.json"
                self.assertTrue(report_manifest_path.exists())
                hashes.append((root / "data/synthetic_demo/synthetic_demo__phase7_integrated_actions_20260727.json").read_bytes())

            self.assertEqual(hashes[0], hashes[1])

    def test_mpb_01_manifest_references_only_synthetic_artifacts(self):
        manifest = load_synthetic_manifest(PROJECT_ROOT, "20260727")
        self.assertEqual(manifest["mode"], SYNTHETIC_DEMO_MODE)
        required = {
            "phase7_source_snapshot",
            "phase7_action_drafts",
            "phase6_kpi_status",
            "phase7_integrated_actions",
            "phase7_kpi_status",
            "phase7_n8n_payload",
            "phase7_stat_test_runs",
            "phase7_action_history_log",
            "phase7_stat_launch_requests",
        }
        self.assertEqual(set(manifest["artifacts"].keys()), required)
        for logical_name in required:
            artifact = manifest["artifacts"][logical_name]
            self.assertTrue(str(artifact["path"]).startswith("data/synthetic_demo/"))
            self.assertTrue(resolve_synthetic_runtime_artifact(PROJECT_ROOT, logical_name, "20260727").exists())

    def test_mpb_02_builder_is_idempotent_and_runtime_does_not_need_processed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "copy"
            shutil.copytree(PROJECT_ROOT, root)
            env = {**os.environ, "PYTHONPATH": "src", "MODE": SYNTHETIC_DEMO_MODE}
            subprocess.run([sys.executable, "scripts/build_phase7_synthetic_demo_bundle.py"], cwd=root, env=env, check=True, capture_output=True, text=True)
            first_hashes = self._bundle_hashes(root, "20260727")
            shutil.rmtree(root / "data" / "processed")
            reporting = build_phase7_reporting_view_model(root, run_date="20260727", mode=SYNTHETIC_DEMO_MODE)
            review = build_phase7_review_page_view_model(root, run_date="20260727", mode=SYNTHETIC_DEMO_MODE)
            self.assertEqual(reporting["summary"]["test_count"], 3)
            self.assertEqual(reporting["summary"]["completed_test_count"], 2)
            self.assertEqual(reporting["summary"]["winner_test_count"], 2)
            self.assertEqual(reporting["summary"]["guardrail_breach_count"], 0)
            self.assertEqual(review["post_test_pending_count"], 2)
            self.assertEqual(review["pre_test_pending_count"], 3)
            subprocess.run([sys.executable, "scripts/build_phase7_synthetic_demo_bundle.py"], cwd=root, env=env, check=True, capture_output=True, text=True)
            second_hashes = self._bundle_hashes(root, "20260727")
            self.assertEqual(first_hashes, second_hashes)

    def test_mpb_03_runtime_loaders_do_not_touch_processed_namespace(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "copy"
            shutil.copytree(PROJECT_ROOT, root)
            env = {**os.environ, "PYTHONPATH": "src", "MODE": SYNTHETIC_DEMO_MODE}
            subprocess.run([sys.executable, "scripts/build_phase7_synthetic_demo_bundle.py"], cwd=root, env=env, check=True, capture_output=True, text=True)

            original_read_text = Path.read_text
            original_read_parquet = pd.read_parquet

            def guarded_read_text(path_self: Path, *args, **kwargs):
                if "data/processed" in str(path_self):
                    raise AssertionError(f"runtime attempted to read processed namespace: {path_self}")
                return original_read_text(path_self, *args, **kwargs)

            def guarded_read_parquet(path, *args, **kwargs):
                if "data/processed" in str(path):
                    raise AssertionError(f"runtime attempted to read processed namespace: {path}")
                return original_read_parquet(path, *args, **kwargs)

            with mock.patch.object(Path, "read_text", guarded_read_text), mock.patch.object(pd, "read_parquet", guarded_read_parquet):
                reporting = build_phase7_reporting_view_model(root, run_date="20260727", mode=SYNTHETIC_DEMO_MODE)
                review = build_phase7_review_page_view_model(root, run_date="20260727", mode=SYNTHETIC_DEMO_MODE)

            self.assertEqual(reporting["summary"], {
                "test_count": 3,
                "completed_test_count": 2,
                "winner_test_count": 2,
                "guardrail_breach_count": 0,
                "visible_history_count": 9,
            })
            self.assertEqual(len(review["pending_post_test_decisions"]), 2)
            self.assertEqual(len(review["pending_pre_test_actions"]), 3)
            for row in review["pending_post_test_decisions"]:
                self.assertTrue(row["recommended_action"].strip())
                self.assertTrue(row["business_context"].strip())
                self.assertTrue(row["previous_action"].get("action_id"))


if __name__ == "__main__":
    unittest.main()
