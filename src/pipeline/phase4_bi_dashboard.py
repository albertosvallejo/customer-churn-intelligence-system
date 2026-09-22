import html
import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline.campaign_kpis import summarize_campaign_kpis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
OUTPUT_PATH = REPORTS_DIR / "phase4_bi_dashboard_demo.html"


def _load_inputs() -> dict[str, pd.DataFrame | dict]:
    actions = pd.read_parquet(DATA_PROCESSED_DIR / "retention_actions_20260519.parquet")
    driver_summary = pd.read_csv(DATA_PROCESSED_DIR / "churn_driver_summary_20260519.csv")
    model_metrics = pd.read_csv(DATA_PROCESSED_DIR / "churn_model_metrics_20260506.csv")
    model_comparison = pd.read_csv(DATA_PROCESSED_DIR / "churn_model_comparison_20260506.csv")
    synthetic_campaign = pd.read_parquet(DATA_PROCESSED_DIR / "campaign_kpis_synthetic.parquet")
    synthetic_actions = DATA_PROCESSED_DIR / "retention_actions_synthetic_30d.parquet"
    synthetic_events = DATA_PROCESSED_DIR / "retention_events_synthetic_30d.parquet"
    kpi_payload = summarize_campaign_kpis(
        as_of="2026-05-30T00:00:00Z",
        actions_parquet_path=synthetic_actions,
        events_parquet_path=synthetic_events,
    )
    return {
        "actions": actions,
        "driver_summary": driver_summary,
        "model_metrics": model_metrics,
        "model_comparison": model_comparison,
        "synthetic_campaign": synthetic_campaign,
        "kpi_payload": kpi_payload,
    }


def _fmt_int(value: float) -> str:
    return f"{int(value):,}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _fmt_pp(value: float) -> str:
    return f"{value:.2f} pp"


def render_dashboard(inputs: dict[str, pd.DataFrame | dict]) -> str:
    actions = inputs["actions"]
    driver_summary = inputs["driver_summary"]
    model_metrics = inputs["model_metrics"]
    synthetic_campaign = inputs["synthetic_campaign"]
    kpi_payload = inputs["kpi_payload"]

    tier_counts = actions["risk_tier"].value_counts().rename_axis("risk_tier").reset_index(name="customers")
    dispatch_summary = pd.DataFrame(
        [
            {"label": "Dispatch-ready", "value": int(actions["send_action_flag"].fillna(False).sum())},
            {"label": "Holdout", "value": int(actions["control_group_flag"].fillna(False).sum())},
            {"label": "Push enabled", "value": int(actions["primary_channels"].fillna("").str.contains("push").sum())},
            {"label": "VIP human touch", "value": int(actions["vip_human_touch_flag"].fillna(False).sum())},
        ]
    )
    top_drivers = driver_summary.sort_values(["rows_n", "avg_probability"], ascending=[False, False]).head(6)
    test_metrics = model_metrics[model_metrics["split"] == "test"].sort_values("roc_auc", ascending=False).head(3)

    tier_chart = {
        "labels": tier_counts["risk_tier"].tolist(),
        "values": tier_counts["customers"].tolist(),
    }
    campaign_chart = {
        "tiers": synthetic_campaign["tier"].tolist(),
        "treated": synthetic_campaign["cr_treated"].tolist(),
        "holdout": synthetic_campaign["cr_holdout"].tolist(),
    }
    driver_chart = {
        "labels": [f"{tier} · {driver}" for tier, driver in zip(top_drivers["risk_tier"], top_drivers["top_driver_group"])],
        "values": top_drivers["rows_n"].tolist(),
    }

    tier_rows = "".join(
        f"<tr><td>{html.escape(str(row.risk_tier))}</td><td>{_fmt_int(row.customers)}</td><td>{_fmt_pct(row.customers / len(actions))}</td></tr>"
        for row in tier_counts.itertuples(index=False)
    )

    dispatch_rows = "".join(
        f"<tr><td>{html.escape(str(row.label))}</td><td>{_fmt_int(row.value)}</td></tr>"
        for row in dispatch_summary.itertuples(index=False)
    )

    driver_rows = "".join(
        f"<tr><td>{html.escape(str(row.risk_tier))}</td><td>{html.escape(str(row.top_driver_group))}</td><td>{html.escape(str(row.recommended_offer_type))}</td><td>{_fmt_int(row.rows_n)}</td><td>{_fmt_pct(float(row.avg_probability))}</td></tr>"
        for row in top_drivers.itertuples(index=False)
    )

    metric_rows = "".join(
        f"<tr><td>{html.escape(str(row.model_name))}</td><td>{html.escape(str(row.split))}</td><td>{row.roc_auc:.4f}</td><td>{row.average_precision:.4f}</td><td>{_fmt_pct(float(row.precision_at_top_10pct))}</td></tr>"
        for row in test_metrics.itertuples(index=False)
    )

    campaign_rows = "".join(
        f"<tr><td>{html.escape(str(row.tier))}</td><td>{int(row.attr_window_days)}</td><td>{_fmt_int(row.dispatched)}</td><td>{_fmt_pct(float(row.delivery_rate))}</td><td>{_fmt_pct(float(row.open_rate))}</td><td>{_fmt_pct(float(row.click_rate))}</td><td>{_fmt_int(row.coupon_redemptions)}</td><td>{_fmt_pp(float(row.holdout_lift_pp))}</td></tr>"
        for row in synthetic_campaign.itertuples(index=False)
    )

    holdout_rows = "".join(
        f"<tr><td>{html.escape(str(row['risk_tier']))}</td><td>{int(row['attr_window_days'])}</td><td>{_fmt_pct(float(row['treated_conversion_rate']))}</td><td>{_fmt_pct(float(row['holdout_conversion_rate']))}</td><td>{_fmt_pct(float(row['holdout_lift']))}</td></tr>"
        for row in kpi_payload.get("holdout_lift", [])
    )

    top_cards = [
        ("Customers in current scored base", _fmt_int(len(actions)), "Operational snapshot from the canonical 20260519 retention payload."),
        ("Dispatch-ready customers", _fmt_int(int(actions["send_action_flag"].fillna(False).sum())), "Customers currently eligible for governed action dispatch."),
        ("Holdout share", _fmt_pct(actions["control_group_flag"].fillna(False).mean()), "Protected control cohort needed for causal measurement integrity."),
        ("Best test ROC AUC", f"{test_metrics.iloc[0]['roc_auc']:.4f}", "Best available test-set discrimination from the canonical V2C baseline."),
    ]
    cards_html = "".join(
        f"<div class='card'><h2>{html.escape(title)}</h2><div class='metric'>{value}</div><div class='hint'>{html.escape(hint)}</div></div>"
        for title, value, hint in top_cards
    )

    tier_chart_json = html.escape(json.dumps(tier_chart))
    campaign_chart_json = html.escape(json.dumps(campaign_chart))
    driver_chart_json = html.escape(json.dumps(driver_chart))

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Phase 4 BI Dashboard Demo</title>
  <script src=\"https://cdn.plot.ly/plotly-2.35.2.min.js\"></script>
  <style>
    :root {{ --bg:#f5f7fa; --surface:#ffffff; --surface-soft:#f8fafc; --text:#1f2937; --muted:#5b6472; --brand:#005090; --accent:#1f7a3d; --accent2:#0f766e; --border:#d9e2ec; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Arial,sans-serif; background:var(--bg); color:var(--text); }}
    .wrap {{ max-width:1320px; margin:0 auto; padding:28px 20px 48px; }}
    .hero,.card,.panel {{ background:var(--surface); border:1px solid var(--border); border-radius:16px; box-shadow:0 6px 16px rgba(15,23,42,.05); }}
    .hero {{ margin-bottom:24px; padding:24px; }}
    .hero-top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
    .brand {{ display:flex; align-items:center; gap:14px; }}
    .brand img {{ height:44px; width:auto; border-radius:8px; }}
    .eyebrow {{ color:var(--brand); font-size:12px; letter-spacing:.08em; text-transform:uppercase; font-weight:700; }}
    h1 {{ margin:8px 0 10px; font-size:34px; }}
    .sub {{ max-width:960px; color:var(--muted); line-height:1.55; }}
    .pill {{ display:inline-block; margin-top:10px; margin-right:10px; padding:8px 12px; border-radius:999px; font-size:13px; }}
    .live {{ background:#eaf7ef; color:var(--accent); font-weight:700; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:16px; margin:24px 0; }}
    .card,.panel {{ padding:18px; }}
    .card h2 {{ margin:0 0 8px; font-size:14px; color:var(--muted); font-weight:600; }}
    .metric {{ font-size:32px; font-weight:700; }}
    .hint {{ margin-top:8px; color:var(--muted); font-size:13px; line-height:1.4; }}
    .view-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .view-title {{ margin:0 0 8px; font-size:22px; }}
    .view-sub {{ margin:0 0 18px; color:var(--muted); line-height:1.5; }}
    .tag {{ display:inline-block; margin-bottom:12px; padding:6px 10px; border-radius:999px; background:#eaf2fb; color:var(--brand); font-size:12px; font-weight:700; text-transform:uppercase; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid var(--border); text-align:left; font-size:14px; vertical-align:top; }}
    th {{ color:var(--muted); font-weight:600; background:var(--surface-soft); }}
    tr:last-child td {{ border-bottom:none; }}
    .section {{ margin-top:18px; }}
    .section h3 {{ margin:0 0 8px; font-size:17px; }}
    .chart {{ width:100%; height:280px; margin-top:10px; border:1px solid var(--border); border-radius:12px; background:var(--surface-soft); }}
    .note {{ margin-top:18px; padding:14px 16px; border-left:4px solid var(--brand); background:#eaf2fb; color:var(--text); border-radius:10px; line-height:1.5; }}
    .footer {{ margin-top:26px; color:var(--muted); font-size:12px; }}
    @media (max-width: 980px) {{ .view-grid {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="hero-top"><div class="brand"><img src="../assets/images/logo.gif" alt="VivaMarket logo" /><div><div class="eyebrow">Phase 4 · Stakeholder BI surface</div><h1>Retention BI Dashboard</h1><div class="sub">Stakeholder-facing dashboard with clear separation between the daily operational view and the analytical learning view. It prioritizes actionability, model transparency, and business interpretation speed.</div></div></div><div class="pill live">Current portfolio baseline · canonical V2C + Phase 4 reporting layer</div></div>
    </div>

    <div class="grid">{cards_html}</div>

    <div class="view-grid">
      <div class="panel">
        <div class="tag">Operational view · CRM manager / retention analyst</div>
        <h2 class="view-title">What should operations look at today?</h2>
        <p class="view-sub">This side is optimized for actionability within one minute: current tier mix, dispatch readiness, holdout pressure, and operational coverage signals.</p>

        <div class="section">
          <h3>Tier mix in the current scored base</h3>
          <div id="tier-mix-chart" class="chart"></div>
          <table>
            <thead><tr><th>Risk tier</th><th>Customers</th><th>Share</th></tr></thead>
            <tbody>{tier_rows}</tbody>
          </table>
        </div>

        <div class="section">
          <h3>Dispatch governance summary</h3>
          <table>
            <thead><tr><th>Signal</th><th>Value</th></tr></thead>
            <tbody>{dispatch_rows}</tbody>
          </table>
        </div>

        <div class="section">
          <h3>Campaign effectiveness snapshot</h3>
          <div id="campaign-kpi-chart" class="chart"></div>
          <table>
            <thead><tr><th>Tier</th><th>Window</th><th>Dispatched</th><th>Delivery rate</th><th>Open rate</th><th>Click rate</th><th>Coupon redemptions</th><th>Holdout lift</th></tr></thead>
            <tbody>{campaign_rows}</tbody>
          </table>
        </div>
      </div>

      <div class="panel">
        <div class="tag">Analytical view · Data scientist / stakeholder</div>
        <h2 class="view-title">What is the system learning?</h2>
        <p class="view-sub">This side focuses on current model quality, active driver families, and the strength of the current action design.</p>

        <div class="section">
          <h3>Model quality snapshot</h3>
          <table>
            <thead><tr><th>Model</th><th>Split</th><th>ROC AUC</th><th>Avg precision</th><th>Precision @ top 10%</th></tr></thead>
            <tbody>{metric_rows}</tbody>
          </table>
        </div>

        <div class="section">
          <h3>Top active driver families</h3>
          <div id="driver-chart" class="chart"></div>
          <table>
            <thead><tr><th>Tier</th><th>Driver family</th><th>Offer type</th><th>Rows</th><th>Avg churn probability</th></tr></thead>
            <tbody>{driver_rows}</tbody>
          </table>
        </div>

        <div class="section">
          <h3>Current response pattern by tier</h3>
          <table>
            <thead><tr><th>Tier</th><th>Window</th><th>Treated conversion</th><th>Holdout conversion</th><th>Lift</th></tr></thead>
            <tbody>{holdout_rows}</tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="note">Reader guide: use this surface for business interpretation, current action prioritization, and high-level effectiveness reading. Deep validation details remain in the internal KPI and governance monitors.</div>
    <div class="footer">Output file: phase4_bi_dashboard_demo.html · Source artifacts: retention_actions_20260519, churn_driver_summary_20260519, churn_model_metrics_20260506, churn_model_comparison_20260506, synthetic campaign KPI inputs, and closed-evaluation KPI payload.</div>
  </div>
  <script>
    const tierChart = JSON.parse('{tier_chart_json}');
    const campaignChart = JSON.parse('{campaign_chart_json}');
    const driverChart = JSON.parse('{driver_chart_json}');
    const baseLayout = {{
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: {{color: '#e5e7eb'}},
      margin: {{l: 40, r: 20, t: 20, b: 40}},
    }};
    Plotly.newPlot('tier-mix-chart', [{{
      type: 'bar',
      x: tierChart.labels,
      y: tierChart.values,
      marker: {{color: ['#38bdf8', '#22c55e', '#f59e0b']}},
      hovertemplate: '%{{x}}: %{{y:,}} customers<extra></extra>'
    }}], {{...baseLayout, yaxis: {{title: 'Customers'}}, xaxis: {{title: 'Tier'}}}}, {{displayModeBar: false, responsive: true}});
    Plotly.newPlot('campaign-kpi-chart', [
      {{type: 'bar', name: 'Treated conversion', x: campaignChart.tiers, y: campaignChart.treated, marker: {{color: '#22c55e'}}, hovertemplate: '%{{x}}: %{{y:.1%}}<extra></extra>'}},
      {{type: 'bar', name: 'Holdout conversion', x: campaignChart.tiers, y: campaignChart.holdout, marker: {{color: '#f59e0b'}}, hovertemplate: '%{{x}}: %{{y:.1%}}<extra></extra>'}}
    ], {{...baseLayout, barmode: 'group', yaxis: {{title: 'Conversion rate', tickformat: '.0%'}}, xaxis: {{title: 'Tier'}}}}, {{displayModeBar: false, responsive: true}});
    Plotly.newPlot('driver-chart', [{{
      type: 'bar',
      orientation: 'h',
      x: driverChart.values.slice().reverse(),
      y: driverChart.labels.slice().reverse(),
      marker: {{color: '#7c3aed'}},
      hovertemplate: '%{{y}}: %{{x:,}} rows<extra></extra>'
    }}], {{...baseLayout, xaxis: {{title: 'Rows'}}, yaxis: {{title: ''}}, margin: {{l: 170, r: 20, t: 20, b: 40}}}}, {{displayModeBar: false, responsive: true}});
  </script>
</body>
</html>
"""


def write_dashboard(output_path: Path = OUTPUT_PATH) -> Path:
    inputs = _load_inputs()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_dashboard(inputs), encoding="utf-8")
    return output_path


def main() -> None:
    output_path = write_dashboard()
    logger.info("phase4_bi_dashboard_written=%s", output_path)


if __name__ == "__main__":
    main()
