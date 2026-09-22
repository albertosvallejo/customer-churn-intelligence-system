from __future__ import annotations

import json
import logging
import os
import re
import string
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evidence.phase7_artifacts import (
    SYNTHETIC_WARNING,
    namespaced_artifact_path,
    namespaced_report_path,
    phase7_namespace_dir,
    resolve_phase7_mode,
)

LOGGER = logging.getLogger(__name__)
_NUMERIC_PATTERN = re.compile(r"\d+(?:[\.,]\d+)?%?")
_DEFAULT_OPENAI_MODEL = "gpt-5.6-luna"
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_REASONING_EFFORT = "low"
_ALLOWED_FAKE_LLM_ENVS = {"test", "ci"}
_DEFAULT_LLM_MODE = "disabled"
_LLM_MODE_LIVE = "live"


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_snapshot_path(project_root: Path | None = None, run_date: str | None = None, mode: str | None = None) -> Path:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    namespace_dir = phase7_namespace_dir(root, resolved_mode)
    if run_date:
        path = namespaced_artifact_path(root, f"phase7_source_snapshot_{run_date}.json", resolved_mode)
        if not path.exists():
            raise FileNotFoundError(f"no Phase 7 source snapshot found for run_date {run_date}: {path}")
        return path
    candidates = sorted(namespace_dir.glob(namespaced_artifact_path(root, "phase7_source_snapshot_*.json", resolved_mode).name))
    if not candidates:
        raise FileNotFoundError(f"no Phase 7 source snapshot found under {namespace_dir}")
    return candidates[-1]


def load_snapshot(path: Path) -> dict[str, Any]:
    LOGGER.info("Loading Phase 7 source snapshot from %s", path)
    return json.loads(path.read_text(encoding="utf-8"))


def extract_numeric_claims(text: str | None) -> list[str]:
    if not text:
        return []
    return _NUMERIC_PATTERN.findall(text)


def _load_env_file(env_path: Path) -> dict[str, str]:
    payload: dict[str, str] = {}
    if not env_path.exists():
        return payload
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def resolve_openai_runtime_config(project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or _project_root()
    env_candidates = [root / ".env"]
    key = os.environ.get("OPENAI_API_KEY")
    source = "process_env" if key else None
    env_payload: dict[str, str] = {}
    merged_env_payload: dict[str, str] = {}
    if not key:
        for candidate in env_candidates:
            candidate_payload = _load_env_file(candidate)
            merged_env_payload.update(candidate_payload)
            if candidate_payload.get("OPENAI_API_KEY"):
                key = candidate_payload["OPENAI_API_KEY"]
                source = str(candidate)
                break
    else:
        for candidate in env_candidates:
            merged_env_payload.update(_load_env_file(candidate))
    env_payload = merged_env_payload
    model = (
        os.environ.get("PHASE7_OPENAI_MODEL")
        or env_payload.get("PHASE7_OPENAI_MODEL")
        or _DEFAULT_OPENAI_MODEL
    )
    reasoning_effort = (
        os.environ.get("PHASE7_OPENAI_REASONING_EFFORT")
        or env_payload.get("PHASE7_OPENAI_REASONING_EFFORT")
        or _DEFAULT_REASONING_EFFORT
    )
    temperature_raw = (
        os.environ.get("PHASE7_OPENAI_TEMPERATURE")
        or env_payload.get("PHASE7_OPENAI_TEMPERATURE")
        or str(_DEFAULT_TEMPERATURE)
    )
    try:
        temperature = float(temperature_raw)
    except ValueError as exc:
        raise ValueError(f"invalid PHASE7_OPENAI_TEMPERATURE '{temperature_raw}'") from exc
    app_env = (os.environ.get("APP_ENV") or env_payload.get("APP_ENV") or "local").strip().lower()
    llm_provider = (
        os.environ.get("PHASE7_LLM_PROVIDER")
        or env_payload.get("PHASE7_LLM_PROVIDER")
        or "openai"
    ).strip().lower()
    ci_fake_llm = (
        os.environ.get("CI_FAKE_LLM")
        or env_payload.get("CI_FAKE_LLM")
        or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    fake_llm_enabled = app_env in _ALLOWED_FAKE_LLM_ENVS and (
        llm_provider == "fake" or ci_fake_llm
    )
    # Master switch for real OpenAI calls. Fail closed: only the exact value "live" enables them.
    llm_mode = (
        os.environ.get("LLM_MODE")
        or env_payload.get("LLM_MODE")
        or _DEFAULT_LLM_MODE
    ).strip().strip("\"'").lower()
    return {
        "api_key": key,
        "api_key_source": source,
        "model": model,
        "temperature": temperature,
        "reasoning_effort": reasoning_effort,
        "app_env": app_env,
        "llm_mode": llm_mode,
        "llm_provider": "fake" if fake_llm_enabled else "openai",
        "fake_llm_enabled": fake_llm_enabled,
    }


def synthesize_article_with_fake_llm(
    article: dict[str, Any],
    runtime: dict[str, Any],
) -> dict[str, Any]:
    title = (article.get("title") or "").strip()
    summary = (article.get("summary") or "").strip()
    combined_anchor = " ".join(part for part in [title, summary] if part).strip()
    numeric_claims_used = list(dict.fromkeys(extract_numeric_claims(combined_anchor)))
    summary_for_business = summary or title or "No source summary was provided."
    pros: list[str] = []
    cons: list[str] = []

    if numeric_claims_used:
        pros.append("The source includes explicit numeric claims that can be reviewed deterministically in CI.")
    else:
        pros.append("The source can still be summarized deterministically without external network access.")
        cons.append("No explicit numeric claims were present in the source text.")

    recommended_action = (
        "CI fake LLM output generated for contract validation only. Keep human review before operational use."
    )

    return {
        "summary_for_business": summary_for_business,
        "pros": pros,
        "cons": cons,
        "recommended_action": recommended_action,
        "numeric_claims_used": numeric_claims_used,
        "generation_contract_violation": False,
        "llm_request": {
            "provider": "fake",
            "model": "ci-fake-llm-v1",
            "temperature": 0.0,
            "reasoning_effort": "none",
            "api_key_source": "not_used_fake_llm",
            "attempt": 1,
            "app_env": runtime.get("app_env"),
        },
        "llm_response": {
            "id": "ci-fake-llm-response",
            "model": "ci-fake-llm-v1",
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        },
    }


def synthesize_article_with_openai(
    article: dict[str, Any],
    project_root: Path | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    runtime = resolve_openai_runtime_config(project_root)
    if runtime.get("fake_llm_enabled"):
        return synthesize_article_with_fake_llm(article, runtime)
    if runtime.get("llm_mode") != _LLM_MODE_LIVE:
        raise RuntimeError(
            f"Live LLM calls are disabled (LLM_MODE='{runtime.get('llm_mode') or 'unset'}'). "
            "AI drafting requires LLM_MODE=live and a valid OPENAI_API_KEY in the local .env or process environment."
        )
    if not runtime["api_key"]:
        raise RuntimeError(
            "OPENAI_API_KEY is not configured. AI drafting is disabled until the operator provides a valid key in the local .env or process environment."
        )

    system_prompt = (
        "You are generating structured business-facing action drafts for a churn-retention portfolio system. "
        "Use only the title and summary provided. Never invent metrics or facts not present in the source text. "
        "Return strict JSON with keys: summary_for_business, pros, cons, recommended_action, numeric_claims_used. "
        "pros and cons must each be arrays of short strings. numeric_claims_used must be an array of strings containing only numbers/percentages explicitly present in the source text. "
        "If the source text contains no numeric claims, numeric_claims_used must be [] exactly. Never return an object, explanation, null, or placeholder text for numeric_claims_used."
    )
    user_prompt = {
        "source_name": article.get("source_name"),
        "title": article.get("title"),
        "summary": article.get("summary"),
        "article_url": article.get("link"),
        "published_at": article.get("published_at"),
    }
    payload = {
        "model": runtime["model"],
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
        ],
    }
    if runtime["model"].startswith("gpt-5.6-"):
        payload["reasoning_effort"] = runtime["reasoning_effort"]
    else:
        payload["temperature"] = runtime["temperature"]
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {runtime['api_key']}",
        },
        method="POST",
    )
    last_result: dict[str, Any] | None = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - exercised only in live connectivity runs
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI request failed with status {exc.code}: {error_body}"
            ) from exc

        message_content = body["choices"][0]["message"]["content"]
        synthesis = json.loads(message_content)
        numeric_claims_used_raw = synthesis.get("numeric_claims_used")
        generation_contract_violation = not _is_string_list(numeric_claims_used_raw)
        last_result = {
            "summary_for_business": synthesis.get("summary_for_business") or article.get("summary") or article.get("title") or "",
            "pros": synthesis.get("pros") or [],
            "cons": synthesis.get("cons") or [],
            "recommended_action": synthesis.get("recommended_action") or "",
            "numeric_claims_used": numeric_claims_used_raw if numeric_claims_used_raw is not None else [],
            "generation_contract_violation": generation_contract_violation,
            "llm_request": {
                "provider": "openai",
                "model": runtime["model"],
                "temperature": runtime["temperature"],
                "reasoning_effort": runtime.get("reasoning_effort"),
                "api_key_source": runtime["api_key_source"],
                "attempt": attempt + 1,
            },
            "llm_response": {
                "id": body.get("id"),
                "model": body.get("model"),
                "usage": body.get("usage"),
            },
        }
        if not generation_contract_violation:
            return last_result

    assert last_result is not None
    return last_result


def build_action_drafts(
    snapshot: dict[str, Any],
    project_root: Path | None = None,
    synthesizer: Callable[[dict[str, Any], Path | None], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    article_synthesizer = synthesizer or synthesize_article_with_openai
    for idx, article in enumerate(snapshot.get("in_scope_articles", []), start=1):
        summary = article.get("summary") or ""
        title = article.get("title") or ""
        combined_anchor = " ".join(part for part in [title, summary] if part).strip()
        synthesis = article_synthesizer(article, project_root)
        numeric_claims = extract_numeric_claims(combined_anchor)
        drafts.append(
            {
                "proposal_id": f"P7-DRAFT-{idx:03d}",
                "source_name": article["source_name"],
                "article_title": title,
                "article_url": article.get("link"),
                "published_at": article.get("published_at"),
                "summary_for_business": synthesis["summary_for_business"],
                "pros": synthesis.get("pros", []),
                "cons": synthesis.get("cons", []),
                "recommended_action": synthesis.get("recommended_action", ""),
                "numeric_claims": numeric_claims,
                "numeric_claims_used": synthesis.get("numeric_claims_used", []),
                "citation_anchor": combined_anchor,
                "status": "draft_ready",
                "generation_contract_violation": synthesis.get("generation_contract_violation", False),
                "llm_request": synthesis.get("llm_request"),
                "llm_response": synthesis.get("llm_response"),
                "llm_retry_used": (synthesis.get("llm_request") or {}).get("attempt", 1) > 1,
            }
        )
    return drafts


def _normalize_claim_comparison_text(text: str) -> str:
    """Normalize only separator spacing/punctuation for exact-meaning claim comparison.

    This deliberately does NOT normalize numbers, words, or units. It only smooths
    superficial separator formatting differences that appeared in the real dataset,
    specifically the Phase 7 case:
    "October 5- October 16, 2026" vs "October 5 - October 16, 2026".
    """
    normalized = text.strip()
    normalized = re.sub(r"\s*([-–—/:;,])\s*", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip(string.whitespace)


def validate_numeric_coherence(drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validation_rows: list[dict[str, Any]] = []
    for draft in drafts:
        citation_anchor = draft.get("citation_anchor") or ""
        normalized_citation_anchor = _normalize_claim_comparison_text(citation_anchor)
        numeric_claims_used_raw = draft.get("numeric_claims_used") or []

        # Added after the real P7-DRAFT-011 failure, where the model returned
        # {"none": "No specific numbers or percentages are provided in the source text."}
        # instead of the contracted List[str]. This must fail closed as an
        # upstream schema/contract violation, not be auto-coerced into [] and not
        # be mixed with genuine anchor-mismatch failures.
        invalid_format = not isinstance(numeric_claims_used_raw, list) or not all(
            isinstance(claim, str) for claim in numeric_claims_used_raw
        )
        numeric_claims_used = numeric_claims_used_raw if not invalid_format else []
        missing_from_citation_anchor = [
            claim
            for claim in numeric_claims_used
            if _normalize_claim_comparison_text(claim) not in normalized_citation_anchor
        ]
        validation_rows.append(
            {
                "proposal_id": draft["proposal_id"],
                "source_name": draft["source_name"],
                "validation_target": "citation_anchor",
                "numeric_claim_count": len(numeric_claims_used_raw) if isinstance(numeric_claims_used_raw, list) else 0,
                "numeric_claims_used": numeric_claims_used_raw,
                "invalid_format": invalid_format,
                "missing_from_citation_anchor": missing_from_citation_anchor,
                "passed": (not invalid_format) and len(missing_from_citation_anchor) == 0,
            }
        )
    return validation_rows


def render_action_drafts_report(drafts: list[dict[str, Any]], validation_rows: list[dict[str, Any]], run_date: str) -> str:
    lines = [
        "# PHASE 7 ACTION DRAFTS",
        "",
        f"- Run date: {run_date}",
        "- Upstream source mode: RSS-only scope (NNGroup + Baymard)",
        "- Proposal builder mode: article-level drafting with OpenAI-backed pros/contras synthesis",
        "",
        "## Draft proposals",
    ]
    for draft in drafts:
        llm_request = draft.get("llm_request") or {}
        llm_response = draft.get("llm_response") or {}
        lines.extend(
            [
                f"### {draft['proposal_id']} — {draft['source_name']}",
                f"- Title: {draft['article_title']}",
                f"- URL: {draft['article_url']}",
                f"- Published at: {draft['published_at']}",
                f"- Summary for business: {draft['summary_for_business']}",
                f"- Pros: {' | '.join(draft['pros']) if draft.get('pros') else 'none'}",
                f"- Cons: {' | '.join(draft['cons']) if draft.get('cons') else 'none'}",
                f"- Recommended action: {draft.get('recommended_action') or 'none'}",
                f"- Numeric claims detected in source anchor: {', '.join(draft['numeric_claims']) if draft['numeric_claims'] else 'none detected'}",
                f"- Numeric claims used by synthesis: {', '.join(draft.get('numeric_claims_used', [])) if draft.get('numeric_claims_used') else 'none used'}",
                f"- Citation anchor: {draft['citation_anchor']}",
                f"- LLM request: provider=openai | model={llm_request.get('model')} | temperature={llm_request.get('temperature')} | api_key_source={llm_request.get('api_key_source')}",
                f"- LLM response: model={llm_response.get('model')} | id={llm_response.get('id')} | usage={llm_response.get('usage')}",
                "",
            ]
        )
    lines.extend(["## Numeric coherence validation"])
    for row in validation_rows:
        lines.append(
            f"- {row['proposal_id']} | target={row['validation_target']} | passed={row['passed']} | invalid_format={row['invalid_format']} | numeric_claim_count={row['numeric_claim_count']} | numeric_claims_used={row['numeric_claims_used']} | missing_from_citation_anchor={row['missing_from_citation_anchor']}"
        )
    return "\n".join(lines) + "\n"


def write_action_drafts(
    drafts: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    project_root: Path | None = None,
    run_date: str | None = None,
    mode: str | None = None,
) -> tuple[Path, Path]:
    root = project_root or _project_root()
    effective_run_date = run_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    resolved_mode = resolve_phase7_mode(mode)
    data_path = namespaced_artifact_path(root, f"phase7_action_drafts_{effective_run_date}.json", resolved_mode)
    report_path = namespaced_report_path(root, f"phase7_action_drafts_{effective_run_date}.md", resolved_mode)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(
        json.dumps(
            {
                "mode": resolved_mode,
                "warning": SYNTHETIC_WARNING if resolved_mode == "synthetic_demo" else None,
                "run_date": effective_run_date,
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                "drafts": drafts,
                "validation": validation_rows,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(render_action_drafts_report(drafts, validation_rows, effective_run_date), encoding="utf-8")
    return data_path, report_path


def build_and_write_action_drafts(
    project_root: Path | None = None,
    run_date: str | None = None,
    synthesizer: Callable[[dict[str, Any], Path | None], dict[str, Any]] | None = None,
    mode: str | None = None,
) -> dict[str, str]:
    root = project_root or _project_root()
    resolved_mode = resolve_phase7_mode(mode)
    snapshot_path = _resolve_snapshot_path(root, run_date, resolved_mode)
    snapshot_name = snapshot_path.name.removeprefix("synthetic_demo__")
    effective_run_date = snapshot_name.removeprefix("phase7_source_snapshot_").removesuffix(".json")
    snapshot = load_snapshot(snapshot_path)
    drafts = build_action_drafts(snapshot, root, synthesizer=synthesizer)
    validation_rows = validate_numeric_coherence(drafts)
    data_path, report_path = write_action_drafts(drafts, validation_rows, root, effective_run_date, resolved_mode)
    return {
        "drafts_path": str(data_path),
        "report_path": str(report_path),
        "draft_count": str(len(drafts)),
        "validated_count": str(sum(1 for row in validation_rows if row["passed"])),
        "run_date": effective_run_date,
    }
