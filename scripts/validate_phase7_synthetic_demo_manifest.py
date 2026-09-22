from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from evidence.phase7_artifacts import SYNTHETIC_DEMO_MODE, phase7_namespace_dir

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    namespace_dir = phase7_namespace_dir(PROJECT_ROOT, SYNTHETIC_DEMO_MODE)
    manifest_path = namespace_dir / "synthetic_demo__phase7_manifest_20260727.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    rows = []
    for logical_name, artifact in manifest["artifacts"].items():
        path = PROJECT_ROOT / artifact["path"]
        actual_hash = sha256_file(path)
        actual_size = path.stat().st_size
        rows.append({
            "logical_name": logical_name,
            "name": artifact["name"],
            "path": artifact["path"],
            "expected_sha256": artifact["sha256"],
            "actual_sha256": actual_hash,
            "expected_size": artifact["size_bytes"],
            "actual_size": actual_size,
            "match": actual_hash == artifact["sha256"] and actual_size == artifact["size_bytes"],
        })

    ok = all(row["match"] for row in rows)
    payload = {
        "manifest": str(manifest_path),
        "mode": manifest["mode"],
        "run_date": manifest["run_date"],
        "artifact_count": len(rows),
        "all_match": ok,
        "artifacts": rows,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    LOGGER.info("Synthetic demo manifest validation %s", "passed" if ok else "failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
