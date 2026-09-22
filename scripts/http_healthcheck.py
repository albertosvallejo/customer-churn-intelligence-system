#!/usr/bin/env python3
import os
import sys
import urllib.error
import urllib.request

url = os.environ.get("HEALTHCHECK_URL") or (sys.argv[1] if len(sys.argv) > 1 else None)
if not url:
    raise SystemExit("Usage: http_healthcheck.py <url> or set HEALTHCHECK_URL")

try:
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.status != 200:
            raise SystemExit(f"Unexpected status: {response.status}")
except urllib.error.URLError as exc:
    raise SystemExit(str(exc))
