from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen
from xml.etree import ElementTree as ET

from evidence.catalog_builder import load_allowlist
from evidence.phase7_artifacts import namespaced_artifact_path, resolve_phase7_mode

LOGGER = logging.getLogger(__name__)
USER_AGENT = "VivaMarketEvidenceBot/1.0"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _registry_path(allowlist: dict[str, Any], project_root: Path) -> Path:
    return project_root / allowlist["source_scraping_registry"]["path"]


def load_registry(path: Path) -> dict[str, Any]:
    if path.exists():
        return _load_json(path)
    return {
        "registry_version": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "key_fields": ["domain", "path_pattern"],
        "allowed_results": ["no", "null+flag", "solo_RSS_API", "sí"],
        "records": [],
    }


def _upsert_registry_record(records: list[dict[str, Any]], new_record: dict[str, Any]) -> None:
    for idx, record in enumerate(records):
        if record["domain"] == new_record["domain"] and record["path_pattern"] == new_record["path_pattern"]:
            records[idx] = new_record
            return
    records.append(new_record)


def _iter_sources(allowlist: dict[str, Any]) -> list[dict[str, Any]]:
    return list(allowlist.get("seed_sources", [])) + list(allowlist.get("expansion_pool", []))


def _parse_registry_key(registry_key: str) -> tuple[str, str]:
    domain, path_pattern = registry_key.split("::", 1)
    return domain, path_pattern


def register_source_governance_snapshot(
    allowlist: dict[str, Any],
    registry: dict[str, Any],
    checked_at: str,
) -> dict[str, Any]:
    records = registry.setdefault("records", [])
    for source in _iter_sources(allowlist):
        governance = source["scraping_governance"]
        domain, path_pattern = _parse_registry_key(governance["registry_key"])
        method = (
            "official_rss_feed" if source["automation_scope"]["allowed_channel"] == "rss_only" else "documented_manual_only"
        )
        note = governance["status_note"]
        if source["automation_scope"]["pipeline_status"] == "out_of_scope":
            note = f"Out of automated scope in Phase 7 v9. {note}"

        _upsert_registry_record(
            records,
            {
                "domain": domain,
                "path_pattern": path_pattern,
                "checked_at": checked_at,
                "scraping_permitido": governance["scraping_permitido"],
                "method": method,
                "note": note,
                "source_name": source["source_name"],
                "pipeline_status": source["automation_scope"]["pipeline_status"],
                "allowed_channel": source["automation_scope"]["allowed_channel"],
            },
        )
    return registry


def _parse_feed_datetime(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        return parsedate_to_datetime(raw_value).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    except Exception:  # noqa: BLE001  # pragma: no cover - defensive fallback
        return None


def fetch_rss_entries(feed_url: str, source_name: str) -> list[dict[str, Any]]:
    LOGGER.info("Fetching Phase 7 RSS feed for %s from %s", source_name, feed_url)
    with urlopen(feed_url) as response:
        payload = response.read()
    root = ET.fromstring(payload)
    entries: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        entries.append(
            {
                "source_name": source_name,
                "title": (item.findtext("title") or "").strip(),
                "link": (item.findtext("link") or "").strip(),
                "published_at": _parse_feed_datetime(item.findtext("pubDate")),
                "summary": (item.findtext("description") or "").strip(),
            }
        )
    return entries


def build_phase7_extraction_snapshot(
    project_root: Path | None = None,
    checked_at: str | None = None,
) -> dict[str, Any]:
    root = project_root or _project_root()
    allowlist = load_allowlist(root / "config" / "evidence_sources_allowlist.yaml")
    timestamp = checked_at or _now_utc_iso()
    registry_path = _registry_path(allowlist, root)
    registry = load_registry(registry_path)
    registry = register_source_governance_snapshot(allowlist, registry, timestamp)

    in_scope_articles: list[dict[str, Any]] = []
    out_of_scope_sources: list[dict[str, Any]] = []
    for source in _iter_sources(allowlist):
        automation_scope = source["automation_scope"]
        if automation_scope["pipeline_status"] == "in_scope" and automation_scope["allowed_channel"] == "rss_only":
            in_scope_articles.extend(fetch_rss_entries(automation_scope["rss_url"], source["source_name"]))
        else:
            out_of_scope_sources.append(
                {
                    "source_name": source["source_name"],
                    "pipeline_status": automation_scope["pipeline_status"],
                    "allowed_channel": automation_scope["allowed_channel"],
                    "scope_note": automation_scope["scope_note"],
                }
            )

    snapshot = {
        "run_at": timestamp,
        "mode": "phase7_rss_only_scope",
        "in_scope_source_count": len([s for s in _iter_sources(allowlist) if s["automation_scope"]["pipeline_status"] == "in_scope"]),
        "out_of_scope_source_count": len(out_of_scope_sources),
        "article_count": len(in_scope_articles),
        "in_scope_articles": in_scope_articles,
        "out_of_scope_sources": out_of_scope_sources,
    }
    _write_json(registry_path, registry)
    return snapshot


def write_phase7_extraction_snapshot(
    snapshot: dict[str, Any],
    project_root: Path | None = None,
    run_date: str | None = None,
    mode: str | None = None,
) -> Path:
    root = project_root or _project_root()
    effective_run_date = run_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    output_path = namespaced_artifact_path(root, f"phase7_source_snapshot_{effective_run_date}.json", resolve_phase7_mode(mode))
    _write_json(output_path, snapshot)
    return output_path


def build_and_write_phase7_extraction_snapshot(
    project_root: Path | None = None,
    run_date: str | None = None,
    checked_at: str | None = None,
    mode: str | None = None,
) -> dict[str, str]:
    root = project_root or _project_root()
    snapshot = build_phase7_extraction_snapshot(root, checked_at=checked_at)
    resolved_mode = resolve_phase7_mode(mode)
    snapshot["mode"] = resolved_mode if resolved_mode != "real" else snapshot.get("mode", "phase7_rss_only_scope")
    output_path = write_phase7_extraction_snapshot(snapshot, root, run_date=run_date, mode=resolved_mode)
    return {
        "snapshot_path": str(output_path),
        "article_count": str(snapshot["article_count"]),
        "out_of_scope_source_count": str(snapshot["out_of_scope_source_count"]),
        "run_at": snapshot["run_at"],
    }
