from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

_CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}
_ACTIONABILITY_RANK = {"high": 2, "medium": 1, "low": 0}
_APPLICABILITY_RANK = {"high": 2, "medium": 1, "low": 0}
_CONFIDENCE_WEIGHT = 100
_ACTIONABILITY_WEIGHT = 10
_APPLICABILITY_WEIGHT = 1


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_latest_catalog_path(project_root: Path | None = None) -> Path:
    root = project_root or _project_root()
    candidates = sorted((root / "data" / "processed").glob("evidence_catalog_*.json"))
    if not candidates:
        raise FileNotFoundError("no evidence catalog found under data/processed")
    return candidates[-1]


def _resolve_catalog_path_for_run_date(run_date: str, project_root: Path | None = None) -> Path:
    root = project_root or _project_root()
    target = root / "data" / "processed" / f"evidence_catalog_{run_date}.json"
    if not target.exists():
        raise FileNotFoundError(f"no evidence catalog found for run_date {run_date}: {target}")
    return target


def load_catalog(path: Path | None = None) -> list[dict[str, Any]]:
    """Load either an explicit catalog snapshot or the latest available Phase 6 catalog."""
    target = path or _resolve_latest_catalog_path()
    LOGGER.info("Loading Phase 6 catalog from %s", target)
    return json.loads(target.read_text(encoding="utf-8"))


def _priority_score(entry: dict[str, Any]) -> int:
    """Score ranking order with fixed precedence: confidence > actionability > applicability."""
    return (
        _CONFIDENCE_RANK[entry["confidence_score"]] * _CONFIDENCE_WEIGHT
        + _ACTIONABILITY_RANK[entry["actionability_score"]] * _ACTIONABILITY_WEIGHT
        + _APPLICABILITY_RANK.get(entry.get("applicability_to_vivamarket", "low"), 0) * _APPLICABILITY_WEIGHT
    )


def build_recommendation_rows(catalog_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the Phase 6 catalog into recommendation rows while preserving governance gates."""
    rows: list[dict[str, Any]] = []
    for entry in catalog_entries:
        confidence = entry["confidence_score"]
        if confidence == "high":
            readiness = "approval_gate_eligible"
            recommendation_tier = "tier_1"
        elif confidence == "medium":
            readiness = "approval_gate_eligible"
            recommendation_tier = "tier_2"
        else:
            readiness = "evidence_enrichment_only"
            recommendation_tier = "tier_3"

        rows.append(
            {
                "intervention_id": entry["intervention_id"],
                "source_name": entry["source_name"],
                "ref_id": entry["ref_id"],
                "confidence_score": confidence,
                "actionability_score": entry["actionability_score"],
                "applicability_to_vivamarket": entry.get("applicability_to_vivamarket", "low"),
                "priority_score": _priority_score(entry),
                "recommendation_tier": recommendation_tier,
                "readiness": readiness,
                "copy_hypothesis": entry.get("actionable_elements", {}).get("copy"),
                "channel_hypothesis": entry.get("actionable_elements", {}).get("channel"),
                "timing_hypothesis": entry.get("actionable_elements", {}).get("timing"),
                "incentive_hypothesis": entry.get("actionable_elements", {}).get("incentive"),
                "effect_size_text": entry.get("effect_size_text"),
                "evidence_note": entry.get("quote_or_anchor"),
            }
        )

    return sorted(rows, key=lambda row: (-row["priority_score"], row["intervention_id"]))


def render_recommendations_report(rows: list[dict[str, Any]], run_date: str) -> str:
    """Render the human-readable recommendations report for the current catalog snapshot."""
    eligible = [row for row in rows if row["readiness"] == "approval_gate_eligible"]
    enrich_only = [row for row in rows if row["readiness"] != "approval_gate_eligible"]
    lines = [
        "# PHASE 6 DYNAMIC EVIDENCE RECOMMENDATIONS",
        "",
        f"- Run date: {run_date}",
        "- Source mode: seed-baseline bootstrap (not live-discovery yet)",
        "- Recommendation rule: confidence determines gate eligibility; actionability and applicability determine order inside the eligible set.",
        "",
        "## Recommended order",
    ]

    for idx, row in enumerate(rows, 1):
        lines.extend(
            [
                f"### {idx}. {row['intervention_id']} — {row['source_name']}",
                f"- Tier: {row['recommendation_tier']}",
                f"- Readiness: {row['readiness']}",
                f"- Confidence: {row['confidence_score']}",
                f"- Actionability: {row['actionability_score']}",
                f"- Applicability to VivaMarket: {row['applicability_to_vivamarket']}",
                f"- Priority score: {row['priority_score']}",
                f"- Suggested copy hypothesis: {row['copy_hypothesis']}",
                f"- Suggested channel hypothesis: {row['channel_hypothesis']}",
                f"- Suggested timing hypothesis: {row['timing_hypothesis']}",
                f"- Suggested incentive hypothesis: {row['incentive_hypothesis']}",
                f"- Evidence anchor: {row['effect_size_text']}",
                f"- Traceability note: {row['evidence_note']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Interpretation",
            f"- Approval-gate-eligible candidates: {len(eligible)}",
            f"- Evidence-enrichment-only candidates: {len(enrich_only)}",
            "- This report is parallel to the historical `phase5_step6_intervention_recommendations_20260718.md` artifact and does not replace it yet.",
            "- Any low-confidence item remains blocked from autonomous approval flow even if it is highly actionable.",
            "",
            "## Validation prompts for Sub-phase 6.3",
            "- Check that every evidence anchor maps to the expected intervention ID.",
            "- Confirm that no low-confidence entry appears as approval-gate-eligible.",
            "- Review whether the ordering remains stable when new seed or live evidence is added.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_recommendations_report(
    rows: list[dict[str, Any]],
    project_root: Path | None = None,
    run_date: str | None = None,
) -> Path:
    """Persist the dated recommendations report produced from the current catalog slice."""
    root = project_root or _project_root()
    run_date = run_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"phase6_dynamic_evidence_recommendations_{run_date}.md"
    LOGGER.info("Writing Phase 6 dynamic recommendations report to %s", path)
    path.write_text(render_recommendations_report(rows, run_date), encoding="utf-8")
    return path


def build_and_write_recommendations(project_root: Path | None = None, run_date: str | None = None) -> dict[str, str]:
    """Run the Phase 6 recommendation pipeline for an exact run_date or latest available catalog."""
    root = project_root or _project_root()
    catalog_path = _resolve_catalog_path_for_run_date(run_date, root) if run_date else _resolve_latest_catalog_path(root)
    effective_run_date = run_date or catalog_path.stem.removeprefix("evidence_catalog_")
    catalog = load_catalog(catalog_path)
    rows = build_recommendation_rows(catalog)
    report_path = write_recommendations_report(rows, project_root=root, run_date=effective_run_date)
    return {
        "report_path": str(report_path),
        "run_date": effective_run_date,
        "recommendation_count": str(len(rows)),
        "top_intervention": rows[0]["intervention_id"] if rows else "",
    }
