from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dashboard_history_controls_lock_five_per_page_and_csv_export():
    dashboard_js = (PROJECT_ROOT / "web" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

    assert "pageSize: 5" in dashboard_js
    assert "downloadCsv(`phase7_history_${runDate}.csv`" in dashboard_js
    assert "renderPagination({" in dashboard_js


def test_tested_history_controls_lock_five_per_page_and_csv_export():
    tested_js = (PROJECT_ROOT / "web" / "static" / "js" / "tested-actions.js").read_text(encoding="utf-8")

    assert "pageSize: 5" in tested_js
    assert "downloadCsv(`phase7_history_${runDate}.csv`" in tested_js
    assert "renderPagination({" in tested_js
