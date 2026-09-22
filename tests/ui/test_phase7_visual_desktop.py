from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_kpi_chip_typography():
    dashboard_js = (PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    dashboard_css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")

    assert "kpi-chip-label" in dashboard_js
    assert "kpi-chip-subtitle" in dashboard_js
    assert "kpi-chip-value" in dashboard_js
    assert ".kpi-chip-label" in dashboard_css
    assert ".kpi-chip-subtitle" in dashboard_css
    assert ".kpi-chip-value" in dashboard_css


def test_summary_cards_have_separate_metric_and_copy():
    dashboard_template = (PROJECT_ROOT / "web" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    dashboard_css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")

    assert 'class="summary-label"' in dashboard_template
    assert 'class="summary-metric"' in dashboard_template
    assert 'class="summary-explainer"' in dashboard_template
    assert ".summary-label" in dashboard_css
    assert ".summary-metric" in dashboard_css
    assert ".summary-explainer" in dashboard_css


def test_three_pages_match_desktop_overlay():
    css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")
    tested_template = (PROJECT_ROOT / "web" / "templates" / "tested-actions-approval.html").read_text(encoding="utf-8")
    new_template = (PROJECT_ROOT / "web" / "templates" / "new-actions-testing.html").read_text(encoding="utf-8")

    assert "--sidebar-width: 210px" in css
    assert ".pill.info" in css
    assert 'Winning proposals' in tested_template
    assert 'Pending proposals before statistical test' in new_template


def test_dashboard_badges_are_semantic_and_distinct():
    css = (PROJECT_ROOT / "web" / "static" / "css" / "dashboard-app.css").read_text(encoding="utf-8")

    assert ".pill.positive" in css
    assert ".pill.negative" in css
    assert ".pill.warning" in css
    assert ".pill.neutral" in css
