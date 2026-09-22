import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_extractor import build_and_write_phase7_extraction_snapshot


class TestPhase7Extractor(unittest.TestCase):
    def test_phase7_snapshot_fetches_only_rss_in_scope_sources_and_updates_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "config").mkdir()
            (root / "data" / "interim").mkdir(parents=True)
            (root / "data" / "processed").mkdir(parents=True)

            nn_feed = root / "data" / "interim" / "nn.xml"
            nn_feed.write_text(
                """<?xml version='1.0' encoding='UTF-8'?>
                <rss version='2.0'><channel>
                <item><title>NN One</title><link>https://example.com/nn1</link><description>NN desc</description><pubDate>Mon, 27 Jul 2026 00:00:00 GMT</pubDate></item>
                </channel></rss>
                """,
                encoding="utf-8",
            )
            bay_feed = root / "data" / "interim" / "bay.xml"
            bay_feed.write_text(
                """<?xml version='1.0' encoding='UTF-8'?>
                <rss version='2.0'><channel>
                <item><title>Bay One</title><link>https://example.com/bay1</link><description>Bay desc</description><pubDate>Mon, 27 Jul 2026 01:00:00 GMT</pubDate></item>
                <item><title>Bay Two</title><link>https://example.com/bay2</link><description>Bay desc 2</description><pubDate>Mon, 27 Jul 2026 02:00:00 GMT</pubDate></item>
                </channel></rss>
                """,
                encoding="utf-8",
            )

            allowlist = {
                "phase": "phase6",
                "cadence": "monthly",
                "open_access_only": True,
                "source_levels": {
                    "A": {"confidence_ceiling": "high"},
                    "B": {"confidence_ceiling": "high"},
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
                    "required_record_fields": ["domain", "path_pattern", "checked_at", "scraping_permitido", "method", "note"],
                    "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
                },
                "seed_sources": [],
                "expansion_pool": [
                    {
                        "source_name": "Nielsen Norman Group",
                        "source_level": "B",
                        "peer_review_status": "none",
                        "open_access_verified": True,
                        "used_in": ["INT-01"],
                        "seed_role": "priority_expansion",
                        "source_domains": ["nngroup.com"],
                        "automation_scope": {
                            "pipeline_status": "in_scope",
                            "allowed_channel": "rss_only",
                            "rss_url": nn_feed.as_uri(),
                            "scope_note": "rss only",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "solo_RSS_API",
                            "registry_key": "nngroup.com::/articles/",
                            "status_note": "rss only",
                        },
                    },
                    {
                        "source_name": "Baymard Institute public content",
                        "source_level": "B",
                        "peer_review_status": "none",
                        "open_access_verified": True,
                        "used_in": ["INT-05"],
                        "seed_role": "priority_expansion",
                        "source_domains": ["baymard.com"],
                        "automation_scope": {
                            "pipeline_status": "in_scope",
                            "allowed_channel": "rss_only",
                            "rss_url": bay_feed.as_uri(),
                            "scope_note": "rss only",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "solo_RSS_API",
                            "registry_key": "baymard.com::/blog/",
                            "status_note": "rss only",
                        },
                    },
                    {
                        "source_name": "CXL",
                        "source_level": "D",
                        "peer_review_status": "none",
                        "open_access_verified": True,
                        "used_in": ["INT-01"],
                        "seed_role": "baseline_reference",
                        "source_domains": ["cxl.com"],
                        "automation_scope": {
                            "pipeline_status": "out_of_scope",
                            "allowed_channel": "manual_only",
                            "scope_note": "manual",
                        },
                        "scraping_governance": {
                            "mode": "observed_per_article",
                            "scraping_permitido": "no",
                            "registry_key": "cxl.com::/blog/",
                            "status_note": "manual only",
                        },
                    },
                ],
            }
            (root / "config" / "evidence_sources_allowlist.yaml").write_text(json.dumps(allowlist), encoding="utf-8")
            (root / "data" / "interim" / "phase7_source_scraping_registry.json").write_text(
                json.dumps({"registry_version": "2026-07-27", "key_fields": ["domain", "path_pattern"], "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"], "records": []}),
                encoding="utf-8",
            )

            payload = build_and_write_phase7_extraction_snapshot(
                project_root=root,
                run_date="20260727",
                checked_at="2026-07-27T00:00:00+00:00",
            )

            snapshot_path = Path(payload["snapshot_path"])
            self.assertTrue(snapshot_path.exists())
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["article_count"], 3)
            self.assertEqual(snapshot["out_of_scope_source_count"], 1)
            self.assertEqual([item["source_name"] for item in snapshot["in_scope_articles"]], [
                "Nielsen Norman Group",
                "Baymard Institute public content",
                "Baymard Institute public content",
            ])
            self.assertEqual(snapshot["out_of_scope_sources"][0]["source_name"], "CXL")

            registry = json.loads((root / "data" / "interim" / "phase7_source_scraping_registry.json").read_text(encoding="utf-8"))
            self.assertEqual(len(registry["records"]), 3)
            self.assertEqual(
                {record["method"] for record in registry["records"]},
                {"official_rss_feed", "documented_manual_only"},
            )


if __name__ == "__main__":
    unittest.main()
