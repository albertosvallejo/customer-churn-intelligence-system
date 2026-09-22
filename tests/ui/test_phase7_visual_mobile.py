from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_three_pages_match_mobile_overlay():
    css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")
    dashboard_template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")

    assert "@media (max-width: 760px)" in css
    assert ".feedback-panel { display: none; }" in css
    assert "overflow-x: auto" in css
    assert "Rate this dashboard" in dashboard_template
