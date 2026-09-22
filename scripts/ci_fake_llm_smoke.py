#!/usr/bin/env python3
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_proposal_builder import synthesize_article_with_openai


def main() -> None:
    article = {
        "source_name": "CI synthetic source",
        "title": "Email benchmark improved 15%",
        "summary": "A retained-customer test reported 15% uplift across 2 cohorts.",
        "link": "https://example.com/ci-fake-llm",
        "published_at": "2026-07-27T00:00:00+00:00",
    }
    result = synthesize_article_with_openai(article, project_root=PROJECT_ROOT)
    if (result.get("llm_request") or {}).get("provider") != "fake":
        raise SystemExit("FAIL: fake LLM provider was not used")
    if result.get("generation_contract_violation"):
        raise SystemExit("FAIL: fake LLM returned invalid contract payload")
    print(json.dumps({
        "provider": result["llm_request"]["provider"],
        "response_id": result["llm_response"]["id"],
        "numeric_claims_used": result["numeric_claims_used"],
    }))


if __name__ == "__main__":
    main()
