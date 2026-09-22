from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

LOGGER = logging.getLogger(__name__)

_SCORE_RANK = {"low": 0, "medium": 1, "high": 2}
_RANK_SCORE = {value: key for key, value in _SCORE_RANK.items()}
_STUDY_BASE_SCORE = {
    "rct": "high",
    "quasi_experimental": "medium",
    "observational": "medium",
    "industry_benchmark": "low",
    "industry_heuristic": "low",
}
_REQUIRED_ALLOWLIST_KEYS = {"phase", "cadence", "open_access_only", "source_levels", "approval"}
_REQUIRED_APPROVAL_KEYS = {"mode", "single_approver", "ab_mode"}
_REQUIRED_SOURCE_DISCOVERY_KEYS = {
    "source_name",
    "source_level",
    "peer_review_status",
    "open_access_verified",
    "used_in",
    "seed_role",
    "source_domains",
    "automation_scope",
    "scraping_governance",
}
_REQUIRED_AUTOMATION_SCOPE_KEYS = {"pipeline_status", "allowed_channel", "scope_note"}
_ALLOWED_PIPELINE_STATUSES = {"in_scope", "out_of_scope"}
_ALLOWED_CHANNELS = {"manual_only", "rss_only"}
_REQUIRED_SCRAPING_GOVERNANCE_KEYS = {
    "mode",
    "scraping_permitido",
    "registry_key",
    "status_note",
}
_ALLOWED_SCRAPING_RESULTS = {"sí", "no", "solo_RSS_API", "null+flag"}
_REQUIRED_SEED_KEYS = {
    "entry_id",
    "ref_id",
    "intervention_id",
    "source_name",
    "source_level",
    "peer_review_status",
    "study_design",
    "actionable_elements",
    "quote_or_anchor",
}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _missing_keys(payload: Dict[str, Any], required_keys: set[str]) -> List[str]:
    return sorted(key for key in required_keys if key not in payload)


def _validate_allowlist(allowlist: Dict[str, Any]) -> Dict[str, Any]:
    missing = _missing_keys(allowlist, _REQUIRED_ALLOWLIST_KEYS)
    if missing:
        raise ValueError(f"Phase 6 allowlist missing required keys: {', '.join(missing)}")

    source_levels = allowlist["source_levels"]
    if not isinstance(source_levels, dict) or not source_levels:
        raise ValueError("Phase 6 allowlist must define a non-empty 'source_levels' mapping")

    for level_name, level_payload in source_levels.items():
        if "confidence_ceiling" not in level_payload:
            raise ValueError(f"source_level '{level_name}' is missing 'confidence_ceiling'")
        confidence_ceiling = level_payload["confidence_ceiling"]
        if confidence_ceiling not in _SCORE_RANK:
            raise ValueError(
                f"source_level '{level_name}' has invalid confidence_ceiling '{confidence_ceiling}'"
            )

    approval = allowlist["approval"]
    missing_approval = _missing_keys(approval, _REQUIRED_APPROVAL_KEYS)
    if missing_approval:
        raise ValueError(f"Phase 6 approval config missing required keys: {', '.join(missing_approval)}")

    source_registry = allowlist.get("source_scraping_registry")
    if source_registry is not None:
        required_registry_keys = {"path", "key_fields", "required_record_fields", "allowed_results"}
        missing_registry = _missing_keys(source_registry, required_registry_keys)
        if missing_registry:
            raise ValueError(
                "source_scraping_registry is missing required keys: " + ", ".join(missing_registry)
            )
        if source_registry["allowed_results"] != sorted(_ALLOWED_SCRAPING_RESULTS):
            raise ValueError("source_scraping_registry.allowed_results must match the supported scraping outcomes")

    for collection_name in ("seed_sources", "expansion_pool"):
        collection = allowlist.get(collection_name, [])
        if collection is None:
            continue
        if not isinstance(collection, list):
            raise ValueError(f"{collection_name} must be a list when present")
        for index, entry in enumerate(collection, start=1):
            missing_source_keys = _missing_keys(entry, _REQUIRED_SOURCE_DISCOVERY_KEYS)
            if missing_source_keys:
                raise ValueError(
                    f"{collection_name} entry #{index} is missing required keys: {', '.join(missing_source_keys)}"
                )

            automation_scope = entry["automation_scope"]
            missing_scope_keys = _missing_keys(automation_scope, _REQUIRED_AUTOMATION_SCOPE_KEYS)
            if missing_scope_keys:
                raise ValueError(
                    f"{collection_name} entry #{index} automation_scope is missing required keys: "
                    + ", ".join(missing_scope_keys)
                )

            pipeline_status = automation_scope["pipeline_status"]
            if pipeline_status not in _ALLOWED_PIPELINE_STATUSES:
                raise ValueError(
                    f"{collection_name} entry #{index} has unsupported pipeline_status '{pipeline_status}'"
                )

            allowed_channel = automation_scope["allowed_channel"]
            if allowed_channel not in _ALLOWED_CHANNELS:
                raise ValueError(
                    f"{collection_name} entry #{index} has unsupported allowed_channel '{allowed_channel}'"
                )
            if allowed_channel == "rss_only" and not automation_scope.get("rss_url"):
                raise ValueError(
                    f"{collection_name} entry #{index} must define automation_scope.rss_url for rss_only sources"
                )

            scraping_governance = entry["scraping_governance"]
            missing_governance_keys = _missing_keys(scraping_governance, _REQUIRED_SCRAPING_GOVERNANCE_KEYS)
            if missing_governance_keys:
                raise ValueError(
                    f"{collection_name} entry #{index} scraping_governance is missing required keys: "
                    + ", ".join(missing_governance_keys)
                )

            scraping_result = scraping_governance["scraping_permitido"]
            if scraping_result not in _ALLOWED_SCRAPING_RESULTS:
                raise ValueError(
                    f"{collection_name} entry #{index} has unsupported scraping_permitido '{scraping_result}'"
                )

    return allowlist


def _validate_seed_entries(seed_entries: List[Dict[str, Any]], allowlist: Dict[str, Any]) -> List[Dict[str, Any]]:
    known_levels = set(allowlist["source_levels"].keys())
    for index, entry in enumerate(seed_entries, start=1):
        missing = _missing_keys(entry, _REQUIRED_SEED_KEYS)
        if missing:
            raise ValueError(f"seed entry #{index} is missing required keys: {', '.join(missing)}")

        source_level = entry["source_level"]
        if source_level not in known_levels:
            raise ValueError(f"source_level '{source_level}' is not defined in the allowlist")

    return seed_entries


def load_allowlist(path: Path | None = None) -> Dict[str, Any]:
    """Load and validate the Phase 6 source-governance allowlist defined in Sub-phase 6.1."""
    target = path or (_project_root() / "config" / "evidence_sources_allowlist.yaml")
    LOGGER.info("Loading Phase 6 allowlist from %s", target)
    return _validate_allowlist(_load_json(target))


def load_seed_evidence(path: Path | None = None) -> List[Dict[str, Any]]:
    """Load the Phase 6 seed evidence baseline used by the bootstrap catalog slice."""
    target = path or (_project_root() / "data" / "interim" / "phase6_seed_evidence.json")
    LOGGER.info("Loading Phase 6 seed evidence from %s", target)
    return _load_json(target)


def _bounded_score(score: str, ceiling: str) -> str:
    return _RANK_SCORE[min(_SCORE_RANK[score], _SCORE_RANK[ceiling])]


def derive_confidence_score(entry: Dict[str, Any], confidence_ceiling: str) -> str:
    """Apply the deterministic confidence rules from the Phase 6 spec bootstrap slice."""
    base = _STUDY_BASE_SCORE.get(entry.get("study_design"), "low")
    peer_review_status = entry.get("peer_review_status", "none")

    if peer_review_status == "preprint":
        base = _bounded_score(base, "medium")
    elif peer_review_status == "none":
        base = _bounded_score(base, "low")

    return _bounded_score(base, confidence_ceiling)


def derive_actionability_score(entry: Dict[str, Any]) -> str:
    """Score actionability from actionable-element completeness, independent of confidence."""
    elements = entry.get("actionable_elements") or {}
    populated = sum(1 for value in elements.values() if value not in (None, "", [], {}))
    if populated >= 4:
        return "high"
    if populated >= 2:
        return "medium"
    return "low"


def build_catalog_entries(
    allowlist: Dict[str, Any],
    seed_entries: List[Dict[str, Any]],
    catalog_run_date: str,
) -> List[Dict[str, Any]]:
    """Build the append-only bootstrap evidence catalog entries defined in Sub-phase 6.2."""
    LOGGER.info("Building bootstrap Phase 6 evidence catalog for %s", catalog_run_date)
    validated_allowlist = _validate_allowlist(allowlist)
    validated_seed_entries = _validate_seed_entries(seed_entries, validated_allowlist)
    levels = validated_allowlist["source_levels"]
    approval = validated_allowlist["approval"]
    catalog_entries: List[Dict[str, Any]] = []

    for entry in validated_seed_entries:
        source_level = entry["source_level"]
        confidence_ceiling = levels[source_level]["confidence_ceiling"]
        catalog_entry = {
            **entry,
            "catalog_run_date": catalog_run_date,
            "confidence_ceiling": confidence_ceiling,
            "confidence_score": derive_confidence_score(entry, confidence_ceiling),
            "actionability_score": derive_actionability_score(entry),
            "approval_mode": approval["mode"],
            "single_approver": approval["single_approver"],
            "ab_mode": approval["ab_mode"],
            "open_access_only": allowlist["open_access_only"],
            "catalog_role": "seed_baseline",
        }
        catalog_entries.append(catalog_entry)

    return catalog_entries


def render_catalog_summary(
    catalog_entries: List[Dict[str, Any]],
    allowlist: Dict[str, Any],
    catalog_run_date: str,
) -> str:
    """Render the human-readable summary that explains the Phase 6 seed-baseline catalog snapshot."""
    interventions = sorted({entry["intervention_id"] for entry in catalog_entries})
    high_conf = sum(entry["confidence_score"] == "high" for entry in catalog_entries)
    medium_conf = sum(entry["confidence_score"] == "medium" for entry in catalog_entries)
    low_conf = sum(entry["confidence_score"] == "low" for entry in catalog_entries)
    high_action = sum(entry["actionability_score"] == "high" for entry in catalog_entries)

    lines = [
        "# PHASE 6 EVIDENCE CATALOG SUMMARY",
        "",
        f"- Run date: {catalog_run_date}",
        f"- Phase: {allowlist['phase']}",
        f"- Cadence: {allowlist['cadence']}",
        f"- Open access only: {allowlist['open_access_only']}",
        f"- Approval mode: {allowlist['approval']['mode']}",
        f"- Single approver: {allowlist['approval']['single_approver']}",
        f"- A/B mode: {allowlist['approval']['ab_mode']}",
        "",
        "## Snapshot",
        f"- Entries: {len(catalog_entries)}",
        f"- Interventions covered: {', '.join(interventions)}",
        f"- Confidence distribution: high={high_conf}, medium={medium_conf}, low={low_conf}",
        f"- High-actionability entries: {high_action}",
        "",
        "## Governance interpretation",
        "- This artifact is a seed baseline generated from inherited static references, not a live-discovery refresh.",
        "- Low-confidence but high-actionability entries remain usable for idea enrichment only; they do not authorize production changes on their own.",
        "- Real holdout / real dispatch remains explicitly deferred in this implementation slice.",
        "",
        "## Covered entries",
    ]

    for entry in catalog_entries:
        lines.append(
            f"- {entry['intervention_id']} | {entry['source_name']} | confidence={entry['confidence_score']} | actionability={entry['actionability_score']} | ref={entry['ref_id']}"
        )

    return "\n".join(lines) + "\n"


def write_catalog_snapshot(
    catalog_entries: List[Dict[str, Any]],
    summary_markdown: str,
    project_root: Path | None = None,
    catalog_run_date: str | None = None,
) -> Tuple[Path, Path]:
    """Write the immutable dated catalog snapshot and fail if that dated snapshot already exists."""
    root = project_root or _project_root()
    run_date = catalog_run_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    data_dir = root / "data" / "processed"
    reports_dir = root / "reports"
    data_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    catalog_path = data_dir / f"evidence_catalog_{run_date}.json"
    summary_path = reports_dir / f"phase6_evidence_catalog_summary_{run_date}.md"

    if catalog_path.exists():
        raise FileExistsError(f"Phase 6 catalog snapshot already exists for run_date {run_date}: {catalog_path}")

    LOGGER.info("Writing Phase 6 catalog snapshot to %s", catalog_path)
    catalog_path.write_text(json.dumps(catalog_entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LOGGER.info("Writing Phase 6 summary report to %s", summary_path)
    summary_path.write_text(summary_markdown, encoding="utf-8")
    return catalog_path, summary_path


def build_and_write_catalog(project_root: Path | None = None, run_date: str | None = None) -> Dict[str, str]:
    """Run the local Phase 6 bootstrap pipeline and return the generated artifact paths."""
    root = project_root or _project_root()
    catalog_run_date = run_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    allowlist = load_allowlist(root / "config" / "evidence_sources_allowlist.yaml")
    seed_entries = _validate_seed_entries(
        load_seed_evidence(root / "data" / "interim" / "phase6_seed_evidence.json"),
        allowlist,
    )
    catalog_entries = build_catalog_entries(allowlist, seed_entries, catalog_run_date)
    summary = render_catalog_summary(catalog_entries, allowlist, catalog_run_date)
    catalog_path, summary_path = write_catalog_snapshot(
        catalog_entries=catalog_entries,
        summary_markdown=summary,
        project_root=root,
        catalog_run_date=catalog_run_date,
    )
    return {
        "catalog_path": str(catalog_path),
        "summary_path": str(summary_path),
        "run_date": catalog_run_date,
        "entry_count": str(len(catalog_entries)),
    }
