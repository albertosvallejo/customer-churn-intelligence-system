from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_business_copy_hides_internal_enums_and_empty_fields():
    tested_js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")
    new_js = (PROJECT_ROOT / "web" / "static" / "js" / "new-actions.js").read_text(encoding="utf-8")
    dashboard_template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert "keep_incumbent" in tested_js
    assert "promote_challenger" in tested_js
    assert "Accept" in tested_js
    assert "Reject" in tested_js
    assert "Pending review" in new_js
    assert "No recommendation available." not in new_js
    assert "Tested Actions Approval" in dashboard_template
    assert "New Actions Approval" in dashboard_template
