import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.catalog_builder import build_and_write_catalog, build_catalog_entries, render_catalog_summary


class TestPhase6CatalogBuilder(unittest.TestCase):
    def test_build_and_write_catalog_creates_versioned_seed_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            (root / "data" / "interim").mkdir(parents=True)

            allowlist = {
                "phase": "phase6",
                "cadence": "monthly",
                "open_access_only": True,
                "source_levels": {
                    "A": {"confidence_ceiling": "high"},
                    "D": {"confidence_ceiling": "low"},
                },
                "approval": {
                    "mode": "dashboard",
                    "single_approver": "architect.openclaw@gmail.com",
                    "ab_mode": "simulated",
                },
                "source_scraping_registry": {
                    "path": "data/interim/phase7_source_scraping_registry.json",
                    "key_fields": ["domain", "path_pattern"],
                    "required_record_fields": [
                        "domain",
                        "path_pattern",
                        "checked_at",
                        "scraping_permitido",
                        "method",
                        "note",
                    ],
                    "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
                },
                "seed_sources": [
                    {
                        "source_name": "ResearchGate",
                        "source_level": "A",
                        "peer_review_status": "preprint",
                        "open_access_verified": True,
                        "used_in": ["INT-02"],
                        "seed_role": "baseline_reference",
                        "source_domains": ["researchgate.net"],
                        "automation_scope": {
                            "pipeline_status": "out_of_scope",
                            "allowed_channel": "manual_only",
                            "scope_note": "manual only",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "no",
                            "registry_key": "researchgate.net::/publication/",
                            "status_note": "blocked by tos",
                        },
                    }
                ],
            }
            seed_entries = [
                {
                    "entry_id": "seed-1",
                    "ref_id": "[4]",
                    "intervention_id": "INT-02",
                    "source_name": "ResearchGate",
                    "source_level": "A",
                    "peer_review_status": "preprint",
                    "study_design": "quasi_experimental",
                    "sample_size": None,
                    "publication_year": 2022,
                    "effect_size": None,
                    "effect_size_text": "anchor",
                    "expected_lift": None,
                    "actionable_elements": {
                        "copy": "reminder_sequence",
                        "channel": "email",
                        "timing": "follow_up_sequence",
                        "incentive": "repeat_offer",
                    },
                    "applicability_to_vivamarket": "medium",
                    "citation_status": "pending",
                    "quote_or_anchor": "anchor",
                },
                {
                    "entry_id": "seed-2",
                    "ref_id": "[1]",
                    "intervention_id": "INT-01",
                    "source_name": "CXL",
                    "source_level": "D",
                    "peer_review_status": "none",
                    "study_design": "industry_heuristic",
                    "sample_size": None,
                    "publication_year": 2024,
                    "effect_size": None,
                    "effect_size_text": "anchor",
                    "expected_lift": None,
                    "actionable_elements": {
                        "copy": "value_first",
                        "channel": "email",
                        "timing": None,
                        "incentive": None,
                    },
                    "applicability_to_vivamarket": "high",
                    "citation_status": "pending",
                    "quote_or_anchor": "anchor",
                },
            ]

            (root / "config" / "evidence_sources_allowlist.yaml").write_text(json.dumps(allowlist), encoding="utf-8")
            (root / "data" / "interim" / "phase6_seed_evidence.json").write_text(json.dumps(seed_entries), encoding="utf-8")

            payload = build_and_write_catalog(project_root=root, run_date="20260721")

            catalog_path = Path(payload["catalog_path"])
            summary_path = Path(payload["summary_path"])
            self.assertTrue(catalog_path.exists())
            self.assertTrue(summary_path.exists())

            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            self.assertEqual(len(catalog), 2)
            self.assertEqual(catalog[0]["catalog_run_date"], "20260721")
            self.assertEqual(catalog[0]["approval_mode"], "dashboard")
            self.assertEqual(catalog[0]["ab_mode"], "simulated")
            self.assertEqual(catalog[0]["confidence_score"], "medium")
            self.assertEqual(catalog[0]["actionability_score"], "high")
            self.assertEqual(catalog[1]["confidence_score"], "low")
            self.assertEqual(catalog[1]["actionability_score"], "medium")

            summary = summary_path.read_text(encoding="utf-8")
            self.assertIn("seed baseline", summary.lower())
            self.assertIn("INT-01", summary)
            self.assertIn("INT-02", summary)

    def test_build_and_write_catalog_rejects_overwrite_for_same_run_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            (root / "data" / "interim").mkdir(parents=True)

            allowlist = {
                "phase": "phase6",
                "cadence": "monthly",
                "open_access_only": True,
                "source_levels": {"A": {"confidence_ceiling": "high"}},
                "approval": {
                    "mode": "dashboard",
                    "single_approver": "architect.openclaw@gmail.com",
                    "ab_mode": "simulated",
                },
                "source_scraping_registry": {
                    "path": "data/interim/phase7_source_scraping_registry.json",
                    "key_fields": ["domain", "path_pattern"],
                    "required_record_fields": [
                        "domain",
                        "path_pattern",
                        "checked_at",
                        "scraping_permitido",
                        "method",
                        "note",
                    ],
                    "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
                },
                "seed_sources": [
                    {
                        "source_name": "ResearchGate",
                        "source_level": "A",
                        "peer_review_status": "published",
                        "open_access_verified": True,
                        "used_in": ["INT-02"],
                        "seed_role": "baseline_reference",
                        "source_domains": ["researchgate.net"],
                        "automation_scope": {
                            "pipeline_status": "out_of_scope",
                            "allowed_channel": "manual_only",
                            "scope_note": "manual only",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "no",
                            "registry_key": "researchgate.net::/publication/",
                            "status_note": "blocked by tos",
                        },
                    }
                ],
            }
            seed_entries = [
                {
                    "entry_id": "seed-1",
                    "ref_id": "[4]",
                    "intervention_id": "INT-02",
                    "source_name": "ResearchGate",
                    "source_level": "A",
                    "peer_review_status": "published",
                    "study_design": "rct",
                    "sample_size": 100,
                    "publication_year": 2022,
                    "effect_size": None,
                    "effect_size_text": "anchor",
                    "expected_lift": None,
                    "actionable_elements": {"copy": "x", "channel": "email", "timing": "t", "incentive": "i"},
                    "applicability_to_vivamarket": "high",
                    "citation_status": "pending",
                    "quote_or_anchor": "anchor",
                }
            ]

            (root / "config" / "evidence_sources_allowlist.yaml").write_text(json.dumps(allowlist), encoding="utf-8")
            (root / "data" / "interim" / "phase6_seed_evidence.json").write_text(json.dumps(seed_entries), encoding="utf-8")

            build_and_write_catalog(project_root=root, run_date="20260721")
            with self.assertRaises(FileExistsError):
                build_and_write_catalog(project_root=root, run_date="20260721")

    def test_build_catalog_entries_accepts_published_peer_review_as_base_score(self):
        allowlist = {
            "phase": "phase6",
            "cadence": "monthly",
            "open_access_only": True,
            "source_levels": {"A": {"confidence_ceiling": "high"}},
            "approval": {
                "mode": "dashboard",
                "single_approver": "architect.openclaw@gmail.com",
                "ab_mode": "simulated",
            },
            "source_scraping_registry": {
                "path": "data/interim/phase7_source_scraping_registry.json",
                "key_fields": ["domain", "path_pattern"],
                "required_record_fields": [
                    "domain",
                    "path_pattern",
                    "checked_at",
                    "scraping_permitido",
                    "method",
                    "note",
                ],
                "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
            },
            "seed_sources": [
                {
                    "source_name": "ResearchGate",
                    "source_level": "A",
                    "peer_review_status": "published",
                    "open_access_verified": True,
                    "used_in": ["INT-02"],
                    "seed_role": "baseline_reference",
                    "source_domains": ["researchgate.net"],
                    "automation_scope": {
                        "pipeline_status": "out_of_scope",
                        "allowed_channel": "manual_only",
                        "scope_note": "manual only",
                    },
                    "scraping_governance": {
                        "mode": "observed_per_article",
                        "scraping_permitido": "no",
                        "registry_key": "researchgate.net::/publication/",
                        "status_note": "blocked by tos",
                    },
                }
            ],
        }
        seed_entries = [
            {
                "entry_id": "seed-1",
                "ref_id": "[4]",
                "intervention_id": "INT-02",
                "source_name": "ResearchGate",
                "source_level": "A",
                "peer_review_status": "published",
                "study_design": "rct",
                "sample_size": 100,
                "publication_year": 2022,
                "effect_size": None,
                "effect_size_text": "anchor",
                "expected_lift": None,
                "actionable_elements": {"copy": "x", "channel": "email", "timing": "t", "incentive": "i"},
                "applicability_to_vivamarket": "high",
                "citation_status": "pending",
                "quote_or_anchor": "anchor",
            }
        ]

        catalog_entries = build_catalog_entries(allowlist, seed_entries, "20260721")
        self.assertEqual(catalog_entries[0]["confidence_score"], "high")

    def test_render_catalog_summary_handles_empty_catalog(self):
        allowlist = {
            "phase": "phase6",
            "cadence": "monthly",
            "open_access_only": True,
            "source_levels": {"A": {"confidence_ceiling": "high"}},
            "approval": {
                "mode": "dashboard",
                "single_approver": "architect.openclaw@gmail.com",
                "ab_mode": "simulated",
            },
            "source_scraping_registry": {
                "path": "data/interim/phase7_source_scraping_registry.json",
                "key_fields": ["domain", "path_pattern"],
                "required_record_fields": [
                    "domain",
                    "path_pattern",
                    "checked_at",
                    "scraping_permitido",
                    "method",
                    "note",
                ],
                "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
            },
        }

        summary = render_catalog_summary([], allowlist, "20260721")
        self.assertIn("Entries: 0", summary)
        self.assertIn("Interventions covered:", summary)

    def test_build_and_write_catalog_rejects_invalid_scraping_governance_outcome(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            (root / "data" / "interim").mkdir(parents=True)

            allowlist = {
                "phase": "phase6",
                "cadence": "monthly",
                "open_access_only": True,
                "source_levels": {"A": {"confidence_ceiling": "high"}},
                "approval": {
                    "mode": "dashboard",
                    "single_approver": "architect.openclaw@gmail.com",
                    "ab_mode": "simulated",
                },
                "source_scraping_registry": {
                    "path": "data/interim/phase7_source_scraping_registry.json",
                    "key_fields": ["domain", "path_pattern"],
                    "required_record_fields": [
                        "domain",
                        "path_pattern",
                        "checked_at",
                        "scraping_permitido",
                        "method",
                        "note",
                    ],
                    "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
                },
                "seed_sources": [
                    {
                        "source_name": "ResearchGate",
                        "source_level": "A",
                        "peer_review_status": "published",
                        "open_access_verified": True,
                        "used_in": ["INT-02"],
                        "seed_role": "baseline_reference",
                        "source_domains": ["researchgate.net"],
                        "automation_scope": {
                            "pipeline_status": "out_of_scope",
                            "allowed_channel": "manual_only",
                            "scope_note": "manual only",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "maybe",
                            "registry_key": "researchgate.net::/publication/",
                            "status_note": "blocked by tos",
                        },
                    }
                ],
            }
            seed_entries = [
                {
                    "entry_id": "seed-1",
                    "ref_id": "[4]",
                    "intervention_id": "INT-02",
                    "source_name": "ResearchGate",
                    "source_level": "A",
                    "peer_review_status": "published",
                    "study_design": "rct",
                    "sample_size": 100,
                    "publication_year": 2022,
                    "effect_size": None,
                    "effect_size_text": "anchor",
                    "expected_lift": None,
                    "actionable_elements": {"copy": "x", "channel": "email", "timing": "t", "incentive": "i"},
                    "applicability_to_vivamarket": "high",
                    "citation_status": "pending",
                    "quote_or_anchor": "anchor",
                }
            ]

            (root / "config" / "evidence_sources_allowlist.yaml").write_text(json.dumps(allowlist), encoding="utf-8")
            (root / "data" / "interim" / "phase6_seed_evidence.json").write_text(json.dumps(seed_entries), encoding="utf-8")

            with self.assertRaises(ValueError):
                build_and_write_catalog(project_root=root, run_date="20260721")


if __name__ == "__main__":
    unittest.main()
