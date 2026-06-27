#!/usr/bin/env bash
python3 - <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8088/api/status', timeout=5) as r:
        data=json.loads(r.read().decode())
    sys.exit(0 if data.get('status') is not None else 1)
except Exception:
    sys.exit(1)
PY
