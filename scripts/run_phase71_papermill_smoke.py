#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = [
    '01_data_cleaning.ipynb',
    '02_eda_exploratory.ipynb',
    '03_feature_engineering.ipynb',
    '04_model_training.ipynb',
    '05_model_evaluation_diagnostics.ipynb',
    '06_churn_attribution_explainability.ipynb',
    '07_model_deployment_preparation.ipynb',
    '08_n8n_orchestration.ipynb',
    '09_reporting_dashboard.ipynb',
]
HASH_TARGETS = [
    'data/interim/client_database_clean_20260814.parquet',
    'data/processed/churn_features_20260814.parquet',
    'models/churn_model_20260814.joblib',
    'data/processed/churn_predictions_20260814.parquet',
    'data/processed/churn_model_metrics_20260814.csv',
    'data/processed/churn_model_comparison_20260814.csv',
    'data/processed/churn_diagnostics_20260814.csv',
    'data/processed/churn_explainability_20260814.parquet',
    'models/churn_scoring_package_20260814.joblib',
    'data/processed/churn_inference_smoke_test_20260814.parquet',
    'data/processed/retention_actions_20260814.parquet',
    'data/processed/model_manifest_20260814.json',
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_git_reference_root() -> Path | None:
    for candidate in [PROJECT_ROOT, *PROJECT_ROOT.parents]:
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                cwd=candidate,
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                return candidate
        except Exception:
            continue
    return None


def run_notebook(copy_root: Path, notebook_name: str, git_reference_root: Path | None) -> None:
    notebooks_dir = copy_root / 'notebooks'
    out_dir = copy_root / 'tmp' / 'papermill_outputs'
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(copy_root / 'src')
    env['NOTEBOOK_LOGICAL_DATE'] = '2026-08-14'
    if git_reference_root is not None:
        env['NOTEBOOK_RUNTIME_GIT_ROOT'] = str(git_reference_root)
    cmd = [
        sys.executable,
        '-m',
        'papermill',
        notebook_name,
        str(out_dir / notebook_name),
        '-k',
        'python3',
    ]
    subprocess.run(cmd, cwd=notebooks_dir, env=env, check=True)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit('Usage: run_phase71_papermill_smoke.py <clean-copy-path> <report-json-path>')
    copy_root = Path(sys.argv[1]).resolve()
    report_path = Path(sys.argv[2]).resolve()
    if copy_root.exists():
        shutil.rmtree(copy_root)
    shutil.copytree(PROJECT_ROOT, copy_root)
    git_reference_root = resolve_git_reference_root()

    for rel in HASH_TARGETS:
        target = copy_root / rel
        if target.exists():
            target.unlink()

    for notebook_name in NOTEBOOKS:
        run_notebook(copy_root, notebook_name, git_reference_root)

    hashes = {}
    for rel in HASH_TARGETS:
        target = copy_root / rel
        if not target.exists():
            raise FileNotFoundError(f'Expected smoke artifact missing: {target}')
        hashes[rel] = sha256_file(target)

    report = {
        'copy_root': str(copy_root),
        'logical_date': '2026-08-14',
        'git_reference_root': str(git_reference_root) if git_reference_root else None,
        'git_sha': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=git_reference_root, check=True, capture_output=True, text=True).stdout.strip() if git_reference_root else None,
        'artifacts': hashes,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
