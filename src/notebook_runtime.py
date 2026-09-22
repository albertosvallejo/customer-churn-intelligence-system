from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import yaml

DEFAULT_TIMEZONE = "Europe/Paris"
DEFAULT_SEED = 42
DEFAULT_N8N_HIGH_THRESHOLD = 0.75
DEFAULT_N8N_MEDIUM_THRESHOLD = 0.45
RUNTIME_CONFIG_RELATIVE_PATH = Path("config") / "notebook_runtime.yaml"


@dataclass(frozen=True)
class NotebookRuntimeConfig:
    project_root: Path
    data_raw_dir: Path
    data_interim_dir: Path
    data_processed_dir: Path
    models_dir: Path
    reports_dir: Path
    notebooks_dir: Path
    n8n_dir: Path
    src_dir: Path
    raw_db_path: Path
    dataset_manifest_path: Path
    timezone_name: str
    seed: int
    n8n_high_threshold: float
    n8n_medium_threshold: float
    run_timestamp: datetime

    @property
    def run_date_tag(self) -> str:
        return self.run_timestamp.strftime("%Y%m%d")

    @property
    def run_datetime_label(self) -> str:
        return self.run_timestamp.strftime("%Y-%m-%d %H:%M %Z")


GLOBAL_NOTEBOOK_SEED = DEFAULT_SEED


def resolve_project_root() -> Path:
    candidate_roots = [Path.cwd().resolve(), *Path.cwd().resolve().parents]
    for candidate in candidate_roots:
        if (candidate / "data" / "raw" / "churn_sqlite_db.sqlite").exists():
            return candidate
        nested_candidate = candidate / "daily-customer-churn-predictor"
        if (nested_candidate / "data" / "raw" / "churn_sqlite_db.sqlite").exists():
            return nested_candidate
    raise FileNotFoundError("Could not resolve project root containing data/raw/churn_sqlite_db.sqlite")


def load_runtime_settings(project_root: Path | None = None) -> dict:
    root = project_root or resolve_project_root()
    config_path = root / RUNTIME_CONFIG_RELATIVE_PATH
    if not config_path.exists():
        return {
            "seed": DEFAULT_SEED,
            "timezone": DEFAULT_TIMEZONE,
            "n8n_thresholds": {"high": DEFAULT_N8N_HIGH_THRESHOLD, "medium": DEFAULT_N8N_MEDIUM_THRESHOLD},
            "dataset_manifest_path": "data/DATASET_MANIFEST.json",
            "source_dataset_path": "data/raw/churn_sqlite_db.sqlite",
        }
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def build_runtime_config(
    timezone_name: str | None = None,
    seed: int | None = None,
) -> NotebookRuntimeConfig:
    project_root = resolve_project_root()
    settings = load_runtime_settings(project_root)
    resolved_timezone = timezone_name or settings.get("timezone", DEFAULT_TIMEZONE)
    resolved_seed = int(seed if seed is not None else settings.get("seed", DEFAULT_SEED))
    thresholds = settings.get("n8n_thresholds", {}) or {}
    logical_date = os.environ.get("NOTEBOOK_LOGICAL_DATE") or settings.get("logical_date")
    if logical_date:
        run_timestamp = datetime.fromisoformat(f"{logical_date}T00:00:00").replace(tzinfo=ZoneInfo(resolved_timezone))
    else:
        current_local = datetime.now(ZoneInfo(resolved_timezone))
        run_timestamp = current_local.replace(hour=0, minute=0, second=0, microsecond=0)
    source_dataset_path = Path(settings.get("source_dataset_path", "data/raw/churn_sqlite_db.sqlite"))
    dataset_manifest_path = Path(settings.get("dataset_manifest_path", "data/DATASET_MANIFEST.json"))
    config = NotebookRuntimeConfig(
        project_root=project_root,
        data_raw_dir=project_root / "data" / "raw",
        data_interim_dir=project_root / "data" / "interim",
        data_processed_dir=project_root / "data" / "processed",
        models_dir=project_root / "models",
        reports_dir=project_root / "reports",
        notebooks_dir=project_root / "notebooks",
        n8n_dir=project_root / "n8n",
        src_dir=project_root / "src",
        raw_db_path=project_root / source_dataset_path,
        dataset_manifest_path=project_root / dataset_manifest_path,
        timezone_name=resolved_timezone,
        seed=resolved_seed,
        n8n_high_threshold=float(thresholds.get("high", DEFAULT_N8N_HIGH_THRESHOLD)),
        n8n_medium_threshold=float(thresholds.get("medium", DEFAULT_N8N_MEDIUM_THRESHOLD)),
        run_timestamp=run_timestamp,
    )
    config.data_interim_dir.mkdir(parents=True, exist_ok=True)
    config.data_processed_dir.mkdir(parents=True, exist_ok=True)
    config.models_dir.mkdir(parents=True, exist_ok=True)
    config.reports_dir.mkdir(parents=True, exist_ok=True)
    config.n8n_dir.mkdir(parents=True, exist_ok=True)
    return config


def apply_global_seed(seed: int | None = None) -> int:
    resolved_seed = GLOBAL_NOTEBOOK_SEED if seed is None else int(seed)
    random.seed(resolved_seed)
    np.random.seed(resolved_seed)
    return resolved_seed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dataset_manifest(config: NotebookRuntimeConfig) -> dict:
    manifest = json.loads(config.dataset_manifest_path.read_text(encoding="utf-8"))
    dataset_path = config.project_root / manifest["source_file"]
    actual_sha256 = sha256_file(dataset_path)
    actual_size = dataset_path.stat().st_size
    if actual_sha256 != manifest["expected_sha256"]:
        raise RuntimeError(
            f"Dataset checksum mismatch for {dataset_path}: expected {manifest['expected_sha256']}, got {actual_sha256}"
        )
    if actual_size != int(manifest["expected_size_bytes"]):
        raise RuntimeError(
            f"Dataset size mismatch for {dataset_path}: expected {manifest['expected_size_bytes']}, got {actual_size}"
        )
    return {
        "dataset_name": manifest["dataset_name"],
        "source_file": manifest["source_file"],
        "expected_sha256": manifest["expected_sha256"],
        "expected_size_bytes": int(manifest["expected_size_bytes"]),
        "version": manifest.get("version"),
        "license": manifest.get("license"),
    }


def current_git_sha(project_root: Path) -> str | None:
    git_root_override = os.environ.get("NOTEBOOK_RUNTIME_GIT_ROOT")
    git_lookup_root = Path(git_root_override).resolve() if git_root_override else project_root
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=git_lookup_root,
            check=True,
            capture_output=True,
            text=True,
        )
        git_sha = result.stdout.strip()
        return git_sha or None
    except (subprocess.CalledProcessError, OSError):
        return None


def build_model_manifest(
    *,
    config: NotebookRuntimeConfig,
    dataset_manifest: dict,
    model_output_path: Path,
    train_snapshot_keys: Iterable[str],
    validation_snapshot_keys: Iterable[str],
    test_snapshot_keys: Iterable[str],
    model_name: str,
    model_version: str,
    run_id: str,
    pipeline_tag: str,
    hyperparameters: dict,
    metrics: dict,
) -> dict:
    serialized_model_sha256 = sha256_file(model_output_path)
    return {
        "run_id": run_id,
        "model_version": model_version,
        "pipeline_tag": pipeline_tag,
        "git_sha": current_git_sha(config.project_root),
        "dataset": {
            "source_file": dataset_manifest["source_file"],
            "sha256": dataset_manifest["expected_sha256"],
            "version": dataset_manifest.get("version"),
            "license": dataset_manifest.get("license"),
        },
        "seed": config.seed,
        "split": {
            "train_snapshot_keys": sorted(str(v) for v in train_snapshot_keys),
            "validation_snapshot_keys": sorted(str(v) for v in validation_snapshot_keys),
            "test_snapshot_keys": sorted(str(v) for v in test_snapshot_keys),
            "split_seed": config.seed,
        },
        "model": {
            "name": model_name,
            "hyperparameters": hyperparameters,
            "artifact_path": str(model_output_path.relative_to(config.project_root)),
            "artifact_sha256": serialized_model_sha256,
        },
        "metrics": metrics,
        "timestamp": config.run_timestamp.isoformat(),
    }


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def extract_artifact_tag(path: Path) -> str:
    return path.stem.split("_")[-1]


def resolve_latest_artifact(directory: Path, pattern: str) -> Path:
    candidates = sorted(directory.glob(pattern))
    if not candidates:
        raise FileNotFoundError(f"No artifact matched pattern '{pattern}' in {directory}")
    return candidates[-1]


def resolve_required_artifact(directory: Path, prefix: str, run_date_tag: str, suffix: str) -> Path:
    candidate = directory / f"{prefix}_{run_date_tag}.{suffix}"
    if not candidate.exists():
        raise FileNotFoundError(f"Missing required artifact for run_date_tag={run_date_tag}: {candidate}")
    return candidate


def resolve_named_artifact(directory: Path, filename: str | None) -> Path | None:
    if not filename:
        return None
    candidate = directory / filename
    return candidate if candidate.exists() else None


def _resolve_bundle_source_artifacts(processed_dir: Path, metadata: dict):
    compatibility_artifacts = metadata.get("compatibility_artifacts") or {}
    prediction_path = resolve_named_artifact(processed_dir, compatibility_artifacts.get("prediction"))
    explainability_path = resolve_named_artifact(
        processed_dir,
        compatibility_artifacts.get("explainability") or compatibility_artifacts.get("explainability_proxy"),
    )
    if prediction_path and explainability_path:
        feature_path = resolve_named_artifact(processed_dir, compatibility_artifacts.get("feature"))
        run_date_tag = metadata.get("run_date_tag") or explainability_path.stem.split("_")[-1]
        return run_date_tag, feature_path, prediction_path, explainability_path

    source_artifacts = metadata.get("source_artifacts") or {}
    prediction_path = resolve_named_artifact(processed_dir, source_artifacts.get("prediction"))
    explainability_path = resolve_named_artifact(
        processed_dir,
        source_artifacts.get("explainability") or source_artifacts.get("explainability_proxy"),
    )
    if prediction_path and explainability_path:
        feature_path = resolve_named_artifact(processed_dir, source_artifacts.get("feature"))
        run_date_tag = metadata.get("run_date_tag") or explainability_path.stem.split("_")[-1]
        return run_date_tag, feature_path, prediction_path, explainability_path
    return None


def _artifact_key_set(path: Path):
    df = pd.read_parquet(path, columns=["customer_unique_id", "snapshot_key"])
    return set(zip(df["customer_unique_id"].astype(str), df["snapshot_key"].astype(str)))


def select_consistent_scoring_bundle(models_dir: Path, processed_dir: Path):
    bundle_candidates = sorted(models_dir.glob("churn_scoring_package_*.joblib"), reverse=True)
    prediction_candidates = sorted(processed_dir.glob("churn_predictions_*.parquet"), reverse=True)
    explainability_candidates = sorted(processed_dir.glob("churn_explainability_*.parquet"), reverse=True)

    for candidate in bundle_candidates:
        bundle = joblib.load(candidate)
        metadata = bundle.get("metadata", {})
        explicit_source_resolution = _resolve_bundle_source_artifacts(processed_dir, metadata)
        if explicit_source_resolution:
            run_date_tag, _, prediction_candidate, explainability_candidate = explicit_source_resolution
            return candidate, bundle, run_date_tag, prediction_candidate, explainability_candidate

        run_date_tag = metadata.get("run_date_tag")
        if run_date_tag:
            prediction_candidate = processed_dir / f"churn_predictions_{run_date_tag}.parquet"
            explainability_candidate = processed_dir / f"churn_explainability_{run_date_tag}.parquet"
            if prediction_candidate.exists() and explainability_candidate.exists():
                return candidate, bundle, run_date_tag, prediction_candidate, explainability_candidate

        for prediction_candidate in prediction_candidates:
            for explainability_candidate in explainability_candidates:
                if _artifact_key_set(prediction_candidate) == _artifact_key_set(explainability_candidate):
                    resolved_tag = explainability_candidate.stem.split("_")[-1]
                    metadata.setdefault("resolved_prediction_file", prediction_candidate.name)
                    metadata.setdefault("resolved_explainability_file", explainability_candidate.name)
                    metadata.setdefault("run_date_tag", resolved_tag)
                    bundle["metadata"] = metadata
                    return candidate, bundle, resolved_tag, prediction_candidate, explainability_candidate

    raise FileNotFoundError(
        "No scoring bundle matched a consistent prediction/explainability artifact pair, even after compatibility fallback."
    )


def resolve_latest_model_artifact(models_dir: Path, prefix: str):
    return resolve_latest_artifact(models_dir, f"{prefix}_*.joblib")


def resolve_feature_artifact(processed_dir: Path, preferred_run_date_tag: str | None = None) -> Path:
    if preferred_run_date_tag:
        preferred = processed_dir / f"churn_features_{preferred_run_date_tag}.parquet"
        if preferred.exists():
            return preferred
    return resolve_latest_artifact(processed_dir, "churn_features_*.parquet")


def resolve_latest_training_run_artifacts(processed_dir: Path, models_dir: Path) -> dict:
    model_candidates = sorted(models_dir.glob("churn_model_*.joblib"))
    if not model_candidates:
        raise FileNotFoundError(f"No training model artifact found in {models_dir}")
    model_path = model_candidates[-1]
    run_date_tag = extract_artifact_tag(model_path)

    feature_path = resolve_required_artifact(processed_dir, "churn_features", run_date_tag, "parquet")
    prediction_path = resolve_required_artifact(processed_dir, "churn_predictions", run_date_tag, "parquet")
    metrics_path = resolve_required_artifact(processed_dir, "churn_model_metrics", run_date_tag, "csv")
    comparison_path = resolve_required_artifact(processed_dir, "churn_model_comparison", run_date_tag, "csv")
    manifest_path = resolve_required_artifact(processed_dir, "model_manifest", run_date_tag, "json")

    diagnostics_path = processed_dir / f"churn_diagnostics_{run_date_tag}.csv"
    explainability_path = processed_dir / f"churn_explainability_{run_date_tag}.parquet"
    actions_path = processed_dir / f"retention_actions_{run_date_tag}.parquet"
    scoring_package_path = models_dir / f"churn_scoring_package_{run_date_tag}.joblib"
    smoke_test_path = processed_dir / f"churn_inference_smoke_test_{run_date_tag}.parquet"

    return {
        "run_date_tag": run_date_tag,
        "model_path": model_path,
        "feature_path": feature_path,
        "prediction_path": prediction_path,
        "metrics_path": metrics_path,
        "comparison_path": comparison_path,
        "manifest_path": manifest_path,
        "diagnostics_path": diagnostics_path,
        "explainability_path": explainability_path,
        "actions_path": actions_path,
        "scoring_package_path": scoring_package_path,
        "smoke_test_path": smoke_test_path,
    }


def preserve_existing_bundle_lineage(bundle_path: Path, metadata: dict) -> dict:
    if not bundle_path.exists():
        return metadata

    existing_bundle = joblib.load(bundle_path)
    if not isinstance(existing_bundle, dict):
        return metadata

    existing_metadata = existing_bundle.get("metadata", {})
    if not isinstance(existing_metadata, dict):
        return metadata

    merged = dict(metadata)
    for key in ("run_date_tag", "run_id", "model_version", "pipeline_tag", "restoration_note"):
        if existing_metadata.get(key):
            merged[key] = existing_metadata[key]

    existing_source_artifacts = existing_metadata.get("source_artifacts")
    if existing_source_artifacts:
        merged["source_artifacts"] = existing_source_artifacts

    existing_compatibility_artifacts = existing_metadata.get("compatibility_artifacts")
    if existing_compatibility_artifacts:
        merged["compatibility_artifacts"] = existing_compatibility_artifacts

    return merged


def assign_n8n_tier(
    probability: float,
    high_threshold: float = DEFAULT_N8N_HIGH_THRESHOLD,
    medium_threshold: float = DEFAULT_N8N_MEDIUM_THRESHOLD,
) -> str:
    if probability >= high_threshold:
        return "HIGH"
    if probability >= medium_threshold:
        return "MEDIUM"
    return "LOW"
