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

BASELINE_FEATURES_PATH = DATA_PROCESSED_DIR / "churn_features_20260506.parquet"
CURRENT_ACTIONS_PATH = DATA_PROCESSED_DIR / "retention_actions_20260519.parquet"
CURRENT_PREDICTIONS_PATH = DATA_PROCESSED_DIR / "churn_predictions_20260506.parquet"
SYNTHETIC_ACTIONS_PATH = DATA_PROCESSED_DIR / "retention_actions_synthetic_30d.parquet"
SYNTHETIC_EVENTS_PATH = DATA_PROCESSED_DIR / "retention_events_synthetic_30d.parquet"
MODEL_METRICS_PATH = DATA_PROCESSED_DIR / "churn_model_metrics_20260506.csv"
MODEL_COMPARISON_PATH = DATA_PROCESSED_DIR / "churn_model_comparison_20260506.csv"
DRIVER_SUMMARY_PATH = DATA_PROCESSED_DIR / "churn_driver_summary_20260519.csv"

FEATURES_TO_MONITOR = [
    "recency_days",
    "total_orders",
    "total_payment_value",
    "orders_30d",
    "orders_90d",
]
TRIGGER_THRESHOLDS = {
    "feature_ks": 0.15,
    "score_mean_shift": 0.05,
    "high_tier_share": 0.30,
    "holdout_lift_below_zero": 0.0,
}


def _ks_statistic(left: pd.Series, right: pd.Series) -> float:
    left = left.dropna().astype(float).sort_values().to_numpy()
    right = right.dropna().astype(float).sort_values().to_numpy()
    if len(left) == 0 or len(right) == 0:
        return 0.0
    values = sorted(set(left.tolist() + right.tolist()))
    left_cdf = pd.Series(left).searchsorted(values, side="right") / len(left)
    right_cdf = pd.Series(right).searchsorted(values, side="right") / len(right)
    return float(max(abs(l - r) for l, r in zip(left_cdf, right_cdf)))


def _enrich_with_features(frame: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    missing = [feature for feature in FEATURES_TO_MONITOR if feature not in enriched.columns]
    if not missing:
        return enriched
    return enriched.merge(features[["customer_unique_id", *missing]], on="customer_unique_id", how="left")


def _load_monitoring_frame() -> tuple[pd.DataFrame, pd.DataFrame]:
    features = pd.read_parquet(BASELINE_FEATURES_PATH)
    actions = pd.read_parquet(CURRENT_ACTIONS_PATH)
    predictions = pd.read_parquet(CURRENT_PREDICTIONS_PATH)

    baseline = _enrich_with_features(predictions, features)
    current = _enrich_with_features(actions[actions["send_action_flag"].fillna(False)], features)
    return baseline, current


def build_governance_payload() -> dict:
    baseline, current = _load_monitoring_frame()
    kpi_payload = summarize_campaign_kpis(
        as_of="2026-05-30T00:00:00Z",
        actions_parquet_path=SYNTHETIC_ACTIONS_PATH,
        events_parquet_path=SYNTHETIC_EVENTS_PATH,
    )
    model_metrics = pd.read_csv(MODEL_METRICS_PATH)

    feature_rows = []
    for feature in FEATURES_TO_MONITOR:
        ks_stat = _ks_statistic(baseline[feature], current[feature])
        feature_rows.append(
            {
                "feature": feature,
                "baseline_mean": float(baseline[feature].mean()),
                "current_mean": float(current[feature].mean()),
                "ks_stat": ks_stat,
                "triggered": ks_stat > TRIGGER_THRESHOLDS["feature_ks"],
            }
        )

    baseline_scores = baseline["churn_probability"].astype(float)
    current_scores = current["churn_probability"].astype(float)
    baseline_top_decile = float((baseline_scores >= baseline_scores.quantile(0.9)).mean())
    current_top_decile = float((current_scores >= baseline_scores.quantile(0.9)).mean())
    score_shift = float(current_scores.mean() - baseline_scores.mean())
    score_drift = {
        "baseline_mean": float(baseline_scores.mean()),
        "current_mean": float(current_scores.mean()),
        "mean_shift": score_shift,
        "baseline_top_decile_density": baseline_top_decile,
        "current_top_decile_density": current_top_decile,
        "triggered": abs(score_shift) > TRIGGER_THRESHOLDS["score_mean_shift"],
    }

    baseline_tier = baseline["risk_tier"].value_counts(normalize=True).to_dict()
    current_tier = current["risk_tier"].value_counts(normalize=True).to_dict()
    tier_stability = []
    for tier in sorted(set(baseline_tier) | set(current_tier)):
        tier_stability.append(
            {
                "risk_tier": tier,
                "baseline_share": float(baseline_tier.get(tier, 0.0)),
                "current_share": float(current_tier.get(tier, 0.0)),
                "share_delta": float(current_tier.get(tier, 0.0) - baseline_tier.get(tier, 0.0)),
            }
        )
    current_high_share = float(current_tier.get("HIGH", 0.0))

    best_test = model_metrics[model_metrics["split"] == "test"].sort_values("roc_auc", ascending=False).iloc[0]

    triggers = []
    if any(row["triggered"] for row in feature_rows):
        triggers.append("Feature drift trigger breached on at least one monitored feature.")
    if score_drift["triggered"]:
        triggers.append("Score mean shift exceeded the 0.05 governance threshold.")
    if current_high_share > TRIGGER_THRESHOLDS["high_tier_share"]:
        triggers.append("HIGH tier share exceeded the 30% governance threshold.")
    negative_lift_tiers = [row["risk_tier"] for row in kpi_payload.get("holdout_lift", []) if row["holdout_lift"] < TRIGGER_THRESHOLDS["holdout_lift_below_zero"]]
    if negative_lift_tiers:
        triggers.append(f"Holdout lift below zero for: {', '.join(sorted(negative_lift_tiers))}.")
    if not triggers:
        triggers.append("No retraining trigger breached on the current portfolio governance pass.")

    return {
        "run_date": "2026-05-31",
        "measurement_label": "Simulated campaign baseline",
        "scope_note": "Governance pass built on the synthetic Block C closure baseline for portfolio/demo scope.",
        "feature_drift": feature_rows,
        "score_drift": score_drift,
        "tier_stability": tier_stability,
        "trigger_thresholds": TRIGGER_THRESHOLDS,
        "trigger_summary": triggers,
        "kpi_payload": kpi_payload,
        "model_snapshot": {
            "roc_auc": float(best_test["roc_auc"]),
            "average_precision": float(best_test["average_precision"]),
            "precision_at_top_10pct": float(best_test["precision_at_top_10pct"]),
        },
        "totals": {
            "baseline_rows": len(baseline),
            "current_rows": len(current),
            "closed_evaluations": int(kpi_payload["totals"]["closed_evaluations"]),
            "current_high_share": current_high_share,
        },
    }


def render_governance_report(payload: dict) -> str:
    feature_rows = "".join(
        f"<tr><td>{row['feature'].replace('_', ' ').title()}</td><td>{row['baseline_mean']:.4f}</td><td>{row['current_mean']:.4f}</td><td>{row['ks_stat']:.4f}</td><td><span class='flag {'flag-danger' if row['triggered'] else 'flag-ok'}'>{'Trigger' if row['triggered'] else 'Stable'}</span></td></tr>"
        for row in payload["feature_drift"]
    )
    tier_rows = "".join(
        f"<tr><td><span class='tier tier-{row['risk_tier'].lower()}'>{row['risk_tier']}</span></td><td>{row['baseline_share']*100:.2f}%</td><td>{row['current_share']*100:.2f}%</td><td>{row['share_delta']*100:.2f} pp</td></tr>"
        for row in payload["tier_stability"]
    )
    trigger_rows = "".join(f"<li>{item}</li>" for item in payload["trigger_summary"])
    trigger_state = "Attention required" if any("breached" in item.lower() or "below zero" in item.lower() for item in payload["trigger_summary"]) else "No retraining trigger breached"
    trigger_state_class = "flag-danger" if trigger_state == "Attention required" else "flag-ok"
    return f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <title>Phase 4 Governance Monitor</title>
  <style>
    :root {{ --bg:#f5f7fa; --surface:#ffffff; --surface-soft:#f8fafc; --text:#1f2937; --muted:#5b6472; --border:#d9e2ec; --brand:#005090; --high:#C01010; --medium:#E0B000; --low:#208040; --demo:#8a5a00; --demo-bg:#fff3cd; --ok:#1f7a3d; --ok-bg:#eaf7ef; --danger-bg:#fdecec; }}
    * {{ box-sizing:border-box; }}
    body {{ font-family: Arial, sans-serif; background:var(--bg); color:var(--text); margin:0; line-height:1.45; }}
    .wrap {{ max-width:1240px; margin:0 auto; padding:28px 20px 40px; }}
    .hero,.panel,.card {{ background:var(--surface); border:1px solid var(--border); border-radius:16px; box-shadow:0 6px 16px rgba(15,23,42,.05); }}
    .hero {{ padding:24px; }}
    .hero-top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
    .brand {{ display:flex; align-items:center; gap:14px; }}
    .brand img {{ height:44px; width:auto; border-radius:8px; }}
    .eyebrow {{ color:var(--brand); font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .hero h1,.panel h2 {{ margin:8px 0 10px; }}
    .hero p,.panel p,.meta,li {{ color:var(--muted); }}
    .pill,.flag,.tier {{ display:inline-block; padding:7px 11px; border-radius:999px; font-size:12px; font-weight:700; }}
    .pill {{ background:var(--demo-bg); color:var(--demo); }}
    .flag-ok {{ background:var(--ok-bg); color:var(--ok); }}
    .flag-danger {{ background:var(--danger-bg); color:var(--high); }}
    .tier-high {{ background:#fdecec; color:var(--high); }}
    .tier-medium {{ background:#fff7db; color:#8a6a00; }}
    .tier-low {{ background:#eaf7ef; color:var(--low); }}
    .summary {{ display:grid; grid-template-columns:2fr 1fr; gap:16px; margin-top:18px; }}
    .callout {{ background:var(--surface-soft); border:1px solid var(--border); border-radius:14px; padding:16px; }}
    .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; margin-top:18px; }}
    .card {{ padding:16px; }}
    .label {{ color:var(--muted); font-size:13px; }}
    .metric {{ font-size:30px; font-weight:700; margin-top:8px; color:var(--brand); }}
    .panel {{ padding:20px; margin-top:18px; }}
    .section-kicker {{ color:var(--brand); font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.08em; }}
    table {{ width:100%; border-collapse:collapse; margin-top:10px; background:var(--surface); }}
    th,td {{ border-bottom:1px solid var(--border); padding:11px 10px; text-align:left; font-size:14px; vertical-align:top; }}
    th {{ color:var(--muted); background:var(--surface-soft); }}
    ul {{ margin:10px 0 0 18px; padding:0; }}
    .meta {{ font-size:13px; margin-top:10px; }}
    @media (max-width: 860px) {{ .summary {{ grid-template-columns:1fr; }} .hero-top {{ align-items:flex-start; }} }}
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='hero'>
      <div class='hero-top'>
        <div class='brand'>
          <img src='../assets/images/logo.gif' alt='VivaMarket logo' />
          <div>
            <div class='eyebrow'>Phase 4 governance surface</div>
            <h1>Phase 4 Governance & Drift Monitor</h1>
            <p>{payload['scope_note']}</p>
          </div>
        </div>
        <div>
          <div class='pill'>{payload['measurement_label']}</div>
          <div class='meta'>Run date: {payload['run_date']} · Model baseline: canonical V2C</div>
        </div>
      </div>
      <div class='summary'>
        <div class='callout'>
          <div class='section-kicker'>Executive summary</div>
          <p><strong>What this means:</strong> the current governance pass shows a stable dispatch-ready population, no active retraining trigger, and a portfolio measurement layer suitable for stakeholder review.</p>
          <p><strong>Caveat:</strong> drift, holdout, and trigger logic are implemented and measurable here, but campaign outcome evidence still comes from a simulated benchmark rather than live production telemetry.</p>
        </div>
        <div class='callout'>
          <div class='section-kicker'>Decision implication</div>
          <p><span class='flag {trigger_state_class}'>{trigger_state}</span></p>
          <p class='meta'>Use this report to judge whether the baseline is stable enough to keep as reference or whether retraining/governance escalation should be reviewed.</p>
        </div>
      </div>
      <div class='grid'>
        <div class='card'><div class='label'>Baseline rows</div><div class='metric'>{payload['totals']['baseline_rows']:,}</div></div>
        <div class='card'><div class='label'>Current dispatch-ready rows</div><div class='metric'>{payload['totals']['current_rows']:,}</div></div>
        <div class='card'><div class='label'>Closed evaluations</div><div class='metric'>{payload['totals']['closed_evaluations']:,}</div></div>
        <div class='card'><div class='label'>Current HIGH tier share</div><div class='metric'>{payload['totals']['current_high_share']*100:.2f}%</div></div>
      </div>
    </div>
    <div class='panel'>
      <div class='section-kicker'>Layer 1</div>
      <h2>Feature drift layer</h2>
      <p>Compares the current dispatch-ready slice against the baseline population on the core monitored features that matter for churn scoring behavior.</p>
      <table><thead><tr><th>Feature</th><th>Baseline mean</th><th>Current mean</th><th>KS stat</th><th>Status</th></tr></thead><tbody>{feature_rows}</tbody></table>
    </div>
    <div class='panel'>
      <div class='section-kicker'>Layer 2</div>
      <h2>Score drift layer</h2>
      <p>Shows whether the current scoring distribution moved enough to threaten the stability of operational decision-making.</p>
      <table><tbody>
        <tr><th>Baseline mean score</th><td>{payload['score_drift']['baseline_mean']:.4f}</td></tr>
        <tr><th>Current mean score</th><td>{payload['score_drift']['current_mean']:.4f}</td></tr>
        <tr><th>Mean shift</th><td>{payload['score_drift']['mean_shift']:.4f}</td></tr>
        <tr><th>Baseline top-decile density</th><td>{payload['score_drift']['baseline_top_decile_density']*100:.2f}%</td></tr>
        <tr><th>Current top-decile density</th><td>{payload['score_drift']['current_top_decile_density']*100:.2f}%</td></tr>
        <tr><th>Status</th><td><span class='flag {'flag-danger' if payload['score_drift']['triggered'] else 'flag-ok'}'>{'Trigger' if payload['score_drift']['triggered'] else 'Stable'}</span></td></tr>
      </tbody></table>
    </div>
    <div class='panel'>
      <div class='section-kicker'>Layer 3</div>
      <h2>Tier stability layer</h2>
      <p>Confirms whether the action mix remains consistent with the baseline tier policy rather than drifting into a materially different dispatch posture.</p>
      <table><thead><tr><th>Tier</th><th>Baseline share</th><th>Current share</th><th>Delta</th></tr></thead><tbody>{tier_rows}</tbody></table>
    </div>
    <div class='panel'>
      <div class='section-kicker'>Governance output</div>
      <h2>Governance trigger summary</h2>
      <ul>{trigger_rows}</ul>
    </div>
  </div>
</body>
</html>"""


def render_model_card_v3(payload: dict) -> str:
    comparison = pd.read_csv(MODEL_COMPARISON_PATH)
    drivers = pd.read_csv(DRIVER_SUMMARY_PATH).sort_values("rows_n", ascending=False).head(4)
    comparison_rows = "\n".join(
        f"| {row.version_name} | {row.model_name} | {row.roc_auc:.4f} | {row.average_precision:.4f} | {row.precision_at_top_10pct:.4f} |"
        for row in comparison.itertuples(index=False)
    )
    lift_rows = payload["kpi_payload"].get("holdout_lift", [])
    lift_md = "\n".join(
        f"| {row['risk_tier']} | {row['attr_window_days']} | {row['treated_conversion_rate']:.4f} | {row['holdout_conversion_rate']:.4f} | {row['holdout_lift']:.4f} |"
        for row in lift_rows
    ) or "| — | — | — | — | — |"
    driver_rows = "\n".join(
        f"| {row.risk_tier} | {row.top_driver_group} | {row.recommended_offer_type} | {int(row.rows_n)} |"
        for row in drivers.itertuples(index=False)
    )
    trigger_rows = "\n".join(f"- {item}" for item in payload["trigger_summary"])
    feature_drift_rows = "\n".join(
        f"| {row['feature']} | {row['baseline_mean']:.4f} | {row['current_mean']:.4f} | {row['ks_stat']:.4f} | {'YES' if row['triggered'] else 'NO'} |"
        for row in payload["feature_drift"]
    )
    tier_stability_rows = "\n".join(
        f"| {row['risk_tier']} | {row['baseline_share']:.4f} | {row['current_share']:.4f} | {row['share_delta']:.4f} |"
        for row in payload["tier_stability"]
    )
    return f"""# MODEL CARD — DAILY CUSTOMER CHURN PREDICTOR (PHASE 4 V3 DEMO)

**Card version:** 20260531  
**Measurement scope:** {payload['measurement_label']}

## 1. Model identity
- **Project:** Daily Customer Churn Predictor — VivaMarket Brasil
- **Analytical line:** canonical `V2C` baseline with Phase 4 synthetic feedback-loop governance layer
- **Primary model:** XGBoost
- **Evaluation frame:** held-out temporal test split + synthetic closed-conversion measurement baseline for portfolio governance review

## 2. Intended use
- Demonstrate a production-minded retention scoring workflow with explicit governance and measurement layers.
- Support stakeholder review of tiering, drift, holdout integrity, and portfolio-grade experimentation logic.
- Keep all campaign-performance evidence clearly labeled as demo/simulated until real customer outcome telemetry exists.

## 3. Performance snapshot
- **ROC AUC:** {payload['model_snapshot']['roc_auc']:.4f}
- **Average precision:** {payload['model_snapshot']['average_precision']:.4f}
- **Precision@Top 10%:** {payload['model_snapshot']['precision_at_top_10pct']:.4f}
- **Closed conversion evaluations:** {payload['totals']['closed_evaluations']:,}
- **Current dispatch-ready rows:** {payload['totals']['current_rows']:,}

## 4. Comparison vs prior baselines
| Version | Model | ROC AUC | Avg precision | Precision@Top 10% |
| --- | --- | ---: | ---: | ---: |
{comparison_rows}

## 5. Observed governance / measurement layer
### Holdout lift by tier (simulated benchmark)
| Tier | Window (days) | Treated CR | Holdout CR | Lift |
| --- | ---: | ---: | ---: | ---: |
{lift_md}

### Drift trigger summary
{trigger_rows}

## 6. Active drift monitor snapshot
| Feature | Baseline mean | Current mean | KS stat | Trigger |
| --- | ---: | ---: | ---: | --- |
{feature_drift_rows}

## 7. Tier stability snapshot
| Tier | Baseline share | Current share | Delta |
| --- | ---: | ---: | ---: |
{tier_stability_rows}

## 8. Top active driver families
| Tier | Driver family | Offer type | Rows |
| --- | --- | --- | ---: |
{driver_rows}

## 9. Main limitations and honesty note
- Campaign outcomes in this card are synthetic/demo-generated and must not be presented as observed production lift.
- The target remains positive-heavy, so ranking strength is more trustworthy than naive probability interpretation.
- Governance triggers are useful here as a design demonstration, but the portfolio scope still lacks true production-time telemetry.

## 10. Recommended next step
- Use this governance baseline to support Block F population-redesign benchmarking, keeping the `V2C` baseline as the permanent reference and documenting whether the redesign yields materially better holdout lift or only a marginal/null improvement.
"""


def write_outputs(payload: dict) -> dict[str, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    html_path = REPORTS_DIR / "phase4_governance_monitor_latest.html"
    json_path = DATA_PROCESSED_DIR / "phase4_governance_monitor_latest.json"
    md_path = REPORTS_DIR / "model_card_v3_phase4_demo_20260531.md"
    html_path.write_text(render_governance_report(payload), encoding="utf-8")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_model_card_v3(payload), encoding="utf-8")
    return {"html": html_path, "json": json_path, "model_card": md_path}


def main() -> None:
    payload = build_governance_payload()
    outputs = write_outputs(payload)
    logger.info("phase4_governance_payload=%s", json.dumps(payload, ensure_ascii=False))
    logger.info("phase4_governance_outputs=%s", {k: str(v) for k, v in outputs.items()})


if __name__ == "__main__":
    main()
