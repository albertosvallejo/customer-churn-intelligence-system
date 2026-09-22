import json
import logging
import os
import secrets
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import create_engine, text

from evidence.phase6_integration import (
    build_action_proposals,
    build_kpi_status_view,
    build_n8n_action_payload,
    launch_ab_test,
    load_action_history,
    load_action_proposals,
    load_latest_kpi_status,
    load_latest_n8n_action_payload,
    record_action_decision,
)
from evidence.phase7_integration import (
    build_integrated_actions,
    build_phase7_kpi_status_view,
    build_phase7_n8n_payload,
    build_phase7_post_test_decision_queue,
    build_phase7_stat_summary,
    create_phase7_stat_launch_request,
    execute_phase7_stat_launch_request,
    load_integrated_actions,
    load_phase7_action_history,
    load_phase7_launch_requests,
    load_latest_phase7_kpi_status,
    load_latest_phase7_n8n_payload,
    load_phase7_stat_test_runs,
    record_phase7_action_decision,
    record_phase7_post_test_decision,
)

logger = logging.getLogger(__name__)

def _resolve_project_root() -> Path:
    env_value = str(os.getenv("PROJECT_ROOT") or "").strip()
    candidates: list[Path] = []
    if env_value:
        candidates.append(Path(env_value).expanduser())
    candidates.append(Path(__file__).resolve().parents[2])

    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        processed_dir = resolved / "data" / "processed"
        src_dir = resolved / "src"
        if processed_dir.exists() and src_dir.exists():
            return resolved

    return candidates[-1].resolve(strict=False)


PROJECT_ROOT = _resolve_project_root()
DATA_PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
MODELS_DIR = PROJECT_ROOT / "models"
COUPON_REGISTRY_PATH = DATA_PROCESSED_DIR / "generated_coupons.jsonl"
COUPON_LOCK = threading.Lock()
COUPON_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
VALID_RISK_LEVELS = {"HIGH", "MEDIUM", "LOW"}
DEFAULT_HOST = os.getenv("CHURN_API_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.getenv("CHURN_API_PORT", "62880"))
DEFAULT_DB_URL = os.getenv("CHURN_DB_URL", f"sqlite:///{PROJECT_ROOT / 'data' / 'raw' / 'churn_sqlite_db.sqlite'}")
PINNED_SCORING_BUNDLE = os.getenv("CHURN_SCORING_BUNDLE")
GOVERNANCE_MONITOR_PATH = DATA_PROCESSED_DIR / "phase4_governance_monitor_latest.json"
SYNTHETIC_ACTIONS_PATH = DATA_PROCESSED_DIR / "retention_actions_synthetic_30d.parquet"
SYNTHETIC_DEMO_MANIFEST_PATH = PROJECT_ROOT / "data" / "synthetic_demo" / "synthetic_demo__phase7_manifest_20260727.json"


def _is_synthetic_demo_mode() -> bool:
    return str(os.getenv("MODE") or "").strip().lower() == "synthetic_demo"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime)):
        if getattr(value, "tzinfo", None) is None:
            return value.isoformat()
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, tuple):
        return list(value)
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes, bytearray)):
        converted = value.tolist()
        return converted
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _latest_explainability_path() -> Path:
    matches = sorted(DATA_PROCESSED_DIR.glob("churn_explainability_*.parquet"))
    if not matches:
        raise FileNotFoundError("No explainability parquet file found")
    return matches[-1]


@lru_cache(maxsize=1)
def _ops_engine():
    return create_engine(DEFAULT_DB_URL)


def _ensure_retention_events_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS retention_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_unique_id TEXT NOT NULL,
        run_date_tag TEXT NOT NULL,
        offer_code_stub TEXT,
        channel TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_ts TIMESTAMP NOT NULL,
        provider_message_id TEXT,
        coupon_redeemed BOOLEAN DEFAULT FALSE,
        order_id TEXT,
        order_value_brl REAL,
        metadata TEXT
    );
    """
    dedup = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_retention_events_provider_event
      ON retention_events (provider_message_id, event_type, event_ts);
    """
    engine = _ops_engine()
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text(dedup))


def _ensure_agent_decision_log_table() -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS agent_decision_log (
        id TEXT PRIMARY KEY,
        decision_ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        decision_type TEXT NOT NULL,
        input_snapshot TEXT,
        agent_decision TEXT NOT NULL,
        human_decision TEXT,
        match BOOLEAN,
        rationale TEXT,
        shadow_mode BOOLEAN NOT NULL DEFAULT TRUE,
        cycle_date DATE NOT NULL
    );
    """
    idx_cycle_date = """
    CREATE INDEX IF NOT EXISTS idx_adl_cycle_date
      ON agent_decision_log (cycle_date);
    """
    idx_decision_type = """
    CREATE INDEX IF NOT EXISTS idx_adl_decision_type
      ON agent_decision_log (decision_type);
    """
    engine = _ops_engine()
    with engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text(idx_cycle_date))
        conn.execute(text(idx_decision_type))


def _verify_shadow_decision_cycle(cycle_date: str) -> dict[str, Any]:
    try:
        normalized_cycle_date = pd.to_datetime(cycle_date).strftime("%Y-%m-%d")
    except Exception as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc

    _ensure_agent_decision_log_table()
    with _ops_engine().connect() as conn:
        row = conn.exec_driver_sql(
            "SELECT cycle_date, COUNT(*) FROM agent_decision_log WHERE cycle_date = ? GROUP BY cycle_date",
            (normalized_cycle_date,),
        ).fetchone()

    confirmed_count = int(row[1] if row else 0)
    return {
        "cycle_date": normalized_cycle_date,
        "count": confirmed_count,
        "confirmed": confirmed_count >= 1,
    }


def _get_governance_config_map() -> dict[str, str]:
    engine = _ops_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS retention_governance_config (
                    config_key TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
        )
        rows = conn.execute(text("SELECT config_key, config_value FROM retention_governance_config")).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _event_insert_sql() -> str:
    engine = _ops_engine()
    prefix = "INSERT OR IGNORE" if engine.dialect.name == "sqlite" else "INSERT"
    suffix = "" if engine.dialect.name == "sqlite" else " ON CONFLICT DO NOTHING"
    return (
        f"""
        {prefix} INTO retention_events (
            customer_unique_id,
            run_date_tag,
            offer_code_stub,
            channel,
            event_type,
            event_ts,
            provider_message_id,
            coupon_redeemed,
            order_id,
            order_value_brl,
            metadata
        ) VALUES (
            :customer_unique_id,
            :run_date_tag,
            :offer_code_stub,
            :channel,
            :event_type,
            :event_ts,
            :provider_message_id,
            :coupon_redeemed,
            :order_id,
            :order_value_brl,
            :metadata
        ){suffix}
        """
    )


def _coerce_onesignal_events(payload: dict) -> list[dict]:
    events = payload.get("events")
    if events is None and payload.get("event"):
        events = [payload]
    if not isinstance(events, list) or not events:
        raise ValueError("events must be a non-empty list")
    return events


def _normalize_onesignal_event(event: dict) -> dict:
    if not isinstance(event, dict):
        raise ValueError("each event must be an object")

    customer_unique_id = str(
        event.get("external_user_id")
        or event.get("customer_unique_id")
        or event.get("external_id")
        or ""
    ).strip()
    run_date_tag = str(event.get("run_date_tag") or _latest_scoring_metadata()["run_date_tag"]).strip()
    event_type = str(event.get("event") or event.get("event_type") or "").strip().lower()
    event_ts = event.get("event_time") or event.get("occurred_at") or event.get("timestamp")
    provider_message_id = str(
        event.get("notification_id") or event.get("id") or event.get("provider_message_id") or ""
    ).strip()

    if not customer_unique_id:
        raise ValueError("external_user_id or customer_unique_id is required")
    if not event_type:
        raise ValueError("event type is required")
    if not event_ts:
        raise ValueError("event_time or timestamp is required")

    try:
        normalized_ts = pd.to_datetime(event_ts, utc=True)
    except Exception as exc:  # pragma: no cover
        raise ValueError("event timestamp is invalid") from exc
    if pd.isna(normalized_ts):
        raise ValueError("event timestamp is invalid")

    return {
        "customer_unique_id": customer_unique_id,
        "run_date_tag": run_date_tag,
        "offer_code_stub": None,
        "channel": "push",
        "event_type": event_type,
        "event_ts": normalized_ts.strftime("%Y-%m-%d %H:%M:%S"),
        "provider_message_id": provider_message_id or None,
        "coupon_redeemed": False,
        "order_id": None,
        "order_value_brl": None,
        "metadata": json.dumps(event, ensure_ascii=False),
    }


def _ingest_onesignal_events(payload: dict) -> dict:
    events = _coerce_onesignal_events(payload)
    records = [_normalize_onesignal_event(event) for event in events]

    _ensure_retention_events_table()
    insert_sql = text(_event_insert_sql())
    inserted = 0
    with _ops_engine().begin() as conn:
        for record in records:
            result = conn.execute(insert_sql, record)
            inserted += result.rowcount or 0

    return {
        "status": "ok",
        "received": len(records),
        "inserted": inserted,
        "duplicates": len(records) - inserted,
        "timestamp": _utc_now_iso(),
    }


def _create_shadow_decision(payload: dict, refresh_artifacts: bool = False, refresh_trigger: str = "shadow_create") -> dict:
    _ensure_agent_decision_log_table()

    decision_type = str(payload.get("decision_type") or "").strip()
    agent_decision = str(payload.get("agent_decision") or "").strip()
    rationale = str(payload.get("rationale") or "").strip()
    cycle_date = str(payload.get("cycle_date") or "").strip()
    human_decision = payload.get("human_decision")
    match = payload.get("match")
    input_snapshot = payload.get("input_snapshot")

    if not decision_type:
        raise ValueError("decision_type is required")
    if not agent_decision:
        raise ValueError("agent_decision is required")
    if not rationale:
        raise ValueError("rationale is required")
    if not cycle_date:
        raise ValueError("cycle_date is required")

    normalized_cycle_date = pd.to_datetime(cycle_date, errors="raise").date().isoformat()

    if human_decision is not None:
        human_decision = str(human_decision).strip() or None
    if match is not None and not isinstance(match, bool):
        raise ValueError("match must be boolean when provided")

    record = {
        "id": str(uuid.uuid4()),
        "decision_type": decision_type,
        "input_snapshot": json.dumps(input_snapshot, ensure_ascii=False) if input_snapshot is not None else None,
        "agent_decision": agent_decision,
        "human_decision": human_decision,
        "match": match,
        "rationale": rationale,
        "shadow_mode": True,
        "cycle_date": normalized_cycle_date,
    }

    insert_sql = text(
        """
        INSERT INTO agent_decision_log (
            id,
            decision_type,
            input_snapshot,
            agent_decision,
            human_decision,
            match,
            rationale,
            shadow_mode,
            cycle_date
        ) VALUES (
            :id,
            :decision_type,
            :input_snapshot,
            :agent_decision,
            :human_decision,
            :match,
            :rationale,
            :shadow_mode,
            :cycle_date
        )
        """
    )
    with _ops_engine().begin() as conn:
        conn.execute(insert_sql, record)

    response = {
        "status": "ok",
        "decision_log_table": "agent_decision_log",
        "shadow_mode": True,
        "record_id": record["id"],
        "decision_type": record["decision_type"],
        "agent_decision": record["agent_decision"],
        "cycle_date": record["cycle_date"],
        "timestamp": _utc_now_iso(),
    }
    if refresh_artifacts:
        response["monitor_refresh"] = _refresh_shadow_monitor_artifacts(
            trigger=refresh_trigger,
            cycle_date=record["cycle_date"],
            record_id=record["id"],
        )
    return response


def _resolve_scoring_bundle_path() -> Path | None:
    if PINNED_SCORING_BUNDLE:
        pinned_path = Path(PINNED_SCORING_BUNDLE)
        if not pinned_path.is_absolute():
            pinned_path = MODELS_DIR / pinned_path
        if not pinned_path.exists():
            raise FileNotFoundError(f"Pinned scoring bundle not found: {pinned_path}")
        return pinned_path

    bundle_paths = sorted(MODELS_DIR.glob("churn_scoring_package_*.joblib"), reverse=True)
    return bundle_paths[0] if bundle_paths else None


@lru_cache(maxsize=1)
def _latest_scoring_metadata() -> dict:
    bundle_path = _resolve_scoring_bundle_path()
    if bundle_path is None:
        if _is_synthetic_demo_mode() and SYNTHETIC_DEMO_MANIFEST_PATH.exists():
            with SYNTHETIC_DEMO_MANIFEST_PATH.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
            run_date_tag = str(manifest.get("run_date") or "20260727")
            return {
                "run_id": f"synthetic_demo_{run_date_tag}",
                "run_date_tag": run_date_tag,
                "model_version": str(manifest.get("bundle_version") or "synthetic_demo"),
                "pipeline_tag": str(manifest.get("manifest_version") or "synthetic_demo"),
                "source_file": SYNTHETIC_DEMO_MANIFEST_PATH.name,
                "risk_thresholds": None,
            }
        explainability_path = _latest_explainability_path()
        fallback_tag = explainability_path.stem.split("_")[-1]
        return {
            "run_id": f"canonical_v2c_{fallback_tag}",
            "run_date_tag": fallback_tag,
            "model_version": "unknown",
            "pipeline_tag": "unknown",
            "source_file": explainability_path.name,
            "risk_thresholds": None,
        }

    bundle = joblib.load(bundle_path)
    metadata = bundle.get("metadata", {}) if isinstance(bundle, dict) else {}
    run_date_tag = metadata.get("run_date_tag", bundle_path.stem.split("_")[-1])
    return {
        "run_id": metadata.get("run_id", f"canonical_v2c_{run_date_tag}"),
        "run_date_tag": run_date_tag,
        "model_version": metadata.get("model_version", metadata.get("version_name", "unknown")),
        "pipeline_tag": metadata.get("pipeline_tag", "unknown"),
        "source_file": bundle_path.name,
        "risk_thresholds": metadata.get("risk_thresholds"),
    }


def _load_latest_explainability(customer_id: str | None = None, risk_level: str | None = None, limit: int | None = None) -> dict:
    path = _latest_explainability_path()
    df = pd.read_parquet(path)

    if "snapshot_date" in df.columns:
        snapshot_dates = pd.to_datetime(df["snapshot_date"], errors="coerce")
        latest_snapshot = snapshot_dates.max()
        if pd.notna(latest_snapshot):
            df = df.loc[snapshot_dates.eq(latest_snapshot)].copy()
        else:
            latest_snapshot = None
    else:
        latest_snapshot = None

    if customer_id:
        df = df.loc[df["customer_unique_id"].astype(str) == str(customer_id)].copy()

    if risk_level:
        normalized = str(risk_level).upper()
        df = df.loc[df["risk_tier"].astype(str).str.upper() == normalized].copy()

    df = df.sort_values([c for c in ["churn_probability", "customer_unique_id"] if c in df.columns], ascending=[False, True][: len([c for c in ["churn_probability", "customer_unique_id"] if c in df.columns])])

    if limit is not None:
        df = df.head(limit).copy()

    records = df.to_dict(orient="records")
    return {
        "source_file": path.name,
        "latest_snapshot_date": _json_default(latest_snapshot) if latest_snapshot is not None else None,
        "record_count": len(records),
        "generated_at": _utc_now_iso(),
        "records": records,
    }


def _load_agent_status() -> dict:
    if not GOVERNANCE_MONITOR_PATH.exists():
        raise FileNotFoundError("Governance monitor JSON not found")

    with GOVERNANCE_MONITOR_PATH.open("r", encoding="utf-8") as handle:
        governance_payload = json.load(handle)

    synthetic_actions = pd.read_parquet(SYNTHETIC_ACTIONS_PATH) if SYNTHETIC_ACTIONS_PATH.exists() else pd.DataFrame()
    pending_human_decision_count = 0
    shadow_log_count = 0
    try:
        _ensure_agent_decision_log_table()
        with _ops_engine().connect() as conn:
            shadow_log_count = int(
                conn.execute(text("SELECT COUNT(*) FROM agent_decision_log WHERE shadow_mode = TRUE")).scalar_one()
            )
            pending_human_decision_count = int(
                conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM agent_decision_log
                        WHERE shadow_mode = TRUE
                          AND (human_decision IS NULL OR TRIM(human_decision) = '')
                        """
                    )
                ).scalar_one()
            )
    except Exception:
        logger.exception("Unable to derive agent decision log counts")
    latest_cycle = None
    recent_cycle_summary: list[dict[str, Any]] = []
    if not synthetic_actions.empty and "campaign_cycle" in synthetic_actions.columns:
        synthetic_actions = synthetic_actions.copy()
        synthetic_actions["campaign_cycle"] = pd.to_datetime(synthetic_actions["campaign_cycle"], errors="coerce")
        latest_cycle = synthetic_actions["campaign_cycle"].max()
        if pd.notna(latest_cycle):
            latest_cycle_df = synthetic_actions.loc[synthetic_actions["campaign_cycle"].eq(latest_cycle)].copy()
            if not latest_cycle_df.empty:
                grouped = (
                    latest_cycle_df.groupby("tier", dropna=False)
                    .agg(
                        customers=("customer_unique_id", "count"),
                        dispatched=("dispatched", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
                        holdout=("holdout", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
                    )
                    .reset_index()
                    .sort_values("tier")
                )
                recent_cycle_summary = grouped.to_dict(orient="records")

    feature_drift = governance_payload.get("feature_drift", [])
    score_drift = governance_payload.get("score_drift", {})
    holdout_lift = governance_payload.get("kpi_payload", {}).get("holdout_lift", [])
    conversion_rates = governance_payload.get("kpi_payload", {}).get("summary", [])
    tier_distribution = governance_payload.get("tier_stability", [])
    trigger_thresholds = governance_payload.get("trigger_thresholds", {})

    anomalies: list[dict[str, Any]] = []
    active_triggers: list[str] = []

    for row in feature_drift:
        if row.get("triggered"):
            active_triggers.append(f"feature_drift:{row.get('feature')}")
            anomalies.append(
                {
                    "kind": "feature_drift",
                    "feature": row.get("feature"),
                    "ks_stat": row.get("ks_stat"),
                    "threshold": trigger_thresholds.get("feature_ks"),
                }
            )

    if score_drift.get("triggered"):
        active_triggers.append("score_mean_shift")
        anomalies.append(
            {
                "kind": "score_drift",
                "mean_shift": score_drift.get("mean_shift"),
                "threshold": trigger_thresholds.get("score_mean_shift"),
            }
        )

    high_share = governance_payload.get("totals", {}).get("current_high_share")
    high_share_threshold = trigger_thresholds.get("high_tier_share")
    if high_share is not None and high_share_threshold is not None and high_share > high_share_threshold:
        active_triggers.append("high_tier_share")
        anomalies.append(
            {
                "kind": "high_tier_share",
                "value": high_share,
                "threshold": high_share_threshold,
            }
        )

    negative_lifts = [row for row in holdout_lift if row.get("holdout_lift") is not None and row.get("holdout_lift") < 0]
    for row in negative_lifts:
        active_triggers.append(f"negative_holdout_lift:{row.get('risk_tier')}")
        anomalies.append(
            {
                "kind": "negative_holdout_lift",
                "risk_tier": row.get("risk_tier"),
                "holdout_lift": row.get("holdout_lift"),
                "threshold": trigger_thresholds.get("holdout_lift_below_zero"),
            }
        )

    agent_action_required = bool(active_triggers)
    recommended_decision = "escalation" if agent_action_required else "dispatch_confirm"
    governance_config = _get_governance_config_map()
    human_override = governance_config.get("HUMAN_OVERRIDE_STATE")
    blocklist_raw = governance_config.get("DISPATCH_BLOCKLIST_DATES", "")
    blocklist_dates = sorted({token.strip() for token in blocklist_raw.split(",") if token.strip()})

    return {
        "status": "ok",
        "timestamp": _utc_now_iso(),
        "shadow_mode": True,
        "decision_log_table": "agent_decision_log",
        "pending_human_decision_count": pending_human_decision_count,
        "shadow_log_count": shadow_log_count,
        "agent_action_required": agent_action_required,
        "recommended_decision_type": recommended_decision,
        "governance_run_date": governance_payload.get("run_date"),
        "measurement_label": governance_payload.get("measurement_label"),
        "scope_note": governance_payload.get("scope_note"),
        "model_snapshot": governance_payload.get("model_snapshot"),
        "drift": {
            "feature_drift": feature_drift,
            "score_drift": score_drift,
        },
        "tier_distribution": tier_distribution,
        "holdout_lift": holdout_lift,
        "conversion_rates": conversion_rates,
        "active_triggers": active_triggers,
        "d2_triggers_active": active_triggers,
        "anomalies": anomalies,
        "dispatch_anomalies": anomalies,
        "trigger_summary": governance_payload.get("trigger_summary", []),
        "trigger_thresholds": trigger_thresholds,
        "totals": governance_payload.get("totals", {}),
        "human_override": human_override,
        "dispatch_blocklist_dates": blocklist_dates,
        "latest_shadow_cycle": _json_default(latest_cycle) if latest_cycle is not None and pd.notna(latest_cycle) else None,
        "latest_shadow_cycle_summary": recent_cycle_summary,
        "sources": {
            "governance_monitor": GOVERNANCE_MONITOR_PATH.name,
            "synthetic_actions": SYNTHETIC_ACTIONS_PATH.name if SYNTHETIC_ACTIONS_PATH.exists() else None,
        },
    }


def _derive_shadow_decision(status_payload: dict, cycle_date: str) -> dict:
    normalized_cycle_date = pd.to_datetime(cycle_date, errors="raise").date().isoformat()
    active_triggers = [str(item) for item in status_payload.get("d2_triggers_active", [])]
    anomalies = status_payload.get("dispatch_anomalies", [])
    human_override = str(status_payload.get("human_override") or "").strip()
    blocklist_dates = {str(item) for item in status_payload.get("dispatch_blocklist_dates", [])}
    high_share = status_payload.get("totals", {}).get("current_high_share")
    high_share_threshold = status_payload.get("trigger_thresholds", {}).get("high_tier_share")

    if human_override == "execution_paused":
        return {
            "decision_type": "skip",
            "agent_decision": "skip",
            "rationale": "Human override is active (execution_paused), so the cycle remains in shadow behavior.",
            "escalation_required": False,
            "scenario": "human_override_active",
            "input_snapshot": {
                "human_override": human_override,
                "cycle_date": normalized_cycle_date,
            },
        }

    if normalized_cycle_date in blocklist_dates:
        return {
            "decision_type": "skip",
            "agent_decision": "skip",
            "rationale": f"Cycle date {normalized_cycle_date} is in the dispatch blocklist, so the cycle is skipped.",
            "escalation_required": False,
            "scenario": "dispatch_blocklist_date",
            "input_snapshot": {
                "cycle_date": normalized_cycle_date,
                "dispatch_blocklist_dates": sorted(blocklist_dates),
            },
        }

    if active_triggers:
        return {
            "decision_type": "escalation",
            "agent_decision": "investigate" if anomalies else "escalation",
            "rationale": f"Active D-2 triggers detected: {', '.join(active_triggers)}. Autonomous dispatch stays paused and the cycle must escalate.",
            "escalation_required": True,
            "scenario": "d2_trigger_active",
            "input_snapshot": {
                "d2_triggers_active": active_triggers,
                "dispatch_anomalies": anomalies,
                "cycle_date": normalized_cycle_date,
            },
        }

    if high_share is not None and high_share_threshold is not None and high_share >= high_share_threshold * 0.9:
        return {
            "decision_type": "dispatch_confirm",
            "agent_decision": "dispatch_confirm",
            "rationale": (
                f"No active D-2 triggers were found. High-tier share is elevated ({high_share:.4f}) but still below threshold "
                f"({high_share_threshold:.4f}), so dispatch remains allowed and the warning is informational only."
            ),
            "escalation_required": False,
            "scenario": "score_drift_near_threshold_but_below",
            "input_snapshot": {
                "current_high_share": high_share,
                "high_tier_share_threshold": high_share_threshold,
                "cycle_date": normalized_cycle_date,
            },
        }

    return {
        "decision_type": "dispatch_confirm",
        "agent_decision": "dispatch_confirm",
        "rationale": "No active D-2 triggers or dispatch anomalies were found, so the cycle remains in the normal dispatch-confirm shadow state.",
        "escalation_required": False,
        "scenario": "normal_cycle_no_anomalies",
        "input_snapshot": {
            "d2_triggers_active": active_triggers,
            "dispatch_anomalies": anomalies,
            "cycle_date": normalized_cycle_date,
        },
    }


def _run_shadow_decision_cycle(payload: dict | None = None) -> dict:
    payload = payload or {}
    cycle_date = str(payload.get("cycle_date") or datetime.now(timezone.utc).date().isoformat()).strip()
    status_payload = _load_agent_status()
    derived = _derive_shadow_decision(status_payload, cycle_date=cycle_date)
    created = _create_shadow_decision(
        {
            "decision_type": derived["decision_type"],
            "agent_decision": derived["agent_decision"],
            "rationale": derived["rationale"],
            "cycle_date": cycle_date,
            "input_snapshot": {
                "agent_status": status_payload,
                "derived_scenario": derived["scenario"],
                "decision_basis": derived["input_snapshot"],
            },
        },
        refresh_artifacts=True,
        refresh_trigger="shadow_run",
    )
    created["scenario"] = derived["scenario"]
    created["escalation_required"] = derived["escalation_required"]
    return created


def _refresh_phase5_daily_status_artifacts() -> dict:
    from pipeline.phase5_daily_status import OUTPUT_JSON_PATH, OUTPUT_MARKDOWN_PATH, build_daily_status_snapshot, save_outputs

    snapshot = build_daily_status_snapshot()
    save_outputs(snapshot)
    return {
        "status": "ok",
        "json_artifact": str(OUTPUT_JSON_PATH.relative_to(PROJECT_ROOT)),
        "markdown_artifact": str(OUTPUT_MARKDOWN_PATH.relative_to(PROJECT_ROOT)),
        "rendered_at": snapshot["run_timestamp"],
    }


def _refresh_shadow_monitor_artifacts(trigger: str, cycle_date: str | None = None, record_id: str | None = None) -> dict:
    try:
        from pipeline.phase5_shadow_monitor import (
            OUTPUT_DIVERGENCES_PATH,
            OUTPUT_HTML_PATH,
            build_shadow_monitor_payload,
            render_shadow_divergences_markdown,
            render_shadow_monitor_report,
        )

        payload = build_shadow_monitor_payload()
        OUTPUT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_HTML_PATH.write_text(render_shadow_monitor_report(payload), encoding="utf-8")
        OUTPUT_DIVERGENCES_PATH.write_text(render_shadow_divergences_markdown(payload), encoding="utf-8")
        daily_status_refresh = _refresh_phase5_daily_status_artifacts()
        return {
            "status": "ok",
            "trigger": trigger,
            "cycle_date": cycle_date,
            "record_id": record_id,
            "html_report": str(OUTPUT_HTML_PATH.relative_to(PROJECT_ROOT)),
            "divergence_report": str(OUTPUT_DIVERGENCES_PATH.relative_to(PROJECT_ROOT)),
            "daily_status_refresh": daily_status_refresh,
            "rendered_at": payload["run_timestamp"],
        }
    except Exception as exc:  # pragma: no cover
        logger.exception("Unable to refresh Phase 5 shadow monitor artifacts after %s", trigger)
        return {
            "status": "error",
            "trigger": trigger,
            "cycle_date": cycle_date,
            "record_id": record_id,
            "error": str(exc),
        }


def _load_phase5_daily_status(refresh: bool = False) -> dict:
    # Local import on purpose: `pipeline.phase5_daily_status` imports
    # `pipeline.phase5_shadow_monitor`, and that module imports
    # `_ensure_agent_decision_log_table` / `_load_agent_status` from this
    # file (`api.churn_service`). Keeping the import inside the function
    # avoids triggering that circular dependency during module import time
    # and makes the dependency explicit for future readers.
    from pipeline.phase5_daily_status import (
        OUTPUT_JSON_PATH,
        OUTPUT_MARKDOWN_PATH,
        build_daily_status_snapshot,
        render_daily_status_markdown,
        save_outputs,
    )

    snapshot = build_daily_status_snapshot()
    if refresh:
        save_outputs(snapshot)
    response = dict(snapshot)
    response["artifacts"] = {
        "json": str(OUTPUT_JSON_PATH.relative_to(PROJECT_ROOT)),
        "markdown": str(OUTPUT_MARKDOWN_PATH.relative_to(PROJECT_ROOT)),
        "refreshed": refresh,
    }
    response["markdown_preview"] = render_daily_status_markdown(snapshot)
    return response


def _load_phase5_shadow_monitor_status(refresh: bool = False) -> dict:
    # Local import on purpose: `pipeline.phase5_shadow_monitor` imports
    # `_ensure_agent_decision_log_table` and `_load_agent_status` from this
    # module. Importing it lazily here keeps the circular dependency from
    # exploding at module import time and documents why this is not a
    # top-level import.
    from pipeline.phase5_shadow_monitor import (
        OUTPUT_DIVERGENCES_PATH,
        OUTPUT_HTML_PATH,
        build_shadow_monitor_payload,
        render_shadow_divergences_markdown,
        render_shadow_monitor_report,
    )

    payload = build_shadow_monitor_payload()
    if refresh:
        OUTPUT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_HTML_PATH.write_text(render_shadow_monitor_report(payload), encoding="utf-8")
        OUTPUT_DIVERGENCES_PATH.write_text(render_shadow_divergences_markdown(payload), encoding="utf-8")
    response = dict(payload)
    response["artifacts"] = {
        "html": str(OUTPUT_HTML_PATH.relative_to(PROJECT_ROOT)),
        "divergences_markdown": str(OUTPUT_DIVERGENCES_PATH.relative_to(PROJECT_ROOT)),
        "refreshed": refresh,
    }
    return response


def _load_phase5_operational_snapshot(refresh: bool = False) -> dict:
    return {
        "phase": "phase5",
        "timestamp": _utc_now_iso(),
        "agent_status": _load_agent_status(),
        "daily_status": _load_phase5_daily_status(refresh=refresh),
        "shadow_monitor": _load_phase5_shadow_monitor_status(refresh=refresh),
    }


def _reconcile_shadow_decision(payload: dict) -> dict:
    _ensure_agent_decision_log_table()

    record_id = str(payload.get("record_id") or "").strip()
    cycle_date = str(payload.get("cycle_date") or "").strip()
    human_decision = str(payload.get("human_decision") or "").strip()

    if not human_decision:
        raise ValueError("human_decision is required")
    if not record_id and not cycle_date:
        raise ValueError("record_id or cycle_date is required")

    with _ops_engine().begin() as conn:
        if record_id:
            row = conn.execute(
                text(
                    """
                    SELECT id, decision_type, agent_decision, cycle_date
                    FROM agent_decision_log
                    WHERE id = :record_id AND shadow_mode = TRUE
                    """
                ),
                {"record_id": record_id},
            ).mappings().first()
        else:
            normalized_cycle_date = pd.to_datetime(cycle_date, errors="raise").date().isoformat()
            row = conn.execute(
                text(
                    """
                    SELECT id, decision_type, agent_decision, cycle_date
                    FROM agent_decision_log
                    WHERE cycle_date = :cycle_date AND shadow_mode = TRUE
                    ORDER BY decision_ts DESC
                    LIMIT 1
                    """
                ),
                {"cycle_date": normalized_cycle_date},
            ).mappings().first()

        if row is None:
            raise ValueError("shadow decision record not found")

        match = str(row["agent_decision"]).strip() == human_decision
        conn.execute(
            text(
                """
                UPDATE agent_decision_log
                SET human_decision = :human_decision,
                    match = :match
                WHERE id = :record_id
                """
            ),
            {
                "human_decision": human_decision,
                "match": match,
                "record_id": row["id"],
            },
        )

    response = {
        "status": "ok",
        "record_id": row["id"],
        "cycle_date": str(row["cycle_date"]),
        "decision_type": row["decision_type"],
        "agent_decision": row["agent_decision"],
        "human_decision": human_decision,
        "match": match,
        "timestamp": _utc_now_iso(),
    }
    response["monitor_refresh"] = _refresh_shadow_monitor_artifacts(
        trigger="shadow_reconcile",
        cycle_date=str(row["cycle_date"]),
        record_id=str(row["id"]),
    )
    return response


def _load_existing_coupon_codes() -> set[str]:
    if not COUPON_REGISTRY_PATH.exists():
        return set()
    existing_codes: set[str] = set()
    with COUPON_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            code = payload.get("coupon_code")
            if isinstance(code, str):
                existing_codes.add(code)
    return existing_codes


def _generate_coupon_code(existing_codes: set[str]) -> str:
    for _ in range(1000):
        block1 = "".join(secrets.choice(COUPON_ALPHABET) for _ in range(4))
        block2 = "".join(secrets.choice(COUPON_ALPHABET) for _ in range(4))
        code = f"VIVA-{block1}-{block2}"
        if code not in existing_codes:
            return code
    raise RuntimeError("Unable to generate a unique coupon code")


def _generate_coupon(payload: dict) -> dict:
    customer_unique_id = str(payload.get("customer_unique_id") or payload.get("customer_id") or "").strip()
    risk_tier = str(payload.get("risk_tier") or payload.get("risk_level") or "").strip().upper()
    discount_pct = payload.get("discount_pct")
    scoring_metadata = _latest_scoring_metadata()

    if not customer_unique_id:
        raise ValueError("customer_unique_id is required")
    if risk_tier not in VALID_RISK_LEVELS:
        raise ValueError("risk_tier must be one of HIGH, MEDIUM, LOW")
    if discount_pct is None:
        raise ValueError("discount_pct is required")

    try:
        discount_value = float(discount_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("discount_pct must be numeric") from exc

    if not 0 <= discount_value <= 100:
        raise ValueError("discount_pct must be between 0 and 100")

    COUPON_REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with COUPON_LOCK:
        existing_codes = _load_existing_coupon_codes()
        coupon_code = _generate_coupon_code(existing_codes)
        created_at = _utc_now_iso()
        coupon_payload = {
            "customer_unique_id": customer_unique_id,
            "risk_tier": risk_tier,
            "discount_pct": int(discount_value) if discount_value.is_integer() else round(discount_value, 2),
            "coupon_code": coupon_code,
            "created_at": created_at,
            "run_id": scoring_metadata["run_id"],
            "run_date_tag": scoring_metadata["run_date_tag"],
            "model_version": scoring_metadata["model_version"],
        }
        with COUPON_REGISTRY_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(coupon_payload, ensure_ascii=False) + "\n")
    return coupon_payload


