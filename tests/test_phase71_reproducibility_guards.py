from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from notebook_runtime import apply_global_seed


VERIFY_SOURCE_DATASET_PATH = PROJECT_ROOT / "scripts" / "verify_source_dataset.py"
spec = importlib.util.spec_from_file_location("verify_source_dataset", VERIFY_SOURCE_DATASET_PATH)
verify_source_dataset = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(verify_source_dataset)


def test_verify_source_dataset_fails_explicitly_on_checksum_mismatch(tmp_path, monkeypatch):
    dataset_dir = tmp_path / "data" / "raw"
    dataset_dir.mkdir(parents=True)
    dataset_path = dataset_dir / "fake.sqlite"
    dataset_path.write_bytes(b"phase71-checksum-mismatch")

    manifest_path = tmp_path / "data" / "DATASET_MANIFEST.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_name": "fake-dataset",
                "source_file": "data/raw/fake.sqlite",
                "expected_sha256": "0" * 64,
                "expected_size_bytes": dataset_path.stat().st_size,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(verify_source_dataset, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(verify_source_dataset, "MANIFEST_PATH", manifest_path)

    with pytest.raises(RuntimeError, match=r"Dataset checksum mismatch"):
        verify_source_dataset.main()


def test_apply_global_seed_produces_deterministic_random_streams():
    apply_global_seed(123)
    first_python = [random.random() for _ in range(3)]
    first_numpy = np.random.default_rng(123).normal(size=3)
    first_global_numpy = np.random.rand(3)

    apply_global_seed(123)
    second_python = [random.random() for _ in range(3)]
    second_numpy = np.random.default_rng(123).normal(size=3)
    second_global_numpy = np.random.rand(3)

    apply_global_seed(456)
    third_python = [random.random() for _ in range(3)]
    third_global_numpy = np.random.rand(3)

    assert first_python == second_python
    assert np.allclose(first_numpy, second_numpy)
    assert np.allclose(first_global_numpy, second_global_numpy)
    assert first_python != third_python
    assert not np.allclose(first_global_numpy, third_global_numpy)
