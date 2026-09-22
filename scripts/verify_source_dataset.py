#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger('verify_source_dataset')

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / 'data' / 'DATASET_MANIFEST.json'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    dataset_path = PROJECT_ROOT / manifest['source_file']
    if not dataset_path.exists():
        raise FileNotFoundError(f'Source dataset not found: {dataset_path}')

    actual_sha256 = sha256_file(dataset_path)
    actual_size = dataset_path.stat().st_size
    expected_sha256 = manifest['expected_sha256']
    expected_size = int(manifest['expected_size_bytes'])

    logger.info('Dataset path: %s', dataset_path)
    logger.info('Expected SHA-256: %s', expected_sha256)
    logger.info('Actual   SHA-256: %s', actual_sha256)
    logger.info('Expected size: %s', expected_size)
    logger.info('Actual   size: %s', actual_size)

    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f'Dataset checksum mismatch for {dataset_path}: expected {expected_sha256}, got {actual_sha256}'
        )
    if actual_size != expected_size:
        raise RuntimeError(
            f'Dataset size mismatch for {dataset_path}: expected {expected_size}, got {actual_size}'
        )

    logger.info('Dataset checksum verification passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
