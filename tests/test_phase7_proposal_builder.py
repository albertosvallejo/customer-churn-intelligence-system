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

from evidence.phase7_proposal_builder import (
    build_and_write_action_drafts,
    extract_numeric_claims,
    resolve_openai_runtime_config,
    synthesize_article_with_openai,
    validate_numeric_coherence,
)


class TestPhase7ProposalBuilder(unittest.TestCase):
    def test_extract_numeric_claims_finds_percentages_and_counts(self):
        claims = extract_numeric_claims("Open rate reached 42% across 3 experiments.")
        self.assertEqual(claims, ["42%", "3"])

    def test_resolve_openai_runtime_config_reads_project_env(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".env").write_text(
                "OPENAI_API_KEY=test-key\nPHASE7_OPENAI_MODEL=test-model\nPHASE7_OPENAI_TEMPERATURE=0.2\n",
                encoding="utf-8",
            )
            runtime = resolve_openai_runtime_config(project_root=root)
            self.assertEqual(runtime["api_key"], "test-key")
            self.assertEqual(runtime["model"], "test-model")
            self.assertEqual(runtime["temperature"], 0.2)
            self.assertEqual(runtime["api_key_source"], str(root / ".env"))

    def test_resolve_openai_runtime_config_enables_fake_llm_only_in_test_or_ci(self):
        from unittest.mock import patch
        with patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                (root / ".env").write_text(
                    "APP_ENV=test\nCI_FAKE_LLM=1\n",
                    encoding="utf-8",
                )
                runtime = resolve_openai_runtime_config(project_root=root)
                self.assertTrue(runtime["fake_llm_enabled"])
                self.assertEqual(runtime["llm_provider"], "fake")
                self.assertEqual(runtime["app_env"], "test")

            with tempfile.TemporaryDirectory() as tmpdir:
                root = Path(tmpdir)
                (root / ".env").write_text(
                    "APP_ENV=local\nCI_FAKE_LLM=1\n",
                    encoding="utf-8",
                )
                runtime = resolve_openai_runtime_config(project_root=root)
                self.assertFalse(runtime["fake_llm_enabled"])
                self.assertEqual(runtime["llm_provider"], "openai")

    def test_validate_numeric_coherence_normalizes_separator_spacing_only(self):
        drafts = [
            {
                "proposal_id": "P7-DRAFT-005",
                "source_name": "Nielsen Norman Group",
                "citation_anchor": "October 5- October 16, 2026.",
                "numeric_claims_used": ["October 5 - October 16, 2026"],
            },
            {
                "proposal_id": "P7-DRAFT-006",
                "source_name": "Nielsen Norman Group",
                "citation_anchor": "October 5- October 16, 2026.",
                "numeric_claims_used": ["October 6 - October 16, 2026"],
            },
        ]
        rows = validate_numeric_coherence(drafts)
        self.assertTrue(rows[0]["passed"])
        self.assertFalse(rows[0]["invalid_format"])
        self.assertEqual(rows[0]["missing_from_citation_anchor"], [])
        self.assertFalse(rows[1]["passed"])
        self.assertFalse(rows[1]["invalid_format"])
        self.assertEqual(rows[1]["missing_from_citation_anchor"], ["October 6 - October 16, 2026"])

    def test_validate_numeric_coherence_fails_closed_on_invalid_numeric_claims_used_format(self):
        drafts = [
            {
                "proposal_id": "P7-DRAFT-011",
                "source_name": "Nielsen Norman Group",
                "citation_anchor": "Gather baseline metrics before starting a project so your team can demonstrate its impact.",
                "numeric_claims_used": {"none": "No specific numbers or percentages are provided in the source text."},
            }
        ]
        rows = validate_numeric_coherence(drafts)
        self.assertFalse(rows[0]["passed"])
        self.assertTrue(rows[0]["invalid_format"])
        self.assertEqual(rows[0]["missing_from_citation_anchor"], [])

    def test_synthesize_article_with_openai_retries_once_on_invalid_numeric_claims_used_format(self):
        article = {
            "source_name": "Nielsen Norman Group",
            "title": "Baseline metrics without numbers",
            "summary": "Gather baseline metrics before starting a project.",
            "link": "https://example.com/x",
            "published_at": "2026-07-27T00:00:00+00:00",
        }

        responses = iter([
            {
                "choices": [{"message": {"content": json.dumps({
                    "summary_for_business": "First attempt.",
                    "pros": ["Useful habit."],
                    "cons": ["No quantitative evidence in source."],
                    "recommended_action": "Retry needed.",
                    "numeric_claims_used": {"none": "No specific numbers or percentages are provided in the source text."}
                })}}],
                "id": "chatcmpl-invalid",
                "model": "gpt-4.1-nano-2025-04-14",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            {
                "choices": [{"message": {"content": json.dumps({
                    "summary_for_business": "Second attempt.",
                    "pros": ["Useful habit."],
                    "cons": ["No quantitative evidence in source."],
                    "recommended_action": "Accept.",
                    "numeric_claims_used": []
                })}}],
                "id": "chatcmpl-valid",
                "model": "gpt-4.1-nano-2025-04-14",
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        ])

        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload
            def read(self):
                return json.dumps(self.payload).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False

        from unittest.mock import patch
        with patch("evidence.phase7_proposal_builder.resolve_openai_runtime_config", return_value={
            "api_key": "test-key",
            "api_key_source": "/tmp/.env",
            "model": "gpt-4.1-nano-2025-04-14",
            "temperature": 0.0,
        }), patch("evidence.phase7_proposal_builder.urllib.request.urlopen", side_effect=lambda *args, **kwargs: FakeResponse(next(responses))):
            result = synthesize_article_with_openai(article, project_root=PROJECT_ROOT)

        self.assertEqual(result["numeric_claims_used"], [])
        self.assertFalse(result["generation_contract_violation"])
        self.assertEqual(result["llm_request"]["attempt"], 2)
        self.assertEqual(result["llm_response"]["id"], "chatcmpl-valid")

    def test_synthesize_article_with_openai_returns_fake_payload_in_ci_mode(self):
        article = {
            "source_name": "Nielsen Norman Group",
            "title": "Email benchmark improved 15%",
            "summary": "A retained-customer test reported 15% uplift across 2 cohorts.",
            "link": "https://example.com/x",
            "published_at": "2026-07-27T00:00:00+00:00",
        }

        from unittest.mock import patch
        with patch.dict(
            os.environ,
            {
                "APP_ENV": "test",
                "CI_FAKE_LLM": "1",
                "PHASE7_LLM_PROVIDER": "fake",
            },
            clear=True,
        ):
            result = synthesize_article_with_openai(article, project_root=PROJECT_ROOT)

        self.assertEqual(result["llm_request"]["provider"], "fake")
        self.assertEqual(result["llm_response"]["id"], "ci-fake-llm-response")
        self.assertEqual(result["numeric_claims_used"], ["15%", "2"])
        self.assertFalse(result["generation_contract_violation"])

    def test_build_and_write_action_drafts_creates_llm_backed_drafts_and_validation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "data" / "processed").mkdir(parents=True)
            snapshot = {
                "run_at": "2026-07-27T00:00:00+00:00",
                "in_scope_articles": [
                    {
                        "source_name": "Nielsen Norman Group",
                        "title": "Email benchmark improved 15%",
                        "link": "https://example.com/a",
                        "published_at": "2026-07-27T00:00:00+00:00",
                        "summary": "A retained-customer test reported 15% uplift across 2 cohorts.",
                    },
                    {
                        "source_name": "Baymard Institute public content",
                        "title": "Checkout friction lessons",
                        "link": "https://example.com/b",
                        "published_at": "2026-07-27T01:00:00+00:00",
                        "summary": "Qualitative guidance without quantified lift.",
                    },
                ],
            }
            (root / "data" / "processed" / "phase7_source_snapshot_20260727.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )

            def fake_synthesizer(article, _project_root):
                if article["source_name"] == "Nielsen Norman Group":
                    return {
                        "summary_for_business": "Use the uplift example carefully.",
                        "pros": ["Contains a quantified uplift."],
                        "cons": ["Only 2 cohorts are mentioned."],
                        "recommended_action": "Queue for human review before backlog insertion.",
                        "numeric_claims_used": ["15%", "2"],
                        "llm_request": {
                            "provider": "openai",
                            "model": "gpt-4.1-nano-2025-04-14",
                            "temperature": 0.0,
                            "api_key_source": "/tmp/.env",
                        },
                        "llm_response": {
                            "id": "chatcmpl-test-1",
                            "model": "gpt-4.1-nano-2025-04-14",
                            "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
                        },
                    }
                return {
                    "summary_for_business": "Qualitative signal only.",
                    "pros": ["Useful heuristic."],
                    "cons": ["No quantified lift in source text."],
                    "recommended_action": "Store as low-confidence qualitative evidence.",
                    "numeric_claims_used": [],
                    "llm_request": {
                        "provider": "openai",
                        "model": "gpt-4.1-nano-2025-04-14",
                        "temperature": 0.0,
                        "api_key_source": "/tmp/.env",
                    },
                    "llm_response": {
                        "id": "chatcmpl-test-2",
                        "model": "gpt-4.1-nano-2025-04-14",
                        "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
                    },
                }

            payload = build_and_write_action_drafts(project_root=root, run_date="20260727", synthesizer=fake_synthesizer)
            self.assertEqual(payload["draft_count"], "2")
            self.assertEqual(payload["validated_count"], "2")

            drafts_payload = json.loads(Path(payload["drafts_path"]).read_text(encoding="utf-8"))
            self.assertEqual(drafts_payload["drafts"][0]["pros"], ["Contains a quantified uplift."])
            self.assertEqual(drafts_payload["drafts"][0]["cons"], ["Only 2 cohorts are mentioned."])
            self.assertEqual(drafts_payload["drafts"][0]["numeric_claims_used"], ["15%", "2"])
            self.assertFalse(drafts_payload["drafts"][0]["generation_contract_violation"])
            self.assertTrue(all(row["passed"] for row in drafts_payload["validation"]))
            self.assertEqual(drafts_payload["validation"][0]["validation_target"], "citation_anchor")
            self.assertEqual(drafts_payload["validation"][0]["numeric_claims_used"], ["15%", "2"])
            self.assertFalse(drafts_payload["validation"][0]["invalid_format"])
            self.assertEqual(drafts_payload["validation"][0]["missing_from_citation_anchor"], [])
            report_text = Path(payload["report_path"]).read_text(encoding="utf-8")
            self.assertIn("Pros:", report_text)
            self.assertIn("provider=openai", report_text)
            self.assertIn("temperature=0.0", report_text)
            self.assertIn("target=citation_anchor", report_text)


if __name__ == "__main__":
    unittest.main()
