from __future__ import annotations

import os
import json
from pathlib import Path

REAL_MODE = "real"
SYNTHETIC_DEMO_MODE = "synthetic_demo"
DEFAULT_MODE = REAL_MODE
MODE_ENV_VAR = "MODE"
SYNTHETIC_WARNING = "DATOS SINTÉTICOS — NO SON RESULTADOS REALES"
SYNTHETIC_FILENAME_PREFIX = "synthetic_demo__"
SYNTHETIC_MANIFEST_VERSION = "phase7_synthetic_demo_v1"


class SyntheticDemoManifestError(FileNotFoundError):
    pass


class UnsupportedPhase7ModeError(ValueError):
    pass


def resolve_phase7_mode(mode: str | None = None) -> str:
    candidate = (mode or os.getenv(MODE_ENV_VAR) or DEFAULT_MODE).strip() or DEFAULT_MODE
    if candidate == SYNTHETIC_DEMO_MODE:
        return SYNTHETIC_DEMO_MODE
    if candidate in {REAL_MODE, DEFAULT_MODE}:
        return REAL_MODE
    raise UnsupportedPhase7ModeError(
        f"Unsupported Phase 7 mode '{candidate}'. Supported modes: {REAL_MODE}, {SYNTHETIC_DEMO_MODE}"
    )


def is_synthetic_demo_mode(mode: str | None = None) -> bool:
    return resolve_phase7_mode(mode) == SYNTHETIC_DEMO_MODE


def phase7_namespace_dir(project_root: Path, mode: str | None = None) -> Path:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == SYNTHETIC_DEMO_MODE:
        return project_root / "data" / "synthetic_demo"
    return project_root / "data" / "processed"


def phase7_reports_dir(project_root: Path, mode: str | None = None) -> Path:
    resolved_mode = resolve_phase7_mode(mode)
    if resolved_mode == SYNTHETIC_DEMO_MODE:
        return project_root / "reports" / "synthetic_demo"
    return project_root / "reports"


def namespaced_artifact_name(base_name: str, mode: str | None = None) -> str:
    if is_synthetic_demo_mode(mode):
        return f"{SYNTHETIC_FILENAME_PREFIX}{base_name}"
    return base_name


def namespaced_artifact_path(project_root: Path, base_name: str, mode: str | None = None) -> Path:
    return phase7_namespace_dir(project_root, mode) / namespaced_artifact_name(base_name, mode)


def namespaced_report_path(project_root: Path, base_name: str, mode: str | None = None) -> Path:
    return phase7_reports_dir(project_root, mode) / namespaced_artifact_name(base_name, mode)


def synthetic_manifest_path(project_root: Path, run_date: str) -> Path:
    return phase7_namespace_dir(project_root, SYNTHETIC_DEMO_MODE) / f"{SYNTHETIC_FILENAME_PREFIX}phase7_manifest_{run_date}.json"


def load_synthetic_manifest(project_root: Path, run_date: str | None = None) -> dict:
    namespace_dir = phase7_namespace_dir(project_root, SYNTHETIC_DEMO_MODE)
    if run_date:
        manifest_path = synthetic_manifest_path(project_root, run_date)
        if not manifest_path.exists():
            raise SyntheticDemoManifestError(
                f"Synthetic demo manifest not found for run_date {run_date}: {manifest_path}"
            )
    else:
        manifests = sorted(namespace_dir.glob(f"{SYNTHETIC_FILENAME_PREFIX}phase7_manifest_*.json"))
        if not manifests:
            raise SyntheticDemoManifestError(f"No synthetic demo manifest found under {namespace_dir}")
        manifest_path = manifests[-1]
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if payload.get("manifest_version") != SYNTHETIC_MANIFEST_VERSION:
        raise SyntheticDemoManifestError(
            f"Unsupported synthetic demo manifest version at {manifest_path}: {payload.get('manifest_version')}"
        )
    return payload


def resolve_synthetic_manifest_run_date(project_root: Path, run_date: str | None = None) -> str:
    manifest = load_synthetic_manifest(project_root, run_date)
    resolved_run_date = str(manifest.get("run_date") or "").strip()
    if not resolved_run_date:
        raise SyntheticDemoManifestError("Synthetic demo manifest is missing run_date")
    return resolved_run_date


def resolve_synthetic_runtime_artifact(project_root: Path, logical_name: str, run_date: str | None = None) -> Path:
    manifest = load_synthetic_manifest(project_root, run_date)
    artifacts = manifest.get("artifacts") or {}
    entry = artifacts.get(logical_name)
    if not entry:
        raise SyntheticDemoManifestError(
            f"Synthetic demo manifest for run_date {manifest.get('run_date')} is missing required artifact '{logical_name}'"
        )
    relative_path = Path(str(entry.get("path") or "").strip())
    if not relative_path.parts:
        raise SyntheticDemoManifestError(
            f"Synthetic demo manifest artifact '{logical_name}' is missing path"
        )
    namespace_dir = phase7_namespace_dir(project_root, SYNTHETIC_DEMO_MODE).resolve()
    artifact_path = (project_root / relative_path).resolve()
    if namespace_dir not in artifact_path.parents:
        raise SyntheticDemoManifestError(
            f"Synthetic demo manifest artifact '{logical_name}' escapes synthetic namespace: {artifact_path}"
        )
    if not artifact_path.exists():
        raise SyntheticDemoManifestError(
            f"Synthetic demo manifest artifact '{logical_name}' does not exist: {artifact_path}"
        )
    return artifact_path


def assert_phase7_mode_namespace(path: Path, mode: str | None = None) -> Path:
    resolved = path.resolve()
    expected_root = phase7_namespace_dir(path.parents[2], mode).resolve()
    if expected_root not in resolved.parents and resolved != expected_root:
        raise ValueError(f"Artifact path {resolved} escapes expected namespace {expected_root} for mode={resolve_phase7_mode(mode)}")
    return resolved
