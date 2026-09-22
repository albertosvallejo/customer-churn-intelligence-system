#!/usr/bin/env bash
set -euo pipefail

export BASE_URL="${BASE_URL:-http://127.0.0.1:62881}"
export RUN_DATE="${RUN_DATE:-20260727}"
export PHASE7_TOKEN="${PHASE7_TOKEN:-}"

python3 - <<'PY'
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

base = os.environ["BASE_URL"].rstrip("/")
run_date = os.environ["RUN_DATE"]
token = os.environ.get("PHASE7_TOKEN", "")

checks = []

def fetch(path: str, *, expected_status: int = 200):
    req = urllib.request.Request(base + path)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", "ignore")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "ignore")
        status = exc.code
    if status != expected_status:
        raise SystemExit(f"FAIL {path}: expected {expected_status}, got {status}; body={body[:300]!r}")
    checks.append((path, status))
    return body

health_body = fetch("/health", expected_status=200)
health = json.loads(health_body)
if health.get("status") != "ok":
    raise SystemExit(f"FAIL /health payload: {health!r}")

for page_path, marker in [
    (f"/customer-churn/dashboard?run_date={run_date}", "CHURN CAMPAIGNS DASHBOARD"),
    (f"/customer-churn/dashboard/data?run_date={run_date}", '"status": "ok"'),
]:
    body = fetch(page_path, expected_status=200)
    if marker not in body:
        raise SystemExit(f"FAIL {page_path}: missing marker {marker!r}")

for page_path, marker in [
    (f"/customer-churn/tested-actions-approval?run_date={run_date}", "VivaMarket · Tested Actions Approval"),
    (f"/customer-churn/new-actions-testing?run_date={run_date}", "VivaMarket · New Actions Approval"),
]:
    body = fetch(page_path, expected_status=200)
    if marker not in body:
        raise SystemExit(f"FAIL {page_path}: missing marker {marker!r}")

if token:
    encoded = urllib.parse.quote(token, safe="")
    token_checks = [
        (f"/customer-churn/tested-actions-approval?run_date={run_date}&token={encoded}", "VivaMarket · Tested Actions Approval"),
        (f"/customer-churn/new-actions-testing?run_date={run_date}&token={encoded}", "VivaMarket · New Actions Approval"),
        (f"/customer-churn/tested-actions-approval/data?run_date={run_date}&token={encoded}", '"pending_pre_test_actions"'),
        (f"/customer-churn/new-actions-testing/data?run_date={run_date}&token={encoded}", '"pending_pre_test_actions"'),
    ]
    for path, marker in token_checks:
        body = fetch(path, expected_status=200)
        if marker not in body:
            raise SystemExit(f"FAIL {path}: missing marker {marker!r}")

print("demo_verify.sh OK")
for path, status in checks:
    print(f"{status} {path}")
PY
