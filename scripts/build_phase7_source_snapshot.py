from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_extractor import build_and_write_phase7_extraction_snapshot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 7 RSS-only source snapshot.")
    parser.add_argument("--run-date", help="Optional YYYYMMDD run date for the output snapshot filename.")
    parser.add_argument("--checked-at", help="Optional ISO8601 timestamp override for deterministic runs/tests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_and_write_phase7_extraction_snapshot(
        project_root=PROJECT_ROOT,
        run_date=args.run_date,
        checked_at=args.checked_at,
    )
    LOGGER.info("Phase 7 source snapshot created at %s", payload["snapshot_path"])
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
