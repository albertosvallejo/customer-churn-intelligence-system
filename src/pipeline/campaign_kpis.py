import html
import json
import logging
import os
from datetime import timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_DB_URL = os.getenv("CHURN_DB_URL", f"sqlite:///{PROJECT_ROOT / 'data' / 'raw' / 'churn_sqlite_db.sqlite'}")
DEFAULT_WINDOWS = {"HIGH": 14, "MEDIUM": 21, "LOW": 30}


def _resolve_windows() -> dict[str, int]:
    windows = DEFAULT_WINDOWS.copy()
    for tier, env_name in {
        "HIGH": "CONVERSION_WINDOW_DAYS_HIGH",
        "MEDIUM": "CONVERSION_WINDOW_DAYS_MEDIUM",
        "LOW": "CONVERSION_WINDOW_DAYS_LOW",
    }.items():
        raw = os.getenv(env_name)
        if raw is not None:
            windows[tier] = int(raw)
    return windows


def _standardize_actions(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "action_id",
                "customer_unique_id",
                "run_id",
                "model_version",
                "risk_tier",
                "channel",
                "executed_at",
                "holdout",
                "campaign_cycle",
                "window_days",
            ]
        )

    prepared = df.copy()
    rename_map = {
        "id": "action_id",
        "risk_tier": "risk_tier",
        "tier": "risk_tier",
        "executed_at": "executed_at",
        "action_ts": "executed_at",
        "holdout_window_days": "window_days",
        "attr_window_days": "window_days",
    }
    prepared = prepared.rename(columns=rename_map)

    if "action_id" not in prepared.columns:
        raise ValueError("actions data must include action_id or id")
    if "customer_unique_id" not in prepared.columns:
        raise ValueError("actions data must include customer_unique_id")
    if "risk_tier" not in prepared.columns:
        raise ValueError("actions data must include risk_tier or tier")
    if "executed_at" not in prepared.columns:
        raise ValueError("actions data must include executed_at or action_ts")

    if "run_id" not in prepared.columns:
        prepared["run_id"] = None
    if "model_version" not in prepared.columns:
        prepared["model_version"] = None
    if "channel" not in prepared.columns:
        prepared["channel"] = None
    if "campaign_cycle" not in prepared.columns:
        prepared["campaign_cycle"] = None
    if "holdout" not in prepared.columns:
        prepared["holdout"] = False
    if "window_days" not in prepared.columns:
        prepared["window_days"] = pd.NA

    prepared["risk_tier"] = prepared["risk_tier"].fillna("MEDIUM").astype(str).str.upper()
    prepared["executed_at"] = pd.to_datetime(prepared["executed_at"], errors="coerce", utc=True)
    prepared["holdout"] = prepared["holdout"].fillna(False).astype(bool)
    prepared = prepared.dropna(subset=["executed_at"]).copy()
    return prepared[
        [
            "action_id",
            "customer_unique_id",
            "run_id",
            "model_version",
            "risk_tier",
            "channel",
            "executed_at",
            "holdout",
            "campaign_cycle",
            "window_days",
        ]
    ].drop_duplicates(subset=["action_id"])


def _standardize_events(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["action_id", "customer_unique_id", "event_type", "event_ts", "campaign_cycle"])
    prepared = df.copy()
    if "action_id" not in prepared.columns:
        prepared["action_id"] = None
    if "customer_unique_id" not in prepared.columns:
        raise ValueError("events data must include customer_unique_id")
    if "event_type" not in prepared.columns or "event_ts" not in prepared.columns:
        raise ValueError("events data must include event_type and event_ts")
    if "campaign_cycle" not in prepared.columns:
        prepared["campaign_cycle"] = None
    prepared["event_type"] = prepared["event_type"].astype(str).str.lower()
    prepared["event_ts"] = pd.to_datetime(prepared["event_ts"], errors="coerce", utc=True)
    prepared = prepared.dropna(subset=["event_ts"]).copy()
    return prepared[["action_id", "customer_unique_id", "event_type", "event_ts", "campaign_cycle"]]


def _load_actions(engine=None, parquet_path: Path | None = None) -> pd.DataFrame:
    if parquet_path is not None:
        return _standardize_actions(pd.read_parquet(parquet_path))
    query = text(
        """
        SELECT
            id,
            customer_unique_id,
            run_id,
            NULL AS model_version,
            risk_tier,
            channel,
            executed_at,
            holdout,
            campaign_cycle,
            holdout_window_days
        FROM retention_actions
        WHERE executed_at IS NOT NULL
        """
    )
    with engine.connect() as conn:
        return _standardize_actions(pd.read_sql(query, conn))


def _load_events(engine=None, parquet_path: Path | None = None) -> pd.DataFrame:
    if parquet_path is not None:
        return _standardize_events(pd.read_parquet(parquet_path))
    query = text(
        """
        SELECT
            NULL AS action_id,
            customer_unique_id,
            event_type,
            event_ts,
            NULL AS campaign_cycle
        FROM retention_events
        """
    )
    with engine.connect() as conn:
        return _standardize_events(pd.read_sql(query, conn))


def build_closed_evaluation_frame(
    engine=None,
    as_of: str | None = None,
    actions_parquet_path: Path | None = None,
    events_parquet_path: Path | None = None,
) -> pd.DataFrame:
    windows = _resolve_windows()
    actions = _load_actions(engine=engine, parquet_path=actions_parquet_path)
    if actions.empty:
        return pd.DataFrame()

    invalid_tiers = sorted(set(actions["risk_tier"]) - set(windows))
    if invalid_tiers:
        raise ValueError(f"Unsupported risk_tier values found in actions data: {invalid_tiers}")

    actions = actions.copy()
    actions["window_days"] = actions["window_days"].where(actions["window_days"].notna(), actions["risk_tier"].map(windows))
    actions["window_days"] = actions["window_days"].astype(int)
    actions["window_end"] = actions["executed_at"] + pd.to_timedelta(actions["window_days"], unit="D")

    as_of_ts = pd.Timestamp.now(tz=timezone.utc) if as_of is None else pd.Timestamp(as_of, tz="UTC")
    actions["closed_evaluation"] = actions["window_end"] <= as_of_ts

    events = _load_events(engine=engine, parquet_path=events_parquet_path)
    if events.empty:
        actions["converted"] = False
        return actions

    conversion_events = events[events["event_type"].isin(["converted", "purchase", "coupon_used"])].copy()
    if conversion_events.empty:
        actions["converted"] = False
        return actions

    if conversion_events["action_id"].notna().any():
        merged = actions.merge(conversion_events, on="action_id", how="left", suffixes=("", "_event"))
    else:
        merged = actions.merge(conversion_events, on=["customer_unique_id"], how="left", suffixes=("", "_event"))

    within_window = (
        merged["event_ts"].notna()
        & (merged["event_ts"] >= merged["executed_at"])
        & (merged["event_ts"] <= merged["window_end"])
    )
    converted = merged.loc[within_window, ["action_id"]].drop_duplicates()
    actions["converted"] = actions["action_id"].isin(converted["action_id"])
    return actions


def summarize_campaign_kpis(
    engine=None,
    as_of: str | None = None,
    actions_parquet_path: Path | None = None,
    events_parquet_path: Path | None = None,
) -> dict:
    frame = build_closed_evaluation_frame(
        engine=engine,
        as_of=as_of,
        actions_parquet_path=actions_parquet_path,
        events_parquet_path=events_parquet_path,
    )
    if frame.empty:
        return {
            "as_of": as_of,
            "summary": [],
            "totals": {"actions": 0, "closed_evaluations": 0},
            "label": "Simulated campaign baseline · pre-holdout internal monitor",
        }

    closed = frame[frame["closed_evaluation"]].copy()
    grouped = []
    if not closed.empty:
        agg = (
            closed.groupby(["risk_tier", "window_days", "holdout"], dropna=False)
            .agg(
                closed_evaluations=("action_id", "count"),
                conversions=("converted", "sum"),
            )
            .reset_index()
        )
        agg["conversion_rate"] = agg["conversions"] / agg["closed_evaluations"]
        grouped = agg.to_dict(orient="records")

    totals = {
        "actions": len(frame),
        "closed_evaluations": int(frame["closed_evaluation"].sum()),
        "treated_closed_evaluations": int((closed["holdout"] == False).sum()) if not closed.empty else 0,
        "holdout_closed_evaluations": int((closed["holdout"] == True).sum()) if not closed.empty else 0,
    }

    holdout_lift = []
    if grouped:
        grouped_df = pd.DataFrame(grouped)
        for tier in sorted(grouped_df["risk_tier"].unique()):
            tier_df = grouped_df[grouped_df["risk_tier"] == tier]
            treated = tier_df[tier_df["holdout"] == False]
            holdout = tier_df[tier_df["holdout"] == True]
            if treated.empty or holdout.empty:
                continue
            holdout_lift.append(
                {
                    "risk_tier": tier,
                    "attr_window_days": int(treated.iloc[0]["window_days"]),
                    "treated_conversion_rate": float(treated.iloc[0]["conversion_rate"]),
                    "holdout_conversion_rate": float(holdout.iloc[0]["conversion_rate"]),
                    "holdout_lift": float(treated.iloc[0]["conversion_rate"] - holdout.iloc[0]["conversion_rate"]),
                }
            )

    return {
        "as_of": as_of or pd.Timestamp.now(tz=timezone.utc).isoformat(),
        "summary": grouped,
        "holdout_lift": holdout_lift,
        "totals": totals,
        "label": "Simulated campaign baseline · pre-holdout internal monitor",
    }


def render_campaign_kpi_report(payload: dict) -> str:
    as_of = html.escape(str(payload.get("as_of", "—")))
    label = html.escape(str(payload.get("label", "")))
    totals = payload.get("totals", {})
    summary_rows = payload.get("summary", [])
    holdout_rows = payload.get("holdout_lift", [])

    def _fmt_pct(value) -> str:
        if value is None or pd.isna(value):
            return "—"
        return f"{float(value) * 100:.1f}%"

    def _fmt_int(value) -> str:
        if value is None or pd.isna(value):
            return "0"
        return f"{int(value):,}"

    summary_html = "".join(
        "".join(
            [
                "<tr>",
                f"<td>{html.escape(str(row.get('risk_tier', '—')))}</td>",
                f"<td>{_fmt_int(row.get('window_days'))}</td>",
                f"<td>{'Holdout' if bool(row.get('holdout')) else 'Treated'}</td>",
                f"<td>{_fmt_int(row.get('closed_evaluations'))}</td>",
                f"<td>{_fmt_int(row.get('conversions'))}</td>",
                f"<td>{_fmt_pct(row.get('conversion_rate'))}</td>",
                "</tr>",
            ]
        )
        for row in summary_rows
    ) or '<tr><td colspan="6">No closed evaluations available yet.</td></tr>'

    holdout_html = "".join(
        "".join(
            [
                "<tr>",
                f"<td>{html.escape(str(row.get('risk_tier', '—')))}</td>",
                f"<td>{_fmt_int(row.get('attr_window_days'))}</td>",
                f"<td>{_fmt_pct(row.get('treated_conversion_rate'))}</td>",
                f"<td>{_fmt_pct(row.get('holdout_conversion_rate'))}</td>",
                f"<td>{_fmt_pct(row.get('holdout_lift'))}</td>",
                "</tr>",
            ]
        )
        for row in holdout_rows
    ) or '<tr><td colspan="5">Holdout lift is not available for all tiers yet.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Phase 4 Campaign KPI Monitor</title>
  <style>
    :root {{ --bg:#f5f7fa; --surface:#ffffff; --surface-soft:#f8fafc; --text:#1f2937; --muted:#5b6472; --brand:#005090; --accent:#1f7a3d; --warning:#8a5a00; --warning-bg:#fff3cd; --border:#d9e2ec; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, sans-serif; background: var(--bg); color: var(--text); }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 32px 20px 48px; }}
    .hero, .card, table {{ background: var(--surface); border: 1px solid var(--border); border-radius: 16px; box-shadow: 0 6px 16px rgba(15, 23, 42, 0.05); }}
    .hero {{ margin-bottom: 24px; padding: 24px; }}
    .hero-top {{ display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; }}
    .brand {{ display:flex; align-items:center; gap:14px; }}
    .brand img {{ height:44px; width:auto; border-radius:8px; }}
    .eyebrow {{ color: var(--brand); text-transform: uppercase; letter-spacing: .08em; font-size: 12px; font-weight: 700; }}
    h1 {{ margin: 8px 0 10px; font-size: 32px; }}
    .sub {{ color: var(--muted); max-width: 880px; line-height: 1.5; }}
    .label {{ display: inline-block; margin-top: 12px; padding: 8px 12px; border-radius: 999px; background: var(--warning-bg); color: var(--warning); font-size: 13px; font-weight:700; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; margin: 24px 0 28px; }}
    .card {{ padding: 18px; }}
    .card h2 {{ margin: 0 0 8px; font-size: 14px; color: var(--muted); font-weight: 600; }}
    .metric {{ font-size: 34px; font-weight: 700; }}
    .hint {{ margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.4; }}
    section {{ margin-top: 24px; }}
    section h3 {{ margin-bottom: 8px; font-size: 20px; }}
    section p {{ color: var(--muted); line-height: 1.5; }}
    table {{ width: 100%; border-collapse: collapse; overflow: hidden; }}
    th, td {{ padding: 12px 14px; border-bottom: 1px solid var(--border); text-align: left; font-size: 14px; }}
    th {{ color: var(--muted); font-weight: 600; background: var(--surface-soft); }}
    tr:last-child td {{ border-bottom: none; }}
    .footer {{ margin-top: 28px; color: var(--muted); font-size: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="hero-top">
        <div class="brand">
          <img src="../assets/images/logo.gif" alt="VivaMarket logo" />
          <div>
            <div class="eyebrow">Phase 4 · Internal KPI monitor</div>
            <h1>Campaign KPI Monitor</h1>
            <div class="sub">Internal technical monitoring view for closed conversion evaluation, attribution-window completeness, and early holdout interpretation.</div>
          </div>
        </div>
        <div class="label">{label}</div>
      </div>
    </div>

    <div class="grid">
      <div class="card"><h2>Total actions observed</h2><div class="metric">{_fmt_int(totals.get('actions'))}</div><div class="hint">All retention actions included in the current evaluation frame.</div></div>
      <div class="card"><h2>Closed evaluations</h2><div class="metric">{_fmt_int(totals.get('closed_evaluations'))}</div><div class="hint">Actions whose full attribution window has already elapsed.</div></div>
      <div class="card"><h2>Treated closed</h2><div class="metric">{_fmt_int(totals.get('treated_closed_evaluations'))}</div><div class="hint">Observed treated rows available for conversion-rate reading.</div></div>
      <div class="card"><h2>Holdout closed</h2><div class="metric">{_fmt_int(totals.get('holdout_closed_evaluations'))}</div><div class="hint">Observed holdout rows available for early lift comparison.</div></div>
    </div>

    <section>
      <h3>Conversion summary by tier and cohort</h3>
      <p>Use this table to compare treated versus holdout conversion rates only after the attribution window closes. Tier-specific windows remain explicit to avoid denominator drift.</p>
      <table><thead><tr><th>Risk tier</th><th>Window (days)</th><th>Cohort</th><th>Closed evaluations</th><th>Conversions</th><th>Conversion rate</th></tr></thead><tbody>{summary_html}</tbody></table>
    </section>

    <section>
      <h3>Early holdout lift view</h3>
      <p>Positive lift means treated customers converted more often than holdout customers within the same tier-specific window. Use this view as an internal monitor, not as a stakeholder-facing performance claim.</p>
      <table><thead><tr><th>Risk tier</th><th>Window (days)</th><th>Treated conversion rate</th><th>Holdout conversion rate</th><th>Lift</th></tr></thead><tbody>{holdout_html}</tbody></table>
    </section>

    <div class="footer">Run timestamp: {as_of} · Audience: internal technical review · Honesty marker: simulated or pre-production KPI evidence must remain clearly labeled until the live holdout gate is formally closed.</div>
  </div>
</body>
</html>
"""


def write_campaign_kpi_report(payload: dict, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_campaign_kpi_report(payload), encoding="utf-8")
    return output_path


def main() -> None:
    synthetic_actions = DATA_PROCESSED_DIR / "retention_actions_synthetic_30d.parquet"
    synthetic_events = DATA_PROCESSED_DIR / "retention_events_synthetic_30d.parquet"
    if synthetic_actions.exists() and synthetic_events.exists():
        payload = summarize_campaign_kpis(
            as_of=None,
            actions_parquet_path=synthetic_actions,
            events_parquet_path=synthetic_events,
        )
    else:
        engine = create_engine(DEFAULT_DB_URL)
        payload = summarize_campaign_kpis(engine=engine)
    report_path = write_campaign_kpi_report(payload, REPORTS_DIR / "phase4_campaign_kpi_monitor_latest.html")
    logger.info(json.dumps(payload, ensure_ascii=False))
    logger.info("campaign_kpi_report_written=%s", report_path)


if __name__ == "__main__":
    main()
