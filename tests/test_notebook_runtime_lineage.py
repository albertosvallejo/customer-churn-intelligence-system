from pathlib import Path
import sys

import joblib
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from notebook_runtime import preserve_existing_bundle_lineage, select_consistent_scoring_bundle


def test_select_consistent_scoring_bundle_prefers_compatibility_artifacts_when_historical_lineage_is_unverified(tmp_path):
    models_dir = tmp_path / "models"
    processed_dir = tmp_path / "processed"
    models_dir.mkdir()
    processed_dir.mkdir()

    pd.DataFrame({"customer_unique_id": ["a"], "snapshot_key": ["s1"], "value": [1]}).to_parquet(
        processed_dir / "churn_predictions_20260506.parquet", index=False
    )
    pd.DataFrame({"customer_unique_id": ["a"], "snapshot_key": ["s1"], "value": [1]}).to_parquet(
        processed_dir / "churn_predictions_20260814.parquet", index=False
    )
    pd.DataFrame({"customer_unique_id": ["a"], "snapshot_key": ["s1"], "value": [1]}).to_parquet(
        processed_dir / "churn_explainability_20260519.parquet", index=False
    )

    bundle_path = models_dir / "churn_scoring_package_20260519.joblib"
    joblib.dump(
        {
            "metadata": {
                "run_date_tag": "20260519",
                "source_artifacts": {
                    "feature": "unknown_unverified_historical_lineage",
                    "prediction": "unknown_unverified_historical_lineage",
                    "explainability": "churn_explainability_20260519.parquet",
                },
                "compatibility_artifacts": {
                    "feature": "churn_features_20260506.parquet",
                    "prediction": "churn_predictions_20260506.parquet",
                    "explainability": "churn_explainability_20260519.parquet",
                },
            },
            "model_package": {},
        },
        bundle_path,
    )

    selected_bundle, _, run_date_tag, prediction_path, explainability_path = select_consistent_scoring_bundle(
        models_dir, processed_dir
    )

    assert selected_bundle == bundle_path
    assert run_date_tag == "20260519"
    assert prediction_path.name == "churn_predictions_20260506.parquet"
    assert explainability_path.name == "churn_explainability_20260519.parquet"


def test_preserve_existing_bundle_lineage_keeps_unverified_historical_lineage_and_compatibility_artifacts(tmp_path):
    bundle_path = tmp_path / "churn_scoring_package_20260519.joblib"
    joblib.dump(
        {
            "metadata": {
                "run_date_tag": "20260519",
                "run_id": "canonical_v2c_20260519",
                "model_version": "v2_20260519",
                "pipeline_tag": "canonical_v2c_phase2",
                "source_artifacts": {
                    "model": "churn_scoring_package_20260519.joblib",
                    "feature": "unknown_unverified_historical_lineage",
                    "prediction": "unknown_unverified_historical_lineage",
                    "explainability": "churn_explainability_20260519.parquet",
                },
                "compatibility_artifacts": {
                    "feature": "churn_features_20260506.parquet",
                    "prediction": "churn_predictions_20260506.parquet",
                    "explainability": "churn_explainability_20260519.parquet",
                },
            },
            "model_package": {},
        },
        bundle_path,
    )

    merged = preserve_existing_bundle_lineage(
        bundle_path,
        {
            "run_date_tag": "20260814",
            "run_id": "canonical_v2c_20260814",
            "model_version": "v2_20260814",
            "pipeline_tag": "canonical_v2c_phase2",
            "source_artifacts": {
                "model": "churn_scoring_package_20260519.joblib",
                "feature": "churn_features_20260814.parquet",
                "prediction": "churn_predictions_20260814.parquet",
                "explainability": "churn_explainability_20260519.parquet",
            },
            "compatibility_artifacts": {
                "feature": "churn_features_20260814.parquet",
                "prediction": "churn_predictions_20260814.parquet",
                "explainability": "churn_explainability_20260519.parquet",
            },
        },
    )

    assert merged["run_date_tag"] == "20260519"
    assert merged["run_id"] == "canonical_v2c_20260519"
    assert merged["model_version"] == "v2_20260519"
    assert merged["source_artifacts"]["feature"] == "unknown_unverified_historical_lineage"
    assert merged["source_artifacts"]["prediction"] == "unknown_unverified_historical_lineage"
    assert merged["compatibility_artifacts"]["feature"] == "churn_features_20260506.parquet"
    assert merged["compatibility_artifacts"]["prediction"] == "churn_predictions_20260506.parquet"
