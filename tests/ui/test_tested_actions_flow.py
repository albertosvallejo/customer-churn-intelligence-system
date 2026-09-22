from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_tested_accept_reject_flow_is_business_legible():
    template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")

    assert "Winning proposals" in template
    assert "Operator token required" in template
    assert "Accept" in js
    assert "Reject" in js
    assert "Phase 7 review token is required before submitting a decision." in js
    assert "Decision blocked" in js
    assert "Missing required decision context" in js


def test_new_actions_flow_keeps_business_copy_and_blocks_missing_recommendation():
    template = (PROJECT_ROOT / "web" / "templates" / "new-actions-testing.html").read_text(encoding="utf-8")
    js = (PROJECT_ROOT / "web" / "static" / "js" / "new-actions.js").read_text(encoding="utf-8")

    assert "Pending proposals before statistical test" in template
    assert "Approve for test" in js
    assert "Postpone" in js
    assert "Reject" in js
    assert "Phase 7 review token is required before recording a proposal decision." in js
    assert "Missing required proposal context" in js
