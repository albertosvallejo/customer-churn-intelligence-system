from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_keyboard_flow():
    css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")
    dashboard_template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    tested_template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
    new_template = (PROJECT_ROOT / "web" / "templates" / "new-actions-testing.html").read_text(encoding="utf-8")

    assert ":focus-visible" in css
    assert 'aria-label="Main navigation"' in dashboard_template
    assert 'aria-label="Main navigation"' in tested_template
    assert 'aria-label="Main navigation"' in new_template
    assert 'aria-live="polite"' in tested_template
    assert 'aria-live="polite"' in new_template
