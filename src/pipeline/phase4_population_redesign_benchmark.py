import json
import logging
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

EVALS_PATH = DATA_PROCESSED_DIR / "conversion_evaluations_closed_synthetic.parquet"
ACTIONS_PATH = DATA_PROCESSED_DIR / "retention_actions_synthetic_30d.parquet"
OUTPUT_JSON = DATA_PROCESSED_DIR / "phase4_population_redesign_benchmark_20260531.json"
OUTPUT_HTML = REPORTS_DIR / "phase4_population_redesign_benchmark_20260531.html"
OUTPUT_MD = REPORTS_DIR / "phase4_population_redesign_decision_20260531.md"

MIN_CLOSED_EVALS = 20
MIN_POSITIVE_LIFT = 0.01
MIN_SEGMENT_SHARE = 0.20


def _load_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    evaluations = pd.read_parquet(EVALS_PATH)
    actions = pd.read_parquet(ACTIONS_PATH)
    return evaluations, actions


def build_population_benchmark_payload() -> dict:
    evaluations, actions = _load_frames()

    customer_action_profile = (
        actions.groupby("customer_unique_id")
        .agg(
            action_count=("action_id", "count"),
            avg_score=("score", "mean"),
            dominant_tier=("tier", lambda s: s.mode().iloc[0]),
        )
        .reset_index()
    )

    base = (
        evaluations.groupby("customer_unique_id")
        .agg(
            closed_evaluations=("evaluation_id", "count"),
            conversions=("converted", "sum"),
            holdout_share=("holdout", "mean"),
            dominant_tier=("tier", lambda s: s.mode().iloc[0]),
        )
        .reset_index()
    )

    treated = (
        evaluations[~evaluations["holdout"]]
        .groupby("customer_unique_id")
        .agg(treated_evaluations=("evaluation_id", "count"), treated_conversions=("converted", "sum"))
        .reset_index()
    )
    holdout = (
        evaluations[evaluations["holdout"]]
        .groupby("customer_unique_id")
        .agg(holdout_evaluations=("evaluation_id", "count"), holdout_conversions=("converted", "sum"))
        .reset_index()
    )

    customer = base.merge(treated, on="customer_unique_id", how="left").merge(holdout, on="customer_unique_id", how="left")
    customer = customer.merge(customer_action_profile, on=["customer_unique_id", "dominant_tier"], how="left")
    customer = customer.fillna({
        "treated_evaluations": 0,
        "treated_conversions": 0,
        "holdout_evaluations": 0,
        "holdout_conversions": 0,
    })

    customer["conversion_rate"] = customer["conversions"] / customer["closed_evaluations"]
    customer["treated_conversion_rate"] = customer["treated_conversions"] / customer["treated_evaluations"].replace(0, pd.NA)
    customer["holdout_conversion_rate"] = customer["holdout_conversions"] / customer["holdout_evaluations"].replace(0, pd.NA)
    customer["holdout_lift"] = customer["treated_conversion_rate"] - customer["holdout_conversion_rate"]

    overall_treated_rate = float(evaluations[~evaluations["holdout"]]["converted"].mean())
    customer["retainable_candidate"] = (
        (customer["closed_evaluations"] >= MIN_CLOSED_EVALS)
        & (
            (customer["treated_conversion_rate"].fillna(0.0) > overall_treated_rate)
            | (
                customer["holdout_lift"].fillna(0.0) > MIN_POSITIVE_LIFT
            )
            | (
                customer["dominant_tier"].isin(["HIGH", "MEDIUM"]) & (customer["conversion_rate"] > overall_treated_rate)
            )
        )
    )
    customer["segment"] = customer["retainable_candidate"].map({True: "retainable", False: "structural_single_purchase"})

    segment_rows = []
    for segment_name, segment_df in customer.groupby("segment"):
        treated_total = float(segment_df["treated_conversions"].sum()) / float(segment_df["treated_evaluations"].sum())
        holdout_total = float(segment_df["holdout_conversions"].sum()) / float(segment_df["holdout_evaluations"].sum())
        segment_rows.append(
            {
                "segment": segment_name,
                "customers": int(segment_df["customer_unique_id"].nunique()),
                "avg_closed_evaluations": float(segment_df["closed_evaluations"].mean()),
                "avg_conversion_rate": float(segment_df["conversion_rate"].mean()),
                "avg_treated_conversion_rate": treated_total,
                "avg_holdout_conversion_rate": holdout_total,
                "avg_holdout_lift": treated_total - holdout_total,
                "avg_score": float(segment_df["avg_score"].mean()),
            }
        )
    summary = pd.DataFrame(segment_rows)

    tier_mix = (
        customer.groupby(["segment", "dominant_tier"])
        .size()
        .reset_index(name="customers")
    )

    retainable_share = float((customer["segment"] == "retainable").mean())
    retainable_row = summary[summary["segment"] == "retainable"]
    structural_row = summary[summary["segment"] == "structural_single_purchase"]
    retainable_lift = float(retainable_row["avg_holdout_lift"].iloc[0]) if not retainable_row.empty else 0.0
    structural_lift = float(structural_row["avg_holdout_lift"].iloc[0]) if not structural_row.empty else 0.0

    decision = "defer_v4_keep_v2c"
    rationale = [
        "The benchmark uses the current portfolio evidence layer.",
        "This is a portfolio/demo redesign benchmark, not a production-observed retraining decision.",
    ]
    if retainable_share >= MIN_SEGMENT_SHARE and retainable_lift > structural_lift and retainable_lift > 0:
        decision = "support_population_redesign_candidate"
        rationale.append(
            "Retainable customers show stronger average holdout lift than the structurally single-purchase segment, supporting the redesign hypothesis."
        )
    else:
        rationale.append(
            "The synthetic benchmark does not yet show a strong enough separation to justify replacing the V2C baseline outright."
        )

    return {
        "run_date": "2026-05-31",
        "measurement_label": "Portfolio decision benchmark",
        "decision": decision,
        "decision_rationale": rationale,
        "thresholds": {
            "min_closed_evals": MIN_CLOSED_EVALS,
            "min_positive_lift": MIN_POSITIVE_LIFT,
            "min_segment_share": MIN_SEGMENT_SHARE,
        },
        "overall_baseline": {
            "treated_conversion_rate": overall_treated_rate,
            "customers": int(customer["customer_unique_id"].nunique()),
            "closed_evaluations": len(evaluations),
        },
        "segment_summary": summary.to_dict(orient="records"),
        "tier_mix": tier_mix.to_dict(orient="records"),
        "candidate_customer_summary": {
            "retainable_share": retainable_share,
            "retainable_customers": int((customer["segment"] == "retainable").sum()),
            "structural_customers": int((customer["segment"] == "structural_single_purchase").sum()),
        },
        "top_retainable_examples": customer[customer["segment"] == "retainable"]
        .sort_values(["holdout_lift", "conversion_rate"], ascending=False)
        .head(10)[
            [
                "customer_unique_id",
                "dominant_tier",
                "closed_evaluations",
                "conversion_rate",
                "treated_conversion_rate",
                "holdout_conversion_rate",
                "holdout_lift",
                "avg_score",
            ]
        ]
        .to_dict(orient="records"),
    }


def _fmt_pct(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value) * 100:.2f}%"


def _fmt_float(value) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.4f}"


def render_benchmark_html(payload: dict) -> str:
    summary_rows = "".join(
        f"<tr><td>{row['segment'].replace('_', ' ').title()}</td><td>{int(row['customers'])}</td><td>{row['avg_closed_evaluations']:.1f}</td><td>{_fmt_pct(row['avg_conversion_rate'])}</td><td>{_fmt_pct(row['avg_treated_conversion_rate'])}</td><td>{_fmt_pct(row['avg_holdout_conversion_rate'])}</td><td>{_fmt_pct(row['avg_holdout_lift'])}</td><td>{_fmt_float(row['avg_score'])}</td></tr>"
        for row in payload["segment_summary"]
    )
    tier_rows = "".join(
        f"<tr><td>{row['segment'].replace('_', ' ').title()}</td><td><span class='tier tier-{str(row['dominant_tier']).lower()}'>{row['dominant_tier']}</span></td><td>{int(row['customers'])}</td></tr>"
        for row in payload["tier_mix"]
    )
    example_rows = "".join(
        f"<tr><td>{row['customer_unique_id']}</td><td><span class='tier tier-{str(row['dominant_tier']).lower()}'>{row['dominant_tier']}</span></td><td>{int(row['closed_evaluations'])}</td><td>{_fmt_pct(row['conversion_rate'])}</td><td>{_fmt_pct(row['holdout_lift'])}</td><td>{_fmt_float(row['avg_score'])}</td></tr>"
        for row in payload["top_retainable_examples"]
    )
    rationale = "".join(f"<li>{item}</li>" for item in payload["decision_rationale"])
    retainable = payload['candidate_customer_summary']['retainable_customers']
    structural = payload['candidate_customer_summary']['structural_customers']
    decision_title = payload['decision'].replace('_', ' ')
    return f"""<!DOCTYPE html>
<html lang='en'>
<head><meta charset='utf-8' /><title>Phase 4 Population Redesign Benchmark</title>
<style>
:root{{--bg:#f5f7fa;--surface:#ffffff;--surface-soft:#f8fafc;--text:#1f2937;--muted:#5b6472;--border:#d9e2ec;--brand:#005090;--high:#C01010;--medium:#E0B000;--low:#208040;--demo:#8a5a00;--demo-bg:#fff3cd;--decision:#eaf2fb;}} *{{box-sizing:border-box}} body{{font-family:Arial,sans-serif;background:var(--bg);color:var(--text);margin:0;line-height:1.45}} .wrap{{max-width:1240px;margin:0 auto;padding:28px 20px 40px}} .hero,.panel,.card{{background:var(--surface);border:1px solid var(--border);border-radius:16px;box-shadow:0 6px 16px rgba(15,23,42,.05)}} .hero{{padding:24px}} .hero-top{{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}} .brand{{display:flex;align-items:center;gap:14px}} .brand img{{height:44px;width:auto;border-radius:8px}} .eyebrow{{color:var(--brand);font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}} .hero h1,.panel h2{{margin:8px 0 10px}} .hero p,.panel p,.meta,li{{color:var(--muted)}} .pill,.tier{{display:inline-block;padding:7px 11px;border-radius:999px;font-size:12px;font-weight:700}} .pill{{background:var(--demo-bg);color:var(--demo)}} .tier-high{{background:#fdecec;color:var(--high)}} .tier-medium{{background:#fff7db;color:#8a6a00}} .tier-low{{background:#eaf7ef;color:var(--low)}} .summary{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:18px}} .callout{{background:var(--surface-soft);border:1px solid var(--border);border-radius:14px;padding:16px}} .decision{{background:var(--decision)}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-top:18px}} .card{{padding:16px}} .label{{color:var(--muted);font-size:13px}} .metric{{font-size:30px;font-weight:700;margin-top:8px;color:var(--brand)}} .panel{{padding:20px;margin-top:18px}} .section-kicker{{color:var(--brand);font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.08em}} table{{width:100%;border-collapse:collapse;margin-top:10px;background:var(--surface)}} th,td{{padding:11px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}} th{{color:var(--muted);background:var(--surface-soft)}} ul{{margin:10px 0 0 18px;padding:0}} .meta{{font-size:13px;margin-top:10px}} @media (max-width:860px){{.summary{{grid-template-columns:1fr}}}}
</style></head>
<body><div class='wrap'>
<div class='hero'>
  <div class='hero-top'>
    <div class='brand'>
      <img src='../assets/images/logo.gif' alt='VivaMarket logo' />
      <div>
        <div class='eyebrow'>Phase 4 benchmark surface</div>
        <h1>Phase 4 Population Redesign Benchmark</h1>
        <p>Decision benchmark for the retainable-vs-structurally-single-purchase redesign hypothesis using the current portfolio evidence layer.</p>
      </div>
    </div>
    <div>
      <div class='meta'>Run date: {payload['run_date']} · Baseline: canonical V2C</div>
    </div>
  </div>
  <div class='summary'>
    <div class='callout'>
      <div class='section-kicker'>Executive summary</div>
      <p><strong>What this means:</strong> the benchmark supports a credible redesign hypothesis, but it does not by itself authorize a production retraining claim.</p>
      <p><strong>Caveat:</strong> this benchmark supports portfolio reasoning and roadmap prioritization, not a live causal-superiority claim.</p>
    </div>
    <div class='callout decision'>
      <div class='section-kicker'>Decision implication</div>
      <p><strong>Decision:</strong> {decision_title}</p>
      <p class='meta'>Use this view to judge whether the retainable segment is strong enough to justify a later explicit redesign workstream.</p>
    </div>
  </div>
  <div class='grid'>
    <div class='card'><div class='label'>Customers benchmarked</div><div class='metric'>{payload['overall_baseline']['customers']:,}</div></div>
    <div class='card'><div class='label'>Closed evaluations</div><div class='metric'>{payload['overall_baseline']['closed_evaluations']:,}</div></div>
    <div class='card'><div class='label'>Retainable customers</div><div class='metric'>{retainable:,}</div></div>
    <div class='card'><div class='label'>Structural customers</div><div class='metric'>{structural:,}</div></div>
  </div>
</div>
<div class='panel'><div class='section-kicker'>Primary comparison</div><h2>Segment summary</h2><p>Compares the candidate retainable population against the structurally single-purchase segment on evaluation depth, conversion behavior, and holdout-relative signal.</p><table><thead><tr><th>Segment</th><th>Customers</th><th>Avg closed evals</th><th>Avg conversion rate</th><th>Avg treated CR</th><th>Avg holdout CR</th><th>Avg holdout lift</th><th>Avg score</th></tr></thead><tbody>{summary_rows}</tbody></table></div>
<div class='panel'><div class='section-kicker'>Behavioral composition</div><h2>Tier mix by segment</h2><p>Shows whether the redesign candidate is concentrated in stronger operational tiers or mostly reflects lower-value baseline behavior.</p><table><thead><tr><th>Segment</th><th>Dominant tier</th><th>Customers</th></tr></thead><tbody>{tier_rows}</tbody></table></div>
<div class='panel'><div class='section-kicker'>Illustrative examples</div><h2>Top retainable examples</h2><p>Representative customers from the strongest candidate segment, shown for interpretability rather than for direct production targeting.</p><table><thead><tr><th>Customer</th><th>Tier</th><th>Closed evals</th><th>Conversion rate</th><th>Holdout lift</th><th>Avg score</th></tr></thead><tbody>{example_rows}</tbody></table></div>
<div class='panel'><div class='section-kicker'>Decision output</div><h2>Decision rationale</h2><ul>{rationale}</ul></div>
</div></body></html>"""


def render_decision_md(payload: dict) -> str:
    summary_rows = "\n".join(
        f"| {row['segment']} | {int(row['customers'])} | {row['avg_closed_evaluations']:.1f} | {row['avg_conversion_rate']:.4f} | {row['avg_treated_conversion_rate']:.4f} | {row['avg_holdout_conversion_rate']:.4f} | {row['avg_holdout_lift']:.4f} | {row['avg_score']:.4f} |"
        for row in payload["segment_summary"]
    )
    rationale = "\n".join(f"- {item}" for item in payload["decision_rationale"])
    return f"""# Phase 4 Population Redesign Decision — 2026-05-31

**Measurement scope:** {payload['measurement_label']}

## Decision
`{payload['decision']}`

## Benchmark summary
| Segment | Customers | Avg closed evals | Avg conversion rate | Avg treated CR | Avg holdout CR | Avg holdout lift | Avg score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
{summary_rows}

## Rationale
{rationale}

## Interpretation
- This benchmark uses the current portfolio evidence layer rather than live production telemetry.
- It is therefore valid for portfolio/demo decision-making, but not for claiming live causal superiority in production.
- The V2C baseline remains the permanent reference point.

## Next recommended action
- If the redesign candidate is only marginally better, keep V2C as the canonical public baseline and document the population problem as real but not yet decisively solved.
- If the redesign candidate is materially stronger, use this note as the basis for a later `v4.0.0` redesign workstream with explicit retraining scope.
"""


def write_outputs(payload: dict) -> None:
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    OUTPUT_HTML.write_text(render_benchmark_html(payload), encoding="utf-8")
    OUTPUT_MD.write_text(render_decision_md(payload), encoding="utf-8")


def main() -> None:
    payload = build_population_benchmark_payload()
    write_outputs(payload)
    logger.info("phase4_population_redesign_benchmark=%s", json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
